"""Ledger clamp / catch-up installment / receipt context helpers."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.payments import (
    clamp_refunded_amount,
    payment_base_amount,
    payment_refundable_remaining,
    reconcile_booking_ledger,
)


def test_clamp_refunded_amount():
    assert clamp_refunded_amount(4500, 785) == 785.0
    assert clamp_refunded_amount(-10, 785) == 0.0
    assert clamp_refunded_amount(45, 785) == 45.0


def test_payment_refundable_remaining_clamps_dirty_refunded():
    payment = SimpleNamespace(
        base_amount_cents=78500,
        fee_cents=2277,
        final_amount_cents=80777,
        amount=807.77,
        refunded_amount=4500.0,
    )
    assert payment_base_amount(payment) == 785.0
    assert payment_refundable_remaining(payment) == 0.0


def test_reconcile_flags_out_of_range_refund(app):
    payment = SimpleNamespace(
        id=1,
        base_amount_cents=78500,
        fee_cents=0,
        final_amount_cents=78500,
        amount=785.0,
        refunded_amount=4500.0,
        status="refunded",
        payment_metadata={},
        paid_at=datetime.utcnow(),
        created_at=datetime.utcnow(),
    )
    booking = SimpleNamespace(
        id=1,
        order_number="TEST-001",
        amount_paid=1785.0,
    )

    # Patch ledger_payments_for_booking via monkeypatch on module
    import app.payments as payments_mod

    original = payments_mod.ledger_payments_for_booking
    payments_mod.ledger_payments_for_booking = lambda b: [payment]
    try:
        result = reconcile_booking_ledger(booking)
        assert result["ok"] is False
        assert any(a["issue"] == "refunded_amount_out_of_range" for a in result["anomalies"])
        assert any(a["issue"] == "missing_refund_history" for a in result["anomalies"])
        # computed uses clamped refunded → net 0 for that payment
        assert result["computed_amount_paid"] == 0.0
    finally:
        payments_mod.ledger_payments_for_booking = original


def test_create_installment_payments_catch_up(app):
    """due_date < booking date → paid catch-up row, not skipped."""
    from app import db
    from app.models import Booking, BookingPackage, InstallmentPayment, Trip, TripPackage
    from app.routes import create_installment_payments

    with app.app_context():
        # Use in-memory-ish: require DB. Skip if no trips table usable.
        trip = Trip.query.first()
        if not trip:
            return

        package = TripPackage.query.filter(TripPackage.trip_id == trip.id).first()
        if not package:
            return

        book_day = date.today()
        past = (book_day - timedelta(days=20)).isoformat()
        future = (book_day + timedelta(days=30)).isoformat()
        config = {
            "enabled": True,
            "deposit_amount": 100.0,
            "installments": [
                {"date": past, "amount": 50.0},
                {"date": future, "amount": 50.0},
            ],
        }

        booking = Booking(
            trip_id=trip.id,
            status="deposit_paid",
            amount_paid=150.0,
            passenger_count=1,
            created_at=datetime.combine(book_day, datetime.min.time()),
        )
        db.session.add(booking)
        db.session.flush()

        bp = BookingPackage(
            booking_id=booking.id,
            package_id=package.id,
            quantity=1,
            payment_plan_type="deposit_installment",
        )
        db.session.add(bp)
        db.session.flush()

        create_installment_payments(booking, bp, config)
        db.session.flush()

        rows = (
            InstallmentPayment.query.filter_by(booking_id=booking.id)
            .order_by(InstallmentPayment.installment_number)
            .all()
        )
        # deposit #0 + catch-up #1 paid + future #2 pending
        assert len(rows) >= 3
        catch_up = [r for r in rows if r.installment_number == 1][0]
        assert catch_up.status == "paid"
        assert catch_up.due_date.isoformat() == past
        future_row = [r for r in rows if r.installment_number == 2][0]
        assert future_row.status == "pending"

        # cleanup
        for r in rows:
            db.session.delete(r)
        db.session.delete(bp)
        db.session.delete(booking)
        db.session.commit()


def test_booking_payment_display_status_priority():
    from types import SimpleNamespace
    from unittest.mock import patch

    import app.payments as payments_mod

    booking = SimpleNamespace(id=9, status="deposit_paid")

    with patch.object(payments_mod, "booking_has_refund", return_value=False), patch.object(
        payments_mod, "booking_has_overdue_amount", return_value=True
    ):
        assert payments_mod.booking_payment_display_status(booking) == "overdue"

    with patch.object(payments_mod, "booking_has_refund", return_value=True), patch.object(
        payments_mod, "booking_has_overdue_amount", return_value=True
    ):
        assert payments_mod.booking_payment_display_status(booking) == "refunded"

    assert payments_mod.booking_payment_display_status(
        SimpleNamespace(id=10, status="cancelled")
    ) == "cancelled"

    with patch.object(payments_mod, "booking_has_refund", return_value=False), patch.object(
        payments_mod, "booking_has_overdue_amount", return_value=False
    ):
        assert payments_mod.booking_payment_display_status(booking) == "deposit_paid"
