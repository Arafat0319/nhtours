#!/usr/bin/env python3
"""
Full local QA for Manage post-add add-ons:
  1) Clear booking-related test tables
  2) Seed clean fixture (deposit + installments + 2 passengers)
  3) Logic / conflict checks
  4) Simulate addon payment succeed (+ optional processing path)
  5) Build receipt PDF(s)
  6) Email samples to reviewer inboxes

Usage:
  python scripts/_qa_manual_addon_round.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

OUT_DIR = ROOT / "test-results" / "manual_addon_qa"
REVIEW_TO = [
    "arafathayrat@gmail.com",
    "info@nhtours.com",
]


def clear_booking_tables(db):
    from sqlalchemy import text

    tables = [
        "pending_bookings",
        "payments",
        "installment_payments",
        "booking_addons",
        "booking_packages",
        "booking_participants",
        "bookings",
    ]
    dialect = db.session.get_bind().dialect.name
    if dialect == "mysql":
        db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
        for t in tables:
            db.session.execute(text(f"TRUNCATE TABLE `{t}`"))
            print(f"  truncated {t}")
        db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
    else:
        for t in tables:
            db.session.execute(text(f"DELETE FROM {t}"))
            print(f"  deleted {t}")
    db.session.commit()


def seed_fixture(db):
    from app.models import (
        Booking,
        BookingPackage,
        BookingParticipant,
        Client,
        InstallmentPayment,
        Trip,
        TripAddOn,
        TripPackage,
    )

    trip = Trip.query.get(1) or Trip.query.first()
    if not trip:
        raise RuntimeError("No trip in DB — cannot seed")
    pkg = (
        TripPackage.query.filter_by(trip_id=trip.id)
        .order_by(TripPackage.id.asc())
        .first()
    )
    if not pkg:
        raise RuntimeError(f"No package on trip {trip.id}")
    addons = TripAddOn.query.filter_by(trip_id=trip.id).order_by(TripAddOn.id).all()
    if len(addons) < 1:
        raise RuntimeError(f"No add-ons on trip {trip.id}")

    client = Client.query.filter_by(email="arafathayrat@gmail.com").first()
    if not client:
        client = Client(
            name="Arafat QA",
            email="arafathayrat@gmail.com",
            phone="555-0100",
        )
        db.session.add(client)
        db.session.flush()

    booking = Booking(
        trip_id=trip.id,
        client_id=client.id,
        order_number="2608QA-ADDON",
        status="deposit_paid",
        amount_paid=200.0,
        buyer_first_name="Arafat",
        buyer_last_name="QA",
        buyer_email="arafathayrat@gmail.com",
        buyer_phone="555-0100",
        created_at=datetime.utcnow(),
    )
    db.session.add(booking)
    db.session.flush()

    unit = float(pkg.price or 1000)
    bp = BookingPackage(
        booking_id=booking.id,
        package_id=pkg.id,
        quantity=1,
        payment_plan_type="deposit_installment",
        amount_paid=200.0,
        status="deposit_paid",
        unit_price=unit,
    )
    db.session.add(bp)

    p1 = BookingParticipant(
        booking_id=booking.id,
        name="Arafat First",
        first_name="Arafat",
        last_name="First",
        email="arafathayrat@gmail.com",
        status="active",
    )
    p2 = BookingParticipant(
        booking_id=booking.id,
        name="Traveler Second",
        first_name="Traveler",
        last_name="Second",
        email="second@example.com",
        status="active",
    )
    db.session.add_all([p1, p2])
    db.session.flush()

    today = date.today()
    # #0 deposit already paid conceptually via amount_paid; schedule remaining
    rows = [
        InstallmentPayment(
            booking_id=booking.id,
            installment_number=0,
            amount=200.0,
            due_date=today - timedelta(days=30),
            status="paid",
            paid_at=datetime.utcnow() - timedelta(days=30),
        ),
        InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=400.0,
            due_date=today + timedelta(days=14),
            status="pending",
        ),
        InstallmentPayment(
            booking_id=booking.id,
            installment_number=2,
            amount=max(0.0, unit - 600.0),
            due_date=today + timedelta(days=45),
            status="pending",
        ),
    ]
    db.session.add_all(rows)
    db.session.commit()
    print(
        f"  seeded booking #{booking.id} {booking.order_number} "
        f"trip={trip.id} pkg={pkg.id} unit={unit} addons={[a.id for a in addons]}"
    )
    return booking, addons, p1, p2


def check(label, cond, details=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {label}" + (f" — {details}" if details else ""))
    return bool(cond)


def main():
    from flask import render_template

    from app import create_app, db
    from app.addon_admin import (
        addon_payment_url,
        booking_addon_line_total,
        create_manual_booking_addon,
        send_addon_payment_email,
        serialize_booking_addon,
    )
    from app.addon_payment import (
        handle_addon_payment_failed,
        handle_addon_payment_processing,
        handle_addon_payment_succeeded,
        is_addon_purchase_intent,
    )
    from app.models import Booking, BookingAddOn, Payment
    from app.payments import (
        booking_payoff_due,
        calculate_booking_total,
        payment_step_label,
        unpaid_manual_addons_total,
    )
    from app.utils import send_email_via_ses, _email_brand_logo_url
    import app.utils as utils

    app = create_app("development")
    results = []
    fails = 0

    with app.app_context():
        print("=== 1) Clear booking test data ===")
        clear_booking_tables(db)

        print("=== 2) Seed fixture ===")
        booking, addons, p1, p2 = seed_fixture(db)
        addon_a = addons[0]
        addon_b = addons[1] if len(addons) > 1 else addons[0]

        print("=== 3) Logic / conflict checks ===")
        before_due = booking_payoff_due(booking)
        before_total = calculate_booking_total(booking)["total"]

        # Default participant = first
        ba1, err = create_manual_booking_addon(booking, addon_a.id, quantity=1)
        ok = check("create manual addon", err is None and ba1 is not None, err)
        fails += 0 if ok else 1
        db.session.commit()
        ok = check(
            "defaults to first participant",
            ba1.participant_id == p1.id,
            f"got {ba1.participant_id} want {p1.id}",
        )
        fails += 0 if ok else 1
        ok = check("source/status", ba1.source == "admin_manual" and ba1.payment_status == "unpaid")
        fails += 0 if ok else 1

        line = booking_addon_line_total(ba1)
        unpaid = unpaid_manual_addons_total(booking)
        after_total = calculate_booking_total(booking)["total"]
        after_payoff = booking_payoff_due(booking)
        ok = check(
            "expected total includes unpaid manual",
            abs(after_total - (before_total + line)) < 0.02,
            f"{before_total}+{line} vs {after_total}",
        )
        fails += 0 if ok else 1
        ok = check(
            "unpaid_manual_addons_total",
            abs(unpaid - line) < 0.02,
            f"{unpaid} vs {line}",
        )
        fails += 0 if ok else 1
        ok = check(
            "payoff excludes unpaid manual",
            abs(after_payoff - before_due) < 0.02,
            f"payoff {after_payoff} vs before {before_due}",
        )
        fails += 0 if ok else 1

        # Second addon on explicit passenger 2
        ba2, err2 = create_manual_booking_addon(
            booking, addon_b.id, quantity=1, participant_id=p2.id
        )
        db.session.commit()
        ok = check("explicit second passenger", err2 is None and ba2.participant_id == p2.id, err2)
        fails += 0 if ok else 1

        # Cancelled booking blocked
        booking.status = "cancelled"
        db.session.flush()
        ba_bad, err_bad = create_manual_booking_addon(booking, addon_a.id)
        ok = check("cancelled booking rejected", ba_bad is None and bool(err_bad), err_bad)
        fails += 0 if ok else 1
        booking.status = "deposit_paid"
        db.session.commit()

        # Metadata routing
        ok = check(
            "is_addon_purchase_intent",
            is_addon_purchase_intent({"payment_type": "addon_purchase"})
            and not is_addon_purchase_intent({"payment_step": "installment"}),
        )
        fails += 0 if ok else 1

        # payment_step_label
        fake_pay = SimpleNamespace(
            payment_metadata={
                "payment_step": "addon",
                "payment_type": "addon_purchase",
                "addon_name": addon_a.name,
            },
            installment_payment=None,
            installment_payment_id=None,
            booking_id=booking.id,
        )
        label = payment_step_label(fake_pay)
        ok = check("payment_step_label addon", "Add-on" in (label or ""), label)
        fails += 0 if ok else 1

        print("=== 4) Simulate ACH processing then succeed for ba1 ===")
        base_cents = int(round(line * 100))
        pi_id = "pi_qa_addon_manual_001"
        meta = {
            "payment_type": "addon_purchase",
            "payment_step": "addon",
            "payment_flow": "addon",
            "booking_id": str(booking.id),
            "booking_addon_id": str(ba1.id),
            "addon_name": addon_a.name,
            "base_amount": str(base_cents),
            "fee": "0",
            "final_amount": str(base_cents),
            "payment_method_type": "us_bank_account",
            "funding": "ach",
        }
        ba1.stripe_payment_intent_id = pi_id
        db.session.commit()

        paid_before = float(booking.amount_paid or 0)
        intent_proc = {
            "id": pi_id,
            "amount": base_cents,
            "currency": "usd",
            "metadata": meta,
            "payment_method_types": ["us_bank_account"],
        }
        handle_addon_payment_processing(intent_proc)
        db.session.refresh(ba1)
        pay_row = Payment.query.filter_by(stripe_payment_intent_id=pi_id).first()
        ok = check(
            "processing status",
            ba1.payment_status == "processing"
            and pay_row is not None
            and pay_row.status == "processing",
            f"ba={ba1.payment_status} pay={getattr(pay_row, 'status', None)}",
        )
        fails += 0 if ok else 1
        ok = check(
            "processing does not bump amount_paid",
            abs(float(booking.amount_paid or 0) - paid_before) < 0.01,
        )
        fails += 0 if ok else 1

        # Fail then re-process? skip — go succeed
        intent_ok = dict(intent_proc)
        intent_ok["metadata"] = dict(meta)
        handle_addon_payment_succeeded(intent_ok)
        db.session.refresh(ba1)
        db.session.refresh(booking)
        pay_row = Payment.query.filter_by(stripe_payment_intent_id=pi_id).first()
        ok = check(
            "succeeded marks paid",
            ba1.payment_status == "paid" and pay_row.status == "succeeded",
            f"ba={ba1.payment_status} pay={pay_row.status if pay_row else None}",
        )
        fails += 0 if ok else 1
        ok = check(
            "amount_paid increased by base",
            abs(float(booking.amount_paid or 0) - (paid_before + line)) < 0.02,
            f"{booking.amount_paid} vs {paid_before}+{line}",
        )
        fails += 0 if ok else 1

        # Idempotent second succeed
        paid_mid = float(booking.amount_paid or 0)
        handle_addon_payment_succeeded(intent_ok)
        db.session.refresh(booking)
        ok = check(
            "idempotent succeed (no double credit)",
            abs(float(booking.amount_paid or 0) - paid_mid) < 0.01,
            f"{booking.amount_paid}",
        )
        fails += 0 if ok else 1

        # Failed path on ba2
        pi2 = "pi_qa_addon_manual_fail"
        ba2.stripe_payment_intent_id = pi2
        db.session.commit()
        intent_fail = {
            "id": pi2,
            "amount": int(round(booking_addon_line_total(ba2) * 100)),
            "currency": "usd",
            "metadata": {
                "payment_type": "addon_purchase",
                "payment_step": "addon",
                "booking_id": str(booking.id),
                "booking_addon_id": str(ba2.id),
            },
            "last_payment_error": {"message": "QA simulated decline"},
        }
        handle_addon_payment_failed(intent_fail)
        db.session.refresh(ba2)
        ok = check("failed marks failed", ba2.payment_status == "failed", ba2.payment_status)
        fails += 0 if ok else 1
        # booking must not be cancelled
        ok = check("addon fail does not cancel booking", booking.status != "cancelled", booking.status)
        fails += 0 if ok else 1

        print("=== 5) Receipt context / PDF ===")
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        from app.routes import _booking_receipt_context
        from app.receipt_pdf import build_booking_receipt_pdf

        ctx = _booking_receipt_context(booking, payment_id=ba1.payment_id)
        participant_addon_names = []
        for pinfo in (ctx.get("participants_info") or []):
            for a in (pinfo.get("addons") or []):
                participant_addon_names.append(a.get("name"))
        ok = check(
            "receipt participants include paid manual addon",
            any(addon_a.name in (n or "") for n in participant_addon_names),
            str(participant_addon_names),
        )
        fails += 0 if ok else 1
        ok = check(
            "receipt addons_total > 0",
            float(ctx.get("addons_total") or 0) > 0,
            str(ctx.get("addons_total")),
        )
        fails += 0 if ok else 1
        # Order structure Expected includes unpaid/failed manuals too
        ok = check(
            "receipt expected includes all manual lines",
            float(ctx.get("expected_amount") or 0) >= float(calculate_booking_total(booking)["total"]) - 0.02,
            f"expected={ctx.get('expected_amount')} calc={calculate_booking_total(booking)['total']}",
        )
        fails += 0 if ok else 1

        pdf_bytes = build_booking_receipt_pdf(ctx)
        pdf_path = OUT_DIR / f"receipt_{booking.order_number}_addon_paid.pdf"
        pdf_path.write_bytes(pdf_bytes)
        print(f"  wrote {pdf_path} ({len(pdf_bytes)} bytes)")

        with app.test_request_context("/"):
            html = render_template("booking/receipt.html", **ctx)
        html_path = OUT_DIR / f"receipt_{booking.order_number}_addon_paid.html"
        html_path.write_text(html, encoding="utf-8")
        print(f"  wrote {html_path}")

        print("=== 6) Email samples ===")
        email_log = []

        def wrap_ses(fn):
            def wrapped(sender, recipient, subject, html_body, text_body, **kwargs):
                subject = f"[SAMPLE][Add-on QA] {subject}"
                ok_s, detail = fn(sender, recipient, subject, html_body, text_body, **kwargs)
                email_log.append((subject, ok_s, detail, recipient))
                print(f"  {'OK' if ok_s else 'FAIL'}: {subject} -> {recipient} ({detail})")
                return ok_s, detail

            return wrapped

        utils.send_email_via_ses = wrap_ses(utils.send_email_via_ses)
        sender = (
            app.config.get("SENDER_EMAIL")
            or app.config.get("RECIPIENT_EMAIL")
            or "noreply@nhtours.com"
        )
        logo = _email_brand_logo_url()
        addon_a_name = addon_a.name
        order_label = booking.order_number
        trip_title = booking.trip.title if booking.trip else "Trip"

        ba_invite, _ = create_manual_booking_addon(booking, addon_a.id, quantity=1)
        db.session.commit()
        pay_url = addon_payment_url(ba_invite)

        proc_pay = Payment.query.filter_by(
            stripe_payment_intent_id="pi_qa_email_proc_only"
        ).first()
        if not proc_pay:
            proc_pay = Payment(
                booking_id=booking.id,
                client_id=booking.client_id,
                trip_id=booking.trip_id,
                amount=line,
                stripe_payment_intent_id="pi_qa_email_proc_only",
                status="processing",
                currency="USD",
                payment_metadata={
                    "payment_type": "addon_purchase",
                    "payment_step": "addon",
                    "addon_name": addon_a_name,
                    "base_amount": str(base_cents),
                },
                base_amount_cents=base_cents,
            )
            db.session.add(proc_pay)
            db.session.commit()

        paid_pay = Payment.query.get(ba1.payment_id) if ba1.payment_id else None

        for to in REVIEW_TO:
            try:
                booking.buyer_email = to
                db.session.commit()

                ok_e, msg = send_addon_payment_email(ba_invite)
                results.append(("invite", to, ok_e, msg))

                try:
                    from app.routes import send_order_processing_email
                    send_order_processing_email(booking, proc_pay, is_new_order=False)
                except Exception as e:
                    db.session.rollback()
                    print(f"  WARN processing email -> {to}: {e}")

                try:
                    from app.routes import send_booking_confirmation_email
                    if paid_pay:
                        paid_pay.receipt_email_sent_at = None
                        db.session.commit()
                        send_booking_confirmation_email(booking, False, payment=paid_pay)
                except Exception as e:
                    db.session.rollback()
                    print(f"  WARN receipt email -> {to}: {e}")

                ctx_invite = {
                    "subject_line": f"Pay for add-on — {addon_a_name} ({order_label})",
                    "brand_subtitle": "Add-on payment",
                    "customer_name": "Arafat",
                    "intro_text": (
                        f"An add-on was added to your booking for {trip_title} "
                        f"(order {order_label}). Please complete payment."
                    ),
                    "highlight_title": "Amount due",
                    "trip_title": trip_title,
                    "addon_label": f"{addon_a_name} × 1",
                    "amount": float(addon_a.price or 0),
                    "order_number": order_label,
                    "payment_link": pay_url,
                    "email_logo_url": logo,
                    "cta_label": "Pay now",
                    "footer_note": "If you have already paid, please ignore this email.",
                }
                html_i = render_template("emails/addon_payment_invite.html", **ctx_invite)
                txt_i = render_template("emails/addon_payment_invite.txt", **ctx_invite)
                send_email_via_ses(
                    sender,
                    to,
                    f"Pay for add-on — {addon_a_name} (direct preview)",
                    html_i,
                    txt_i,
                )
                send_email_via_ses(
                    sender,
                    to,
                    f"Receipt PDF — {order_label} (manual add-on paid)",
                    (
                        "<p>Manual add-on QA — receipt PDF attached.</p>"
                        f"<p>Order <strong>{order_label}</strong>: package + paid "
                        f"manual add-on (<em>{addon_a_name}</em>) + installment History.</p>"
                    ),
                    f"Receipt PDF attached for {order_label}",
                    attachments=[
                        {
                            "filename": f"NHTours-Receipt-{order_label}.pdf",
                            "content": pdf_bytes,
                            "mime_subtype": "pdf",
                        }
                    ],
                )
            except Exception as e:
                db.session.rollback()
                print(f"  FAIL email batch -> {to}: {e}")

        booking.buyer_email = "arafathayrat@gmail.com"
        # Sample processing row must not leave ACH lock on the fixture
        if proc_pay and proc_pay.status == "processing":
            proc_pay.status = "failed"
        db.session.commit()

        print("=== Summary ===")
        print(f"  logic fails: {fails}")
        print(f"  emails logged: {len(email_log)}")
        print(f"  booking id={booking.id} order={booking.order_number}")
        print(f"  pay link sample: {pay_url}")
        print(f"  Manage: /admin/trips/{booking.trip_id}/manage → open {booking.order_number}")
        return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
