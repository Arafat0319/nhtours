"""套餐名额占位与并发超售防护。"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

import pytest

from app import db
from app.models import Booking, BookingPackage, Client, PendingBooking, Trip, TripPackage
from app.package_capacity import (
    package_spots_available,
    validate_packages_capacity,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _seed_pkg(capacity=2, price=100.0):
    trip = Trip(
        title=_uniq("cap-trip"),
        slug=_uniq("cap-trip"),
        status="published",
        is_published=True,
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 10),
        trip_abbr="CT",
    )
    db.session.add(trip)
    db.session.flush()
    pkg = TripPackage(
        trip_id=trip.id,
        name="CapPkg",
        price=price,
        capacity=capacity,
        status="available",
    )
    db.session.add(pkg)
    db.session.flush()
    return trip, pkg


def _pending_row(trip, pkg, qty=1):
    pi = f"pending_{uuid.uuid4().hex}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(hours=24),
        booking_data={
            "packages": [{"package_id": pkg.id, "quantity": qty, "payment_plan_type": "full"}],
        },
    )
    db.session.add(pb)
    db.session.commit()
    return pb


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_pending_reservation_reduces_availability(app_ctx):
    trip, pkg = _seed_pkg(capacity=1)
    try:
        assert package_spots_available(pkg.id) == 1
        _pending_row(trip, pkg, qty=1)
        assert package_spots_available(pkg.id) == 0
        err = validate_packages_capacity(
            [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}],
            lock=False,
        )
        assert err is not None
        assert "sold out" in err.lower()
    finally:
        for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_locked_validate_blocks_second_reservation(app_ctx):
    trip, pkg = _seed_pkg(capacity=1)
    packages_data = [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}]
    try:
        assert validate_packages_capacity(packages_data, lock=True) is None
        pb = PendingBooking(
            trip_id=trip.id,
            payment_intent_id=f"pending_{uuid.uuid4().hex}",
            status="pending",
            expires_at=datetime.utcnow() + timedelta(hours=24),
            booking_data={"packages": packages_data},
        )
        db.session.add(pb)
        db.session.commit()

        err = validate_packages_capacity(packages_data, lock=True)
        assert err is not None
    finally:
        for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_processing_booking_counts_as_occupied(app_ctx):
    trip, pkg = _seed_pkg(capacity=1)
    email = f"{_uniq('p')}@example.com"
    client = Client(email=email, first_name="P", last_name="Roc")
    db.session.add(client)
    db.session.flush()
    booking = Booking(
        trip_id=trip.id,
        client_id=client.id,
        buyer_email=email,
        status="processing",
        amount_paid=0,
        passenger_count=1,
    )
    db.session.add(booking)
    db.session.flush()
    db.session.add(
        BookingPackage(
            booking_id=booking.id,
            package_id=pkg.id,
            quantity=1,
            payment_plan_type="full",
            status="processing",
            amount_paid=0,
            unit_price=100,
        )
    )
    db.session.commit()
    try:
        assert package_spots_available(pkg.id) == 0
    finally:
        for bp in BookingPackage.query.filter_by(package_id=pkg.id).all():
            db.session.delete(bp)
        db.session.delete(booking)
        db.session.delete(client)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()
