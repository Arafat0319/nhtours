"""
空壳 Pending / Payment 严格清理：abandon、短 TTL、sibling、微验证不误杀。
对照 context/12 §3.1 §3.7。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models import Booking, Client, Payment, PendingBooking, Trip, TripPackage
from app.package_capacity import package_spots_available
from app.payments import (
    EMPTY_PENDING_HOLD_MINUTES,
    abandon_pending_booking,
    cancel_sibling_empty_pending_bookings,
    payment_intent_is_empty_shell,
    void_empty_shell_pending_payments,
)
from app.tasks import cleanup_empty_shell_pending_payments, cleanup_expired_pending_bookings


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _trip_pkg(*, capacity=2):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("trip"),
        status="published",
        is_published=True,
        start_date=date(2027, 9, 1),
        end_date=date(2027, 9, 10),
        trip_abbr="AB",
    )
    db.session.add(trip)
    db.session.flush()
    pkg = TripPackage(
        trip_id=trip.id,
        name="Pkg",
        price=100.0,
        capacity=capacity,
        status="available",
    )
    db.session.add(pkg)
    db.session.commit()
    return trip, pkg


def _booking_payload(trip, pkg, email):
    return {
        "packages": [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}],
        "participants": [{"first_name": "A", "last_name": "B", "dob": "2012-01-01"}],
        "buyer_info": {
            "first_name": "Parent",
            "last_name": "Test",
            "email": email,
            "phone": "5551234567",
        },
        "payment_method": "full",
        "addons": [],
        "parental_waiver": {
            "accepted": True,
            "version": "2026-08-parental-v1",
            "accepted_at": datetime.utcnow().isoformat() + "Z",
        },
    }


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_payment_intent_is_empty_shell_matrix():
    assert payment_intent_is_empty_shell(None) is True
    assert payment_intent_is_empty_shell(SimpleNamespace(status="requires_payment_method")) is True
    assert payment_intent_is_empty_shell(SimpleNamespace(status="canceled")) is True
    assert payment_intent_is_empty_shell(SimpleNamespace(status="requires_action")) is False
    assert payment_intent_is_empty_shell(SimpleNamespace(status="processing")) is False
    assert payment_intent_is_empty_shell(SimpleNamespace(status="succeeded")) is False
    assert payment_intent_is_empty_shell(SimpleNamespace(status="requires_confirmation")) is False


def test_signup_creates_short_ttl_pending(app_ctx, client):
    trip, pkg = _trip_pkg(capacity=3)
    email = f"{_uniq('u')}@example.com"
    payload = _booking_payload(trip, pkg, email)
    mock_pi = SimpleNamespace(id=f"pi_{uuid.uuid4().hex[:14]}", client_secret="cs_test")
    try:
        with patch("app.routes.create_payment_intent", return_value=mock_pi):
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert resp.status_code == 200
        pb = PendingBooking.query.filter_by(payment_intent_id=mock_pi.id).first()
        assert pb is not None
        assert pb.status == "pending"
        delta = (pb.expires_at - pb.created_at).total_seconds()
        assert 50 * 60 <= delta <= (EMPTY_PENDING_HOLD_MINUTES + 5) * 60
    finally:
        for row in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(row)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_abandon_pending_cancels_empty_shell(app_ctx, client):
    trip, pkg = _trip_pkg()
    pi_id = f"pi_abandon_{uuid.uuid4().hex[:12]}"
    packages = [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}]
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
        booking_data={
            "packages": packages,
            "buyer_info": {"email": "a@example.com"},
        },
    )
    db.session.add(pb)
    db.session.commit()
    assert package_spots_available(pkg.id) == 1

    with patch(
        "app.payments.retrieve_payment_intent",
        return_value=SimpleNamespace(status="requires_payment_method"),
    ), patch(
        "app.payments.safe_cancel_empty_shell_payment_intent",
        return_value=True,
    ) as cancel_mock:
        resp = client.post(
            "/api/payment/abandon-pending",
            data=json.dumps({"payment_intent_id": pi_id, "reason": "test"}),
            content_type="application/json",
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["abandoned"] is True
    assert data["kind"] == "pending_booking"
    cancel_mock.assert_called()
    pb2 = PendingBooking.query.get(pb.id)
    assert pb2.status == "cancelled"
    assert package_spots_available(pkg.id) == 2

    db.session.delete(pb2)
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()


def test_abandon_skips_microdeposit_requires_action(app_ctx):
    trip, pkg = _trip_pkg()
    pi_id = f"pi_md_{uuid.uuid4().hex[:12]}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=10),
        booking_data={
            "packages": [{"package_id": pkg.id, "quantity": 1}],
            "buyer_info": {"email": "md@example.com"},
        },
    )
    db.session.add(pb)
    db.session.commit()
    pb_id = pb.id

    with patch(
        "app.payments.retrieve_payment_intent",
        return_value=SimpleNamespace(status="requires_action"),
    ), patch(
        "app.payments.safe_cancel_empty_shell_payment_intent",
    ) as cancel_mock:
        result = abandon_pending_booking(pi_id, reason="should_skip")
    assert result["abandoned"] is False
    assert "requires_action" in (result.get("skipped_reason") or "")
    cancel_mock.assert_not_called()
    assert PendingBooking.query.get(pb_id).status == "pending"

    db.session.delete(PendingBooking.query.get(pb_id))
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()


def test_resubmit_cancels_sibling_empty_pending(app_ctx, client):
    trip, pkg = _trip_pkg(capacity=2)
    email = f"{_uniq('sib')}@example.com"
    old_pi = f"pi_old_{uuid.uuid4().hex[:12]}"
    packages = [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}]
    old = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=old_pi,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(minutes=60),
        booking_data={"packages": packages, "buyer_info": {"email": email}},
    )
    db.session.add(old)
    db.session.commit()
    assert package_spots_available(pkg.id) == 1

    new_pi = SimpleNamespace(id=f"pi_new_{uuid.uuid4().hex[:12]}", client_secret="cs")
    with patch("app.routes.create_payment_intent", return_value=new_pi), patch(
        "app.payments.retrieve_payment_intent",
        return_value=SimpleNamespace(status="requires_payment_method"),
    ), patch(
        "app.payments.safe_cancel_empty_shell_payment_intent",
        return_value=True,
    ):
        resp = client.post(
            f"/trips/{trip.slug}",
            data=json.dumps({"booking_data": _booking_payload(trip, pkg, email)}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    assert resp.status_code == 200
    old2 = PendingBooking.query.get(old.id)
    assert old2.status == "cancelled"
    new_pb = PendingBooking.query.filter_by(payment_intent_id=new_pi.id).first()
    assert new_pb is not None and new_pb.status == "pending"
    # 仅新占位
    assert package_spots_available(pkg.id) == 1

    for row in PendingBooking.query.filter_by(trip_id=trip.id).all():
        db.session.delete(row)
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()


def test_void_empty_shell_payment_keeps_requires_action(app_ctx):
    trip, pkg = _trip_pkg()
    client = Client(
        first_name="C",
        last_name="D",
        email=f"{_uniq('c')}@example.com",
    )
    db.session.add(client)
    db.session.flush()
    booking = Booking(
        trip_id=trip.id,
        client_id=client.id,
        buyer_email=client.email,
        buyer_first_name="C",
        buyer_last_name="D",
        status="deposit_paid",
        amount_paid=50.0,
        order_number=_uniq("ORD"),
    )
    db.session.add(booking)
    db.session.flush()
    shell = Payment(
        booking_id=booking.id,
        client_id=client.id,
        trip_id=trip.id,
        amount=100.0,
        status="pending",
        stripe_payment_intent_id=f"pi_shell_{uuid.uuid4().hex[:10]}",
        currency="usd",
        created_at=datetime.utcnow() - timedelta(hours=2),
    )
    live = Payment(
        booking_id=booking.id,
        client_id=client.id,
        trip_id=trip.id,
        amount=200.0,
        status="pending",
        stripe_payment_intent_id=f"pi_live_{uuid.uuid4().hex[:10]}",
        currency="usd",
        created_at=datetime.utcnow() - timedelta(hours=2),
    )
    db.session.add_all([shell, live])
    db.session.commit()

    def _retrieve(pi):
        if pi == shell.stripe_payment_intent_id:
            return SimpleNamespace(status="requires_payment_method")
        return SimpleNamespace(status="requires_action")

    with patch("app.payments.retrieve_payment_intent", side_effect=_retrieve), patch(
        "app.payments.safe_cancel_empty_shell_payment_intent",
        return_value=True,
    ):
        n = void_empty_shell_pending_payments(booking, min_age_minutes=60, commit=True)
    assert n == 1
    assert Payment.query.get(shell.id).status == "failed"
    assert Payment.query.get(live.id).status == "pending"

    db.session.delete(Payment.query.get(shell.id))
    db.session.delete(Payment.query.get(live.id))
    db.session.delete(booking)
    db.session.delete(client)
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()


def test_cleanup_empty_shell_task(app_ctx):
    trip, pkg = _trip_pkg()
    client = Client(
        first_name="E",
        last_name="F",
        email=f"{_uniq('e')}@example.com",
    )
    db.session.add(client)
    db.session.flush()
    booking = Booking(
        trip_id=trip.id,
        client_id=client.id,
        buyer_email=client.email,
        buyer_first_name="E",
        buyer_last_name="F",
        status="deposit_paid",
        amount_paid=10.0,
        order_number=_uniq("ORD"),
    )
    db.session.add(booking)
    db.session.flush()
    pay = Payment(
        booking_id=booking.id,
        client_id=client.id,
        trip_id=trip.id,
        amount=80.0,
        status="pending",
        stripe_payment_intent_id=f"pi_task_{uuid.uuid4().hex[:10]}",
        currency="usd",
        created_at=datetime.utcnow() - timedelta(hours=3),
    )
    db.session.add(pay)
    db.session.commit()

    with patch(
        "app.payments.retrieve_payment_intent",
        return_value=SimpleNamespace(status="requires_payment_method"),
    ), patch(
        "app.payments.safe_cancel_empty_shell_payment_intent",
        return_value=True,
    ):
        n = cleanup_empty_shell_pending_payments()
    assert n >= 1
    assert Payment.query.get(pay.id).status == "failed"

    db.session.delete(Payment.query.get(pay.id))
    db.session.delete(booking)
    db.session.delete(client)
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()


def test_cancel_sibling_helper_skips_processing(app_ctx):
    trip, pkg = _trip_pkg()
    email = "keep@example.com"
    packages = [{"package_id": pkg.id, "quantity": 1}]
    keep = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"pi_keep_{uuid.uuid4().hex[:10]}",
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=5),
        booking_data={"packages": packages, "buyer_info": {"email": email}},
    )
    drop = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"pi_drop_{uuid.uuid4().hex[:10]}",
        status="pending",
        expires_at=datetime.utcnow() + timedelta(minutes=30),
        booking_data={"packages": packages, "buyer_info": {"email": email}},
    )
    db.session.add_all([keep, drop])
    db.session.commit()

    def _retrieve(pi):
        if pi == keep.payment_intent_id:
            return SimpleNamespace(status="processing")
        return SimpleNamespace(status="requires_payment_method")

    with patch("app.payments.retrieve_payment_intent", side_effect=_retrieve), patch(
        "app.payments.safe_cancel_empty_shell_payment_intent",
        return_value=True,
    ):
        n = cancel_sibling_empty_pending_bookings(
            trip.id, email, except_pending_id=None, commit=True
        )
    assert n == 1
    assert PendingBooking.query.get(keep.id).status == "pending"
    assert PendingBooking.query.get(drop.id).status == "cancelled"

    for row in PendingBooking.query.filter_by(trip_id=trip.id).all():
        db.session.delete(row)
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()
