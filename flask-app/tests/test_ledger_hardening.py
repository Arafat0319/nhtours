"""账本加固：Save Changes 不得改 Paid、退款重开分期、定金挂链、失败信守卫。"""
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

from app.payments import (
    booking_manual_status_edit_error,
    link_initial_payment_to_deposit_installment,
    reopen_installments_for_refunded_payment,
)


def test_manual_status_rejects_amount_paid_edit():
    booking = SimpleNamespace(id=1, status="deposit_paid", amount_paid=400.0)
    with patch("app.payments.computed_booking_amount_paid", return_value=400.0):
        err = booking_manual_status_edit_error(booking, "deposit_paid", 1.0)
    assert err and "ledger" in err.lower()


def test_manual_status_allows_display_echo_of_computed():
    booking = SimpleNamespace(id=1, status="deposit_paid", amount_paid=400.0)
    with patch("app.payments.computed_booking_amount_paid", return_value=399.0):
        err = booking_manual_status_edit_error(booking, "deposit_paid", 399.0)
    assert err is None


def test_manual_status_rejects_fully_paid_while_due():
    booking = SimpleNamespace(id=1, status="deposit_paid", amount_paid=400.0)
    with patch(
        "app.payments.calculate_booking_total",
        return_value={"amount_due": 399.0, "amount_paid": 400.0},
    ):
        err = booking_manual_status_edit_error(booking, "fully_paid")
    assert err and "Fully paid" in err


def test_manual_status_rejects_pending_with_payments():
    booking = SimpleNamespace(id=1, status="deposit_paid", amount_paid=400.0)
    with patch(
        "app.payments.calculate_booking_total",
        return_value={"amount_due": 0.0, "amount_paid": 400.0},
    ):
        err = booking_manual_status_edit_error(booking, "pending")
    assert err and "Pending" in err


def test_manual_status_rejects_manual_processing(app):
    booking = SimpleNamespace(id=9, status="deposit_paid", amount_paid=100.0)
    with app.app_context():
        with patch(
            "app.payments.calculate_booking_total",
            return_value={"amount_due": 50.0, "amount_paid": 100.0},
        ):
            with patch("app.payments.booking_has_processing_ach_payment", return_value=False):
                err = booking_manual_status_edit_error(booking, "processing")
    assert err and "Processing" in err


def test_link_initial_payment_sets_deposit_and_catch_up_ids(app):
    from app import db
    from app.models import Booking, InstallmentPayment, Payment

    with app.app_context():
        booking = Booking.query.filter(Booking.status != "cancelled").first()
        if not booking:
            return
        existing0 = InstallmentPayment.query.filter_by(
            booking_id=booking.id, installment_number=0
        ).first()
        created = []
        if not existing0:
            existing0 = InstallmentPayment(
                booking_id=booking.id,
                installment_number=0,
                amount=100.0,
                due_date=date.today(),
                status="paid",
                paid_at=datetime.utcnow(),
            )
            db.session.add(existing0)
            db.session.flush()
            created.append(existing0)
        pay = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=100.0,
            status="succeeded",
            currency="usd",
            stripe_payment_intent_id=f"pi_link_deposit_{id(booking)}",
            base_amount_cents=10000,
            final_amount_cents=10000,
            payment_metadata={"payment_step": "initial"},
        )
        db.session.add(pay)
        db.session.flush()
        try:
            assert link_initial_payment_to_deposit_installment(booking, pay) is True
            assert pay.installment_payment_id == existing0.id
            if created:
                assert existing0.payment_intent_id == pay.stripe_payment_intent_id
            meta = pay.payment_metadata or {}
            assert str(existing0.id) in str(meta.get("catch_up_ids") or "")
        finally:
            db.session.delete(pay)
            for row in created:
                db.session.delete(row)
            db.session.commit()


def test_full_refund_reopens_covered_installment(app):
    from app import db
    from app.models import Booking, InstallmentPayment, Payment
    from app.payments import apply_refund_to_ledger

    with app.app_context():
        booking = Booking.query.filter(Booking.status != "cancelled").first()
        if not booking:
            return
        before_paid = float(booking.amount_paid or 0)
        inst = InstallmentPayment(
            booking_id=booking.id,
            installment_number=97,
            amount=40.0,
            due_date=date.today(),
            status="paid",
            paid_at=datetime.utcnow(),
        )
        db.session.add(inst)
        db.session.flush()
        pay = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=40.0,
            status="succeeded",
            currency="usd",
            installment_payment_id=inst.id,
            base_amount_cents=4000,
            final_amount_cents=4000,
            payment_metadata={
                "payment_step": "installment",
                "installment_id": inst.id,
            },
        )
        db.session.add(pay)
        booking.amount_paid = before_paid + 40.0
        db.session.commit()
        try:
            apply_refund_to_ledger(pay, booking, 40.0, reason="unit reopen inst")
            db.session.commit()
            db.session.refresh(inst)
            assert inst.status in ("pending", "overdue")
            assert inst.paid_at is None
        finally:
            db.session.delete(pay)
            db.session.delete(inst)
            booking.amount_paid = before_paid
            db.session.commit()


def test_payoff_refund_reopens_cancelled_not_earlier_paid(app):
    from app import db
    from app.models import Booking, InstallmentPayment, Payment

    with app.app_context():
        booking = Booking.query.filter(Booking.status != "cancelled").first()
        if not booking:
            return
        paid_earlier = InstallmentPayment(
            booking_id=booking.id,
            installment_number=95,
            amount=10.0,
            due_date=date.today(),
            status="paid",
            paid_at=datetime.utcnow(),
        )
        cancelled = InstallmentPayment(
            booking_id=booking.id,
            installment_number=96,
            amount=20.0,
            due_date=date.today(),
            status="cancelled",
        )
        db.session.add_all([paid_earlier, cancelled])
        db.session.flush()
        pay = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=20.0,
            status="refunded",
            currency="usd",
            base_amount_cents=2000,
            final_amount_cents=2000,
            refunded_amount=20.0,
            payment_metadata={"payment_step": "payoff"},
        )
        db.session.add(pay)
        db.session.commit()
        try:
            n = reopen_installments_for_refunded_payment(pay)
            db.session.commit()
            db.session.refresh(paid_earlier)
            db.session.refresh(cancelled)
            assert n >= 1
            assert paid_earlier.status == "paid"
            assert cancelled.status in ("pending", "overdue")
        finally:
            db.session.delete(pay)
            db.session.delete(paid_earlier)
            db.session.delete(cancelled)
            db.session.commit()


def test_addon_refund_does_not_reopen_unrelated_installment(app):
    from app import db
    from app.models import Booking, InstallmentPayment, Payment
    from app.payments import apply_refund_to_ledger

    with app.app_context():
        booking = Booking.query.filter(Booking.status != "cancelled").first()
        if not booking:
            return
        before_paid = float(booking.amount_paid or 0)
        inst = InstallmentPayment(
            booking_id=booking.id,
            installment_number=94,
            amount=25.0,
            due_date=date.today(),
            status="paid",
            paid_at=datetime.utcnow(),
        )
        db.session.add(inst)
        db.session.flush()
        pay = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=25.0,
            status="succeeded",
            currency="usd",
            base_amount_cents=2500,
            final_amount_cents=2500,
            payment_metadata={"payment_type": "addon_purchase", "payment_step": "addon"},
        )
        db.session.add(pay)
        booking.amount_paid = before_paid + 25.0
        db.session.commit()
        try:
            apply_refund_to_ledger(pay, booking, 25.0, reason="unit addon refund")
            db.session.commit()
            db.session.refresh(inst)
            assert inst.status == "paid"
            assert inst.paid_at is not None
        finally:
            db.session.delete(pay)
            db.session.delete(inst)
            booking.amount_paid = before_paid
            db.session.commit()


def test_send_payment_failed_skips_paid_and_empty_group(app):
    from app.tasks import send_payment_failed_email

    paid = SimpleNamespace(
        id=112,
        booking_id=27,
        installment_number=1,
        amount=399.0,
        due_date=date(2026, 10, 6),
        status="paid",
        booking=SimpleNamespace(
            id=27,
            status="deposit_paid",
            order_number="2706ERJP-006",
            buyer_email="parent@example.com",
            buyer_first_name="Helen",
            auto_pay_enabled=False,
            trip=SimpleNamespace(title="2027 Japan Trip"),
        ),
    )
    with app.app_context():
        with patch("app.tasks.send_email_via_ses") as send:
            assert send_payment_failed_email(paid, failure_reason="card_declined") is False
            send.assert_not_called()

        overdue = SimpleNamespace(
            id=113,
            booking_id=27,
            installment_number=1,
            amount=399.0,
            due_date=date(2026, 10, 6),
            status="overdue",
            booking=paid.booking,
        )
        with patch("app.tasks.customer_installment_notice_block_reason", return_value=None):
            with patch("app.tasks._same_due_unpaid_group", return_value=[]):
                with patch("app.tasks.send_email_via_ses") as send:
                    assert send_payment_failed_email(overdue, failure_reason="card_declined") is False
                    send.assert_not_called()
