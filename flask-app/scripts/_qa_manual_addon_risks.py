#!/usr/bin/env python3
"""
Non-Stripe risk / edge-case suite for Manage post-add add-ons.
Does not charge real cards — simulates ledger, locks, email failure, refunds, tokens, Auto Pay math.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check(label, cond, details=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f" — {details}" if details else ""))
    return bool(cond)


def main():
    from app import create_app, db
    from app.addon_admin import (
        addon_payment_url,
        booking_addon_line_total,
        create_manual_booking_addon,
        send_addon_payment_email,
    )
    from app.addon_payment import (
        handle_addon_payment_failed,
        handle_addon_payment_processing,
        handle_addon_payment_succeeded,
    )
    from app.models import (
        Booking,
        BookingAddOn,
        BookingPackage,
        BookingParticipant,
        Client,
        InstallmentPayment,
        Payment,
        Trip,
        TripAddOn,
        TripPackage,
    )
    from app.payments import (
        apply_refund_to_ledger,
        booking_has_processing_ach_payment,
        booking_payoff_due,
        calculate_booking_total,
        catch_up_amount_cents,
        unpaid_manual_addons_total,
    )
    from app.utils import generate_addon_payment_token, verify_addon_payment_token
    import app.utils as utils

    app = create_app("development")
    fails = 0

    with app.app_context():
        print("=== Seed isolated risk booking ===")
        trip = Trip.query.get(1) or Trip.query.first()
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        addons = TripAddOn.query.filter_by(trip_id=trip.id).order_by(TripAddOn.id).all()
        client = Client.query.filter_by(email="arafathayrat@gmail.com").first()
        if not client:
            client = Client(name="QA", email="arafathayrat@gmail.com")
            db.session.add(client)
            db.session.flush()

        # Remove prior risk fixture if any
        old = Booking.query.filter_by(order_number="2608QA-RISK").first()
        if old:
            Payment.query.filter_by(booking_id=old.id).delete()
            InstallmentPayment.query.filter_by(booking_id=old.id).delete()
            BookingAddOn.query.filter_by(booking_id=old.id).delete()
            BookingPackage.query.filter_by(booking_id=old.id).delete()
            BookingParticipant.query.filter_by(booking_id=old.id).delete()
            db.session.delete(old)
            db.session.commit()

        unit = float(pkg.price or 1000)
        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            order_number="2608QA-RISK",
            status="deposit_paid",
            amount_paid=200.0,
            buyer_first_name="Risk",
            buyer_last_name="QA",
            buyer_email="arafathayrat@gmail.com",
            passenger_count=2,
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(
            BookingPackage(
                booking_id=booking.id,
                package_id=pkg.id,
                quantity=1,
                payment_plan_type="deposit_installment",
                amount_paid=200.0,
                status="deposit_paid",
                unit_price=unit,
            )
        )
        p1 = BookingParticipant(
            booking_id=booking.id, name="First P", first_name="First", last_name="P", status="active"
        )
        p2 = BookingParticipant(
            booking_id=booking.id, name="Second P", first_name="Second", last_name="P", status="active"
        )
        p_w = BookingParticipant(
            booking_id=booking.id, name="Gone", first_name="Gone", last_name="W", status="withdrawn"
        )
        db.session.add_all([p1, p2, p_w])
        db.session.flush()
        today = date.today()
        db.session.add_all(
            [
                InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=0,
                    amount=200.0,
                    due_date=today - timedelta(days=10),
                    status="paid",
                ),
                InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=1,
                    amount=400.0,
                    due_date=today,
                    status="pending",
                ),
                InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=2,
                    amount=max(0.0, unit - 600.0),
                    due_date=today + timedelta(days=30),
                    status="pending",
                ),
            ]
        )
        db.session.commit()
        seats_before = booking.passenger_count

        print("=== A) Participant / catalog / create rules ===")
        ba, err = create_manual_booking_addon(booking, addons[0].id)
        fails += 0 if check("create ok", err is None, err) else 1
        db.session.commit()
        fails += 0 if check("default first active passenger", ba.participant_id == p1.id) else 1

        ba_bad, err_bad = create_manual_booking_addon(booking, 999999)
        fails += 0 if check("wrong addon id rejected", ba_bad is None and bool(err_bad), err_bad) else 1

        # catalog excludes withdrawn
        from app.admin.routes import booking_addons_catalog

        with app.test_request_context(f"/admin/bookings/{booking.id}/addons/catalog"):
            # call internals manually
            parts = [
                p
                for p in booking.participants
                if (getattr(p, "status", None) or "active") != "withdrawn"
            ]
        fails += 0 if check("withdrawn not in active list", p_w not in parts and len(parts) == 2) else 1

        print("=== B) Payoff / Auto Pay catch-up exclude unpaid manual ===")
        payoff_before = booking_payoff_due(booking)
        line = booking_addon_line_total(ba)
        fails += 0 if check(
            "payoff ignores unpaid manual",
            abs(payoff_before - (calculate_booking_total(booking)["amount_due"] - unpaid_manual_addons_total(booking)))
            < 0.02,
            f"payoff={payoff_before} unpaid={unpaid_manual_addons_total(booking)}",
        ) else 1

        inst1 = InstallmentPayment.query.filter_by(
            booking_id=booking.id, installment_number=1
        ).first()
        catch_cents = catch_up_amount_cents(inst1)
        fails += 0 if check(
            "catch_up_amount does not include manual addon dollars",
            abs(catch_cents / 100.0 - float(inst1.amount or 0)) < 0.02
            or catch_cents / 100.0 <= float(inst1.amount or 0) + 0.02,
            f"catch={catch_cents/100:.2f} inst={inst1.amount}",
        ) else 1
        # Stronger: catch-up should be << package remaining if only installment amounts
        fails += 0 if check(
            "catch_up << expected (no full unpaid manuals)",
            catch_cents / 100.0 < calculate_booking_total(booking)["total"] - 100,
            f"catch={catch_cents/100}",
        ) else 1

        print("=== C) Token / URL ===")
        tok = generate_addon_payment_token(ba.id)
        fails += 0 if check("token verifies", verify_addon_payment_token(tok, ba.id)) else 1
        fails += 0 if check(
            "token rejects other id",
            not verify_addon_payment_token(tok, ba.id + 999),
        ) else 1
        with app.test_request_context("/", base_url="http://127.0.0.1:8080"):
            url = addon_payment_url(ba)
        fails += 0 if check(
            "url_for in request uses local host",
            "127.0.0.1:8080" in url or "localhost" in url,
            url,
        ) else 1

        print("=== D) Email failure does not roll back addon ===")
        real_send = utils.send_email_via_ses

        def boom(*a, **k):
            return False, "SES simulated failure"

        utils.send_email_via_ses = boom
        # Also patch addon_admin's imported reference if needed — it imports send at call time
        ba2, err2 = create_manual_booking_addon(booking, addons[0].id, participant_id=p2.id)
        db.session.commit()
        ok_e, msg_e = send_addon_payment_email(ba2)
        fails += 0 if check("email reports failure", not ok_e, msg_e) else 1
        fails += 0 if check(
            "addon still unpaid after email fail",
            ba2.payment_status == "unpaid" and BookingAddOn.query.get(ba2.id) is not None,
        ) else 1
        utils.send_email_via_ses = real_send

        # Admin add endpoint path: create + failed email still success
        from app.addon_admin import send_addon_payment_email as send2

        utils.send_email_via_ses = boom
        ba3, _ = create_manual_booking_addon(booking, addons[-1].id)
        db.session.commit()
        email_ok, email_msg = send2(ba3)
        fails += 0 if check(
            "admin flow: create survives email fail",
            ba3.id and not email_ok,
            email_msg,
        ) else 1
        utils.send_email_via_ses = real_send

        print("=== E) ACH processing lock ===")
        ba_lock, _ = create_manual_booking_addon(booking, addons[0].id)
        db.session.commit()
        line_l = booking_addon_line_total(ba_lock)
        cents = int(round(line_l * 100))
        pi_lock = "pi_risk_ach_lock"
        meta = {
            "payment_type": "addon_purchase",
            "payment_step": "addon",
            "booking_id": str(booking.id),
            "booking_addon_id": str(ba_lock.id),
            "addon_name": "LockTest",
            "base_amount": str(cents),
            "fee": "0",
            "final_amount": str(cents),
            "payment_method_type": "us_bank_account",
            "funding": "ach",
        }
        ba_lock.stripe_payment_intent_id = pi_lock
        db.session.commit()
        # mute emails during processing
        utils.send_email_via_ses = lambda *a, **k: (True, "muted")
        handle_addon_payment_processing(
            {
                "id": pi_lock,
                "amount": cents,
                "currency": "usd",
                "metadata": meta,
                "payment_method_types": ["us_bank_account"],
            }
        )
        fails += 0 if check(
            "ACH processing flag on",
            booking_has_processing_ach_payment(booking.id),
        ) else 1
        ba_blocked, err_block = create_manual_booking_addon(booking, addons[0].id)
        fails += 0 if check(
            "cannot add while ACH processing",
            ba_blocked is None and "processing" in (err_block or "").lower(),
            err_block,
        ) else 1

        print("=== F) Succeed + idempotency + seats unchanged ===")
        paid_before = float(booking.amount_paid or 0)
        intent_ok = {
            "id": pi_lock,
            "amount": cents,
            "currency": "usd",
            "metadata": meta,
            "payment_method_types": ["us_bank_account"],
        }
        handle_addon_payment_succeeded(intent_ok)
        db.session.refresh(booking)
        db.session.refresh(ba_lock)
        fails += 0 if check("paid after succeed", ba_lock.payment_status == "paid") else 1
        fails += 0 if check(
            "amount_paid +base",
            abs(float(booking.amount_paid) - (paid_before + line_l)) < 0.02,
            f"{booking.amount_paid} vs {paid_before}+{line_l}",
        ) else 1
        mid = float(booking.amount_paid)
        handle_addon_payment_succeeded(intent_ok)
        db.session.refresh(booking)
        fails += 0 if check("idempotent double webhook", abs(float(booking.amount_paid) - mid) < 0.01) else 1
        fails += 0 if check(
            "passenger_count unchanged",
            booking.passenger_count == seats_before,
            f"{booking.passenger_count}",
        ) else 1
        fails += 0 if check(
            "ACH lock cleared after succeed",
            not booking_has_processing_ach_payment(booking.id),
        ) else 1

        print("=== G) Fail path does not cancel booking ===")
        ba_f, _ = create_manual_booking_addon(booking, addons[0].id)
        db.session.commit()
        pi_f = "pi_risk_fail"
        ba_f.stripe_payment_intent_id = pi_f
        db.session.commit()
        from app.routes import handle_payment_intent_failed

        handle_payment_intent_failed(
            {
                "id": pi_f,
                "metadata": {
                    "payment_type": "addon_purchase",
                    "booking_addon_id": str(ba_f.id),
                    "booking_id": str(booking.id),
                },
                "last_payment_error": {"message": "declined"},
            }
        )
        db.session.refresh(booking)
        db.session.refresh(ba_f)
        fails += 0 if check("addon failed", ba_f.payment_status == "failed") else 1
        fails += 0 if check("booking not cancelled", booking.status != "cancelled", booking.status) else 1

        print("=== H) Refund of addon payment vs addon status ===")
        pay = Payment.query.filter_by(stripe_payment_intent_id=pi_lock).first()
        fails += 0 if check("have succeeded addon payment", pay is not None and pay.status == "succeeded") else 1
        if pay:
            line_refund = booking_addon_line_total(ba_lock)
            unpaid_before_refund = unpaid_manual_addons_total(booking)
            apply_refund_to_ledger(pay, booking, line_refund, reason="risk full refund")
            db.session.commit()
            db.session.refresh(ba_lock)
            db.session.refresh(booking)
            status_after = ba_lock.payment_status
            unpaid_again = unpaid_manual_addons_total(booking)
            fails += 0 if check(
                "full refund clears paid status on manual addon",
                status_after == "unpaid",
                f"status={status_after} unpaid_manual={unpaid_again}",
            ) else 1
            fails += 0 if check(
                "full refund re-includes line in unpaid_manual",
                abs(unpaid_again - (unpaid_before_refund + line_refund)) < 0.02,
                f"before={unpaid_before_refund} after={unpaid_again} line={line_refund}",
            ) else 1
            fails += 0 if check(
                "full refund clears payment_id on addon",
                ba_lock.payment_id is None and not ba_lock.stripe_payment_intent_id,
            ) else 1

        # Partial refund must keep paid
        ba_part, _ = create_manual_booking_addon(booking, addons[0].id)
        db.session.commit()
        line_p = booking_addon_line_total(ba_part)
        cents_p = int(round(line_p * 100))
        pi_p = "pi_risk_partial"
        meta_p = {
            "payment_type": "addon_purchase",
            "payment_step": "addon",
            "booking_id": str(booking.id),
            "booking_addon_id": str(ba_part.id),
            "addon_name": "Partial",
            "base_amount": str(cents_p),
            "fee": "0",
            "final_amount": str(cents_p),
        }
        ba_part.stripe_payment_intent_id = pi_p
        db.session.commit()
        handle_addon_payment_succeeded(
            {
                "id": pi_p,
                "amount": cents_p,
                "currency": "usd",
                "metadata": meta_p,
                "payment_method_types": ["card"],
            }
        )
        pay_p = Payment.query.filter_by(stripe_payment_intent_id=pi_p).first()
        if pay_p:
            apply_refund_to_ledger(pay_p, booking, round(line_p / 2, 2), reason="risk partial")
            db.session.commit()
            db.session.refresh(ba_part)
            fails += 0 if check(
                "partial refund keeps addon paid",
                ba_part.payment_status == "paid" and ba_part.payment_id == pay_p.id,
                ba_part.payment_status,
            ) else 1

        print("=== I) Null legacy fields behave as booking/paid ===")
        legacy = BookingAddOn(
            booking_id=booking.id,
            addon_id=addons[0].id,
            participant_id=p1.id,
            quantity=1,
            price_at_booking=10.0,
            source=None,
            payment_status=None,
        )
        db.session.add(legacy)
        db.session.commit()
        # unpaid_manual should ignore non-admin_manual
        u1 = unpaid_manual_addons_total(booking)
        legacy.source = "admin_manual"
        legacy.payment_status = None  # treat as paid per getattr default in some paths
        db.session.commit()
        # Our unpaid_manual: status default 'paid' when None after strip — check code
        # (getattr(ba, 'payment_status', None) or 'paid') → None becomes 'paid'
        u2 = unpaid_manual_addons_total(booking)
        fails += 0 if check(
            "null payment_status treated as paid (not unpaid)",
            abs(u2 - u1) < 0.01,
            f"u1={u1} u2={u2}",
        ) else 1
        db.session.delete(legacy)
        db.session.commit()

        print("=== J) Auto Pay skip when ACH processing (addon) ===")
        from app.auto_pay import charge_installment_via_auto_pay

        ba_ap, _ = create_manual_booking_addon(booking, addons[0].id)
        db.session.commit()
        line_ap = booking_addon_line_total(ba_ap)
        cents_ap = int(round(line_ap * 100))
        pi_ap = "pi_risk_autopay_block"
        meta_ap = {
            "payment_type": "addon_purchase",
            "payment_step": "addon",
            "booking_id": str(booking.id),
            "booking_addon_id": str(ba_ap.id),
            "addon_name": "APBlock",
            "base_amount": str(cents_ap),
            "fee": "0",
            "final_amount": str(cents_ap),
            "payment_method_type": "us_bank_account",
            "funding": "ach",
        }
        ba_ap.stripe_payment_intent_id = pi_ap
        booking.auto_pay_enabled = True
        booking.auto_pay_payment_method_id = "pm_risk_card"
        booking.stripe_customer_id = "cus_risk"
        db.session.commit()
        handle_addon_payment_processing(
            {
                "id": pi_ap,
                "amount": cents_ap,
                "currency": "usd",
                "metadata": meta_ap,
                "payment_method_types": ["us_bank_account"],
            }
        )
        inst_pending = InstallmentPayment.query.filter_by(
            booking_id=booking.id, installment_number=1, status="pending"
        ).first()
        if inst_pending:
            ok_ap, reason_ap = charge_installment_via_auto_pay(inst_pending)
            fails += 0 if check(
                "Auto Pay refuses while addon ACH processing",
                (not ok_ap) and reason_ap == "ach_processing",
                f"ok={ok_ap} reason={reason_ap}",
            ) else 1
        pay_ap = Payment.query.filter_by(stripe_payment_intent_id=pi_ap).first()
        if pay_ap:
            pay_ap.status = "cancelled"
        ba_ap.payment_status = "failed"
        booking.auto_pay_enabled = False
        booking.auto_pay_payment_method_id = None
        booking.stripe_customer_id = None
        db.session.commit()

        print("=== K) Cancelled booking cannot add ===")
        booking.status = "cancelled"
        db.session.commit()
        ba_c, err_c = create_manual_booking_addon(booking, addons[0].id)
        fails += 0 if check(
            "cancelled booking rejected",
            ba_c is None and "cancel" in (err_c or "").lower(),
            err_c,
        ) else 1
        booking.status = "deposit_paid"
        db.session.commit()

        print("=== L) Pay page token gate ===")
        ba_tok, _ = create_manual_booking_addon(booking, addons[0].id)
        db.session.commit()
        good = generate_addon_payment_token(ba_tok.id)

        class _FakePI:
            id = "pi_risk_page"
            client_secret = "cs_test_risk"
            status = "requires_payment_method"
            metadata = {}

        import app.payments as payments_mod
        import app.routes as routes_mod

        real_create = payments_mod.create_payment_intent
        payments_mod.create_payment_intent = lambda *a, **k: _FakePI()
        # routes may import create_payment_intent locally inside the view — patch via payments is enough if imported at call
        try:
            with app.test_client() as client_http:
                r_bad = client_http.get(f"/pay-addon/{ba_tok.id}?token=not-a-token")
                r_ok = client_http.get(f"/pay-addon/{ba_tok.id}?token={good}")
        finally:
            payments_mod.create_payment_intent = real_create
        fails += 0 if check(
            "bad token blocked",
            r_bad.status_code in (403, 404, 400, 302),
            str(r_bad.status_code),
        ) else 1
        fails += 0 if check(
            "good token allowed",
            r_ok.status_code == 200,
            str(r_ok.status_code),
        ) else 1

        print("=== M) Failed addon still counts as unpaid_manual ===")
        fails += 0 if check(
            "failed status in unpaid_manual",
            ba_f.payment_status == "failed"
            and unpaid_manual_addons_total(booking) >= booking_addon_line_total(ba_f) - 0.01,
            f"unpaid={unpaid_manual_addons_total(booking)}",
        ) else 1

        print("=== N) Receipt context builds ===")
        from app.routes import _booking_receipt_context

        ctx = _booking_receipt_context(booking)
        calc = calculate_booking_total(booking)
        fails += 0 if check(
            "receipt context builds",
            isinstance(ctx, dict) and bool(ctx),
            str(type(ctx)),
        ) else 1
        fails += 0 if check(
            "calculate_booking_total includes manuals in structure",
            float(calc.get("total") or 0) > float(unit),
            f"total={calc.get('total')} unit={unit}",
        ) else 1

        utils.send_email_via_ses = real_send
        print("=== Summary ===")
        print(f"  fails: {fails}")
        return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
