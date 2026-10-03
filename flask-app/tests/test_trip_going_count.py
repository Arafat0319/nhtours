"""行程列表人数与 Manage Going 同一口径。"""

from __future__ import annotations

import uuid
from datetime import date

import pytest

from app import db
from app.admin.routes import calculate_trip_stats, count_going_participants
from app.models import Booking, BookingParticipant, Client, Trip


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_list_going_skips_cancelled_and_withdrawn(app_ctx):
    trip = Trip(
        title=_uniq("going-trip"),
        slug=_uniq("going-trip"),
        status="published",
        is_published=True,
        start_date=date(2027, 12, 26),
        end_date=date(2028, 1, 6),
        trip_abbr="GT",
        capacity=40,
    )
    db.session.add(trip)
    db.session.flush()
    email = f"{_uniq('g')}@example.com"
    client = Client(email=email, first_name="G", last_name="O")
    db.session.add(client)
    db.session.flush()

    active = Booking(
        trip_id=trip.id,
        client_id=client.id,
        buyer_email=email,
        status="deposit_paid",
        amount_paid=100,
        passenger_count=2,
    )
    cancelled = Booking(
        trip_id=trip.id,
        client_id=client.id,
        buyer_email=email,
        status="cancelled",
        amount_paid=100,
        passenger_count=1,
    )
    db.session.add_all([active, cancelled])
    db.session.flush()
    db.session.add_all([
        BookingParticipant(booking_id=active.id, name="Still Going", status="active"),
        BookingParticipant(booking_id=active.id, name="Left", status="withdrawn"),
        BookingParticipant(booking_id=cancelled.id, name="Cancelled", status="active"),
    ])
    db.session.commit()
    try:
        assert count_going_participants(trip.id) == 1
        stats = calculate_trip_stats(trip)
        assert stats["going_count"] == 1
        assert stats["participants_count"] == 3
    finally:
        for p in BookingParticipant.query.join(Booking).filter(Booking.trip_id == trip.id).all():
            db.session.delete(p)
        for b in Booking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(b)
        db.session.delete(client)
        db.session.delete(trip)
        db.session.commit()
