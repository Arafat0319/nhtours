"""Messages「past due」只含 Bookings 列表上的 Overdue，不含尚未到期的尾款。"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from app import db
from app.messaging import get_recipients_for_trip
from app.models import Booking, BookingPackage, Client, InstallmentPayment, Trip, TripPackage
from app.utils import pacific_today


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_payment_due_recipients_match_overdue_badge(app_ctx):
    today = pacific_today()
    trip = Trip(
        title=_uniq("msg-due"),
        slug=_uniq("msg-due"),
        status="published",
        is_published=True,
        start_date=date(2027, 12, 26),
        end_date=date(2028, 1, 6),
        trip_abbr="MD",
    )
    db.session.add(trip)
    db.session.flush()
    pkg = TripPackage(trip_id=trip.id, name="Pkg", price=1000, status="available")
    db.session.add(pkg)
    db.session.flush()
    email_overdue = f"{_uniq('o')}@example.com"
    email_future = f"{_uniq('f')}@example.com"
    client = Client(email=email_overdue, first_name="O", last_name="Due")
    db.session.add(client)
    db.session.flush()

    def _booking(email, due):
        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            buyer_email=email,
            buyer_first_name="A",
            buyer_last_name="B",
            status="deposit_paid",
            amount_paid=100,
            passenger_count=1,
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(
            BookingPackage(
                booking_id=booking.id,
                package_id=pkg.id,
                quantity=1,
                payment_plan_type="deposit_installment",
                status="deposit_paid",
                amount_paid=100,
                unit_price=1000,
            )
        )
        db.session.add(
            InstallmentPayment(
                booking_id=booking.id,
                installment_number=1,
                amount=900,
                due_date=due,
                status="pending",
            )
        )
        return booking

    overdue = _booking(email_overdue, today - timedelta(days=3))
    future = _booking(email_future, today + timedelta(days=30))
    db.session.commit()
    try:
        recipients = get_recipients_for_trip(trip, {"type": "payment_due"})
        emails = {r["email"] for r in recipients}
        assert emails == {email_overdue}
        assert future.buyer_email not in emails
        assert overdue.buyer_email in emails
    finally:
        InstallmentPayment.query.filter(
            InstallmentPayment.booking_id.in_([overdue.id, future.id])
        ).delete(synchronize_session=False)
        BookingPackage.query.filter(
            BookingPackage.booking_id.in_([overdue.id, future.id])
        ).delete(synchronize_session=False)
        Booking.query.filter(Booking.id.in_([overdue.id, future.id])).delete(synchronize_session=False)
        db.session.delete(client)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()
