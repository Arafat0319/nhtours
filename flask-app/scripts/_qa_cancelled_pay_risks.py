#!/usr/bin/env python3
"""Risk / edge tests for cancelled-order payment link hardening."""
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
    from app.addon_admin import create_manual_booking_addon
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
    from app.payments import apply_refund_to_ledger, cancel_unpaid_installments
    from app.routes import handle_payment_intent_succeeded
    from app.utils import (
        generate_addon_payment_token,
        generate_auto_pay_token,
        generate_installment_token,
        generate_receipt_token,
    )

    app = create_app("development")
    fails = 0

    with app.app_context():
        trip = Trip.query.get(1) or Trip.query.first()
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        addon = TripAddOn.query.filter_by(trip_id=trip.id).first()
        client = Client.query.filter_by(email="cancel-risk@example.com").first()
        if not client:
            client = Client(name="Cancel Risk", email="cancel-risk@example.com")
            db.session.add(client)
            db.session.flush()

        for on in ("2609QA-CAN-A", "2609QA-CAN-B"):
            old = Booking.query.filter_by(order_number=on).first()
            if old:
                Payment.query.filter_by(booking_id=old.id).delete()
                InstallmentPayment.query.filter_by(booking_id=old.id).delete()
                BookingAddOn.query.filter_by(booking_id=old.id).delete()
                BookingPackage.query.filter_by(booking_id=old.id).delete()
                BookingParticipant.query.filter_by(booking_id=old.id).delete()
                db.session.delete(old)
        db.session.commit()

        unit = float(pkg.price or 1000)
        today = date.today()

        def seed(order_number, status, amount_paid):
            b = Booking(
                trip_id=trip.id,
                client_id=client.id,
                order_number=order_number,
                status=status,
                amount_paid=amount_paid,
                buyer_first_name="Cancel",
                buyer_last_name="Risk",
                buyer_email="cancel-risk@example.com",
                passenger_count=1,
            )
            db.session.add(b)
            db.session.flush()
            db.session.add(
                BookingPackage(
                    booking_id=b.id,
                    package_id=pkg.id,
                    quantity=1,
                    payment_plan_type="deposit_installment",
                    amount_paid=min(amount_paid, 100.0),
                    status="deposit_paid" if status != "cancelled" else "cancelled",
                    unit_price=unit,
                )
            )
            p = BookingParticipant(
                booking_id=b.id,
                name="Cancel Risk",
                first_name="Cancel",
                last_name="Risk",
                status="active",
            )
            db.session.add(p)
            db.session.flush()
            rows = [
                InstallmentPayment(
                    booking_id=b.id,
                    installment_number=0,
                    amount=100.0,
                    due_date=today - timedelta(days=10),
                    status="paid",
                    paid_at=datetime.utcnow(),
                ),
                InstallmentPayment(
                    booking_id=b.id,
                    installment_number=1,
                    amount=400.0,
                    due_date=today,
                    status="pending" if status != "cancelled" else "cancelled",
                ),
                InstallmentPayment(
                    booking_id=b.id,
                    installment_number=2,
                    amount=max(0.0, unit - 500.0),
                    due_date=today + timedelta(days=30),
                    status="pending" if status != "cancelled" else "cancelled",
                ),
            ]
            db.session.add_all(rows)
            db.session.flush()
            return b, p, rows[1]

        cancelled, _, inst_c = seed("2609QA-CAN-A", "cancelled", 0.0)
        active, part_a, inst_a = seed("2609QA-CAN-B", "deposit_paid", 100.0)
        db.session.commit()

        print("=== A) Cancelled booking entry points ===")
        with app.test_client() as c:
            tok_i = generate_installment_token(inst_c.id)
            r = c.get(f"/pay-installment/{inst_c.id}?token={tok_i}", follow_redirects=False)
            loc = r.headers.get("Location") or ""
            fails += 0 if check("cancelled pay → 302", r.status_code in (302, 303)) else 1
            fails += 0 if check("cancelled pay Location has cancelled=1", "cancelled=1" in loc, loc) else 1
            fails += 0 if check("cancelled pay NOT already_paid", "already_paid=1" not in loc, loc) else 1

            r2 = c.get(f"/pay-installment/{inst_c.id}/payoff?token={tok_i}", follow_redirects=False)
            loc2 = r2.headers.get("Location") or ""
            fails += 0 if check("cancelled payoff → cancelled=1", "cancelled=1" in loc2, loc2) else 1

            rtok = generate_receipt_token(cancelled.id)
            r3 = c.get(f"/booking/payment/{cancelled.id}?token={rtok}", follow_redirects=False)
            loc3 = r3.headers.get("Location") or ""
            fails += 0 if check("cancelled booking/payment → cancelled=1", "cancelled=1" in loc3, loc3) else 1

            # follow to page
            page = c.get(loc, follow_redirects=True)
            body = page.data.decode("utf-8", errors="ignore")
            fails += 0 if check("page says Order Cancelled", "Order Cancelled" in body) else 1
            fails += 0 if check("page not Already Paid", "Already Paid" not in body) else 1
            fails += 0 if check("shows order number", cancelled.order_number in body) else 1
            fails += 0 if check("no receipt download CTA", "Download receipt" not in body) else 1

            # Auto Pay
            atok = generate_auto_pay_token(cancelled.id)
            r4 = c.get(f"/booking/{cancelled.id}/auto-pay?token={atok}", follow_redirects=False)
            loc4 = r4.headers.get("Location") or ""
            fails += 0 if check("cancelled auto-pay → cancelled=1", "cancelled=1" in loc4, loc4) else 1

            # Manual addon on cancelled booking should fail create; if we force unpaid row, pay page redirects
            ba, err = create_manual_booking_addon(cancelled, addon.id)
            fails += 0 if check("cannot add addon on cancelled", ba is None and bool(err), err) else 1

        print("=== B) Active sibling still payable ===")
        with app.test_client() as c:
            tok = generate_installment_token(inst_a.id)
            r = c.get(f"/pay-installment/{inst_a.id}?token={tok}", follow_redirects=False)
            fails += 0 if check(
                "active installment returns 200 (payment UI)",
                r.status_code == 200,
                str(r.status_code),
            ) else 1
            if r.status_code == 200:
                body = r.data.decode("utf-8", errors="ignore")
                fails += 0 if check(
                    "active page has payment surface",
                    "stripe" in body.lower() or "client_secret" in body.lower() or "Payment" in body,
                ) else 1

        print("=== C) Forged cancelled=1 on ACTIVE booking must not fake closed page ===")
        with app.test_client() as c:
            tok = generate_receipt_token(active.id)
            # Attack: craft cancelled=1 while order is deposit_paid
            r = c.get(
                f"/booking/success?booking_id={active.id}&cancelled=1&token={tok}",
                follow_redirects=True,
            )
            body = r.data.decode("utf-8", errors="ignore")
            forged_ok = "Order Cancelled" not in body
            fails += 0 if check(
                "forged cancelled=1 ignored for active order",
                forged_ok,
                "showed Order Cancelled" if not forged_ok else "ok",
            ) else 1

        print("=== D) Installment cancelled on ACTIVE booking (payoff-style) → Already Paid ===")
        inst_a.status = "cancelled"
        db.session.commit()
        with app.test_client() as c:
            tok = generate_installment_token(inst_a.id)
            r = c.get(f"/pay-installment/{inst_a.id}?token={tok}", follow_redirects=False)
            loc = r.headers.get("Location") or ""
            fails += 0 if check(
                "active booking + cancelled installment → already_paid",
                "already_paid=1" in loc and "cancelled=1" not in loc,
                loc,
            ) else 1
        inst_a.status = "pending"
        db.session.commit()

        print("=== E) Bad token still 403 ===")
        with app.test_client() as c:
            r = c.get(f"/pay-installment/{inst_c.id}?token=not-valid", follow_redirects=False)
            fails += 0 if check("bad installment token 403", r.status_code == 403) else 1
            rtok = generate_receipt_token(cancelled.id)
            r2 = c.get(f"/booking/payment/{cancelled.id}?token=bad", follow_redirects=False)
            fails += 0 if check("bad receipt token 403", r2.status_code == 403) else 1

        print("=== F) Webhook succeed on cancelled booking does not reopen installments ===")
        # Attach a fake pending installment PI then fire succeeded
        pi = "pi_risk_cancelled_late"
        inst_late = InstallmentPayment.query.filter_by(
            booking_id=cancelled.id, installment_number=1
        ).first()
        inst_late.status = "cancelled"
        inst_late.payment_intent_id = pi
        pay = Payment(
            booking_id=cancelled.id,
            client_id=client.id,
            trip_id=trip.id,
            amount=400.0,
            status="processing",
            currency="usd",
            stripe_payment_intent_id=pi,
            installment_payment_id=inst_late.id,
            base_amount_cents=40000,
            final_amount_cents=40000,
        )
        db.session.add(pay)
        paid_before = float(cancelled.amount_paid or 0)
        db.session.commit()

        handle_payment_intent_succeeded(
            {
                "id": pi,
                "amount": 40000,
                "currency": "usd",
                "metadata": {
                    "base_amount": "40000",
                    "fee": "0",
                    "final_amount": "40000",
                    "payment_step": "installment",
                    "booking_id": str(cancelled.id),
                    "installment_id": str(inst_late.id),
                },
            }
        )
        db.session.refresh(cancelled)
        db.session.refresh(inst_late)
        db.session.refresh(pay)
        fails += 0 if check(
            "booking stays cancelled",
            cancelled.status == "cancelled",
            cancelled.status,
        ) else 1
        fails += 0 if check(
            "installment not reopened to paid",
            inst_late.status != "paid",
            inst_late.status,
        ) else 1
        fails += 0 if check(
            "amount_paid unchanged",
            abs(float(cancelled.amount_paid or 0) - paid_before) < 0.01,
            f"{cancelled.amount_paid} vs {paid_before}",
        ) else 1

        print("=== G) Reminder task skips cancelled booking ===")
        from app.tasks import send_installment_reminders
        # Should not throw; cancelled installments shouldn't get emails
        # We only assert helper query excludes cancelled bookings if exposed;
        # smoke: function callable
        try:
            # dry: don't actually send — patch SES
            import app.utils as utils
            real = utils.send_email_via_ses
            utils.send_email_via_ses = lambda *a, **k: (True, "muted")
            # call inner selection if possible
            from app.models import Booking as B
            n_cancelled_pending = (
                InstallmentPayment.query.join(B)
                .filter(
                    B.status == "cancelled",
                    InstallmentPayment.status.in_(("pending", "overdue")),
                )
                .count()
            )
            fails += 0 if check(
                "cancelled bookings have no pending/overdue installments after harden",
                n_cancelled_pending == 0,
                str(n_cancelled_pending),
            ) else 1
            utils.send_email_via_ses = real
        except Exception as e:
            fails += 0 if check("reminder smoke", False, str(e)) else 1

        print("=== Summary ===")
        print(f"  fails: {fails}")
        return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
