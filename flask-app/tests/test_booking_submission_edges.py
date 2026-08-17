"""
报名提交 + 名额占位边界：防客服测试类失败（Waiver / 占位 / Stripe 异常 / 状态轮询）。
"""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models import Booking, BookingPackage, Client, PendingBooking, Trip, TripPackage
from app.package_capacity import package_spots_available, validate_packages_capacity


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _published_trip_with_pkg(*, capacity=1, price=150.0):
    slug = _uniq("trip")
    trip = Trip(
        title=_uniq("title"),
        slug=slug,
        status="published",
        is_published=True,
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 10),
        trip_abbr="SB",
    )
    db.session.add(trip)
    db.session.flush()
    pkg = TripPackage(
        trip_id=trip.id,
        name="TestPkg",
        price=price,
        capacity=capacity,
        status="available",
    )
    db.session.add(pkg)
    db.session.commit()
    return trip, pkg


def _booking_payload(trip, pkg, *, email=None, waiver=True):
    email = email or f"{_uniq('u')}@example.com"
    payload = {
        "packages": [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}],
        "participants": [
            {
                "first_name": "Kid",
                "last_name": "Test",
                "dob": "2012-06-01",
            }
        ],
        "buyer_info": {
            "first_name": "Parent",
            "last_name": "Test",
            "email": email,
            "phone": "5551234567",
        },
        "payment_method": "full",
        "addons": [],
    }
    if waiver:
        payload["parental_waiver"] = {
            "accepted": True,
            "version": "2026-08-parental-v1",
            "accepted_at": datetime.utcnow().isoformat() + "Z",
        }
    return payload


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_cancelled_and_expired_pending_do_not_hold_capacity(app_ctx):
    trip, pkg = _published_trip_with_pkg(capacity=1)
    packages_data = [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}]
    try:
        cancelled = PendingBooking(
            trip_id=trip.id,
            payment_intent_id=f"pending_{uuid.uuid4().hex}",
            status="cancelled",
            expires_at=datetime.utcnow() + timedelta(hours=24),
            booking_data={"packages": packages_data},
        )
        expired = PendingBooking(
            trip_id=trip.id,
            payment_intent_id=f"pending_{uuid.uuid4().hex}",
            status="pending",
            expires_at=datetime.utcnow() - timedelta(hours=1),
            booking_data={"packages": packages_data},
        )
        db.session.add_all([cancelled, expired])
        db.session.commit()
        assert package_spots_available(pkg.id) == 1
        assert validate_packages_capacity(packages_data, lock=False) is None
    finally:
        for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_stripe_exception_cancels_pending_hold(app_ctx, client):
    trip, pkg = _published_trip_with_pkg(capacity=2)
    payload = _booking_payload(trip, pkg)
    try:
        mock_pi = SimpleNamespace(id="pi_test_mock123", client_secret="cs_test")
        with patch("app.routes.create_payment_intent", side_effect=RuntimeError("stripe down")):
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert resp.status_code == 500
        pb = PendingBooking.query.filter_by(trip_id=trip.id).order_by(PendingBooking.id.desc()).first()
        assert pb is not None
        assert pb.status == "cancelled"
        assert package_spots_available(pkg.id) == 2
    finally:
        for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_submission_requires_waiver(app_ctx, client):
    trip, pkg = _published_trip_with_pkg(capacity=5)
    payload = _booking_payload(trip, pkg, waiver=False)
    try:
        resp = client.post(
            f"/trips/{trip.slug}",
            data=json.dumps({"booking_data": payload}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert data.get("success") is False
        assert "Waiver" in (data.get("error") or "")
        assert PendingBooking.query.filter_by(trip_id=trip.id).count() == 0
    finally:
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_submission_success_reserves_and_returns_pi(app_ctx, client):
    trip, pkg = _published_trip_with_pkg(capacity=2)
    payload = _booking_payload(trip, pkg)
    try:
        mock_pi = SimpleNamespace(id="pi_test_ok123", client_secret="cs_test_ok")
        with patch("app.routes.create_payment_intent", return_value=mock_pi):
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data.get("success") is True
        assert data.get("payment_intent_id") == "pi_test_ok123"
        assert data.get("client_secret") == "cs_test_ok"
        assert package_spots_available(pkg.id) == 1
        pb = PendingBooking.query.filter_by(payment_intent_id="pi_test_ok123").first()
        assert pb is not None
        assert pb.status == "pending"
        waiver = (pb.booking_data or {}).get("parental_waiver") or {}
        assert waiver.get("version") == "2026-08-parental-v1"
    finally:
        for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_second_submission_blocked_when_last_spot_held(app_ctx, client):
    trip, pkg = _published_trip_with_pkg(capacity=1)
    p1 = _booking_payload(trip, pkg, email="first@example.com")
    p2 = _booking_payload(trip, pkg, email="second@example.com")
    try:
        mock_pi = SimpleNamespace(id="pi_first123", client_secret="cs1")
        with patch("app.routes.create_payment_intent", return_value=mock_pi):
            r1 = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": p1}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert r1.status_code == 200

        mock_pi2 = SimpleNamespace(id="pi_second456", client_secret="cs2")
        with patch("app.routes.create_payment_intent", return_value=mock_pi2):
            r2 = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": p2}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert r2.status_code == 400
        assert "sold out" in (r2.get_json().get("error") or "").lower()
        assert PendingBooking.query.filter_by(payment_intent_id="pi_second456").count() == 0
    finally:
        for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
            db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()


def test_payment_status_pending_hold_id(app_ctx, client):
    trip, pkg = _published_trip_with_pkg(capacity=5)
    hold = f"pending_{uuid.uuid4().hex}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=hold,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(hours=24),
        booking_data={"packages": [{"package_id": pkg.id, "quantity": 1}]},
    )
    db.session.add(pb)
    db.session.commit()
    try:
        with patch("app.routes.retrieve_payment_intent") as mock_retrieve:
            resp = client.get(f"/api/payment/status?payment_intent_id={hold}")
        assert resp.status_code == 200
        assert resp.get_json().get("status") == "pending"
        mock_retrieve.assert_not_called()
    finally:
        db.session.delete(pb)
        db.session.delete(pkg)
        db.session.delete(trip)
        db.session.commit()
