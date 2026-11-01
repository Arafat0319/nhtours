"""Signup POST + discount APIs: package-only math, force full, 100% free."""
from __future__ import annotations

import json
import uuid
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models import DiscountCode, PendingBooking, Trip, TripAddOn, TripPackage


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _waiver():
    return {
        "accepted": True,
        "version": "2026-08-parental-v1",
        "accepted_at": datetime.utcnow().isoformat() + "Z",
    }


def _setup_trip():
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("trip"),
        status="published",
        is_published=True,
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 10),
        trip_abbr="DC",
    )
    db.session.add(trip)
    db.session.flush()
    pkg = TripPackage(
        trip_id=trip.id,
        name="Student",
        price=4490,
        capacity=20,
        status="available",
        payment_plan_config={
            "enabled": True,
            "allow_full_payment": True,
            "deposit_amount": 1796,
            "installments": [{"date": "2027-01-15", "amount": 2694}],
        },
    )
    addon = TripAddOn(trip_id=trip.id, name="Visa", price=285)
    db.session.add_all([pkg, addon])
    db.session.flush()
    return trip, pkg, addon


def _payload(trip, pkg, addon, *, code=None, plan="deposit_installment", quantity=1, addon_qty=1, extra=None):
    data = {
        "packages": [{"package_id": pkg.id, "quantity": quantity, "payment_plan_type": plan}],
        "addons": [{"addon_id": addon.id, "quantity": addon_qty}] if addon_qty else [],
        "participants": [{"first_name": "Kid", "last_name": "Test", "dob": "2012-06-01"}],
        "buyer_info": {
            "first_name": "Parent",
            "last_name": "Test",
            "email": f"{_uniq('u')}@example.com",
            "phone": "5551234567",
        },
        "payment_method": plan if plan == "full" else "deposit_installment",
        "discount_code": code,
        "parental_waiver": _waiver(),
        "auto_pay_opt_in": plan == "deposit_installment",
    }
    if extra:
        data.update(extra)
    return data


def _cleanup(trip, pkg, addon, *codes):
    for pb in PendingBooking.query.filter_by(trip_id=trip.id).all():
        db.session.delete(pb)
    for code in codes:
        if code is not None:
            row = DiscountCode.query.get(getattr(code, "id", None))
            if row:
                db.session.delete(row)
    db.session.delete(addon)
    db.session.delete(pkg)
    db.session.delete(trip)
    db.session.commit()


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_validate_percent_packages_only(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("P40").upper(), type="percent", amount=40)
    db.session.add(code)
    db.session.commit()
    try:
        resp = client.post(
            "/api/discount/validate",
            json={
                "code": code.code,
                "trip_id": trip.id,
                "packages": [{"package_id": pkg.id, "quantity": 1}],
                "addons": [{"addon_id": addon.id, "quantity": 1}],
            },
        )
        data = resp.get_json() or {}
        assert data.get("valid") is True
        disc = data["discount"]
        assert disc["discount_amount"] == 1796
        assert disc["final_amount"] == 2979
        assert disc["forces_full_pay"] is True
        assert disc["full_waive"] is False
    finally:
        _cleanup(trip, pkg, addon, code)


def test_validate_percent_100_full_waive(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("P100").upper(), type="percent", amount=100)
    db.session.add(code)
    db.session.commit()
    try:
        resp = client.post(
            "/api/discount/validate",
            json={
                "code": code.code,
                "trip_id": trip.id,
                "packages": [{"package_id": pkg.id, "quantity": 1}],
                "addons": [{"addon_id": addon.id, "quantity": 1}],
            },
        )
        data = resp.get_json() or {}
        assert data.get("valid") is True
        disc = data["discount"]
        assert disc["discount_amount"] == 4775
        assert disc["final_amount"] == 0
        assert disc["full_waive"] is True
    finally:
        _cleanup(trip, pkg, addon, code)


def test_post_fixed_coupon_forces_full_and_due_2081(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("FIX").upper(), type="fixed", amount=2694)
    db.session.add(code)
    db.session.commit()
    payload = _payload(trip, pkg, addon, code=code.code)
    mock_pi = SimpleNamespace(id="pi_coupon_2081", client_secret="cs_coupon_2081")
    try:
        with patch("app.routes.create_payment_intent", return_value=mock_pi) as create_pi:
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("payment_required") is True
        assert data.get("base_amount_cents") == 208100
        assert data.get("payment_plan") == "full"
        create_pi.assert_called_once()
        assert create_pi.call_args.kwargs.get("amount") == 2081
        pb = PendingBooking.query.filter_by(payment_intent_id="pi_coupon_2081").first()
        assert pb is not None
        bd = pb.booking_data or {}
        assert bd.get("payment_method") == "full"
        assert bd.get("auto_pay_opt_in") is False
        assert all(p.get("payment_plan_type") == "full" for p in bd.get("packages") or [])
        assert bd.get("discount_amount") == 2694
    finally:
        _cleanup(trip, pkg, addon, code)


def test_post_full_package_coupon_due_is_addon_only(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("PAY").upper(), type="fixed", amount=4490)
    db.session.add(code)
    db.session.commit()
    payload = _payload(trip, pkg, addon, code=code.code)
    mock_pi = SimpleNamespace(id="pi_coupon_285", client_secret="cs_coupon_285")
    try:
        with patch("app.routes.create_payment_intent", return_value=mock_pi):
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("base_amount_cents") == 28500
        assert data.get("payment_plan") == "full"
    finally:
        _cleanup(trip, pkg, addon, code)


def test_post_percent_100_skips_stripe(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("FREE").upper(), type="percent", amount=100)
    db.session.add(code)
    db.session.commit()
    payload = _payload(trip, pkg, addon, code=code.code)
    try:
        with patch("app.routes.create_payment_intent") as create_pi:
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("payment_required") is False
        assert data.get("base_amount_cents") == 0
        assert str(data.get("payment_intent_id") or "").startswith("free_")
        create_pi.assert_not_called()
        pb = PendingBooking.query.filter_by(trip_id=trip.id).first()
        assert (pb.booking_data or {}).get("discount_amount") == 4775
        assert all(
            p.get("payment_plan_type") == "full"
            for p in (pb.booking_data or {}).get("packages") or []
        )
    finally:
        _cleanup(trip, pkg, addon, code)


def test_apply_ignores_forged_amount_and_rewrites_full(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("AP").upper(), type="fixed", amount=2694)
    db.session.add(code)
    db.session.flush()
    pending = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"pi_apply_{uuid.uuid4().hex[:8]}",
        status="pending",
        booking_data={
            "trip_id": trip.id,
            "packages": [{
                "package_id": pkg.id,
                "quantity": 1,
                "payment_plan_type": "deposit_installment",
            }],
            "addons": [{"addon_id": addon.id, "quantity": 1}],
            "gross_amount": 2081,
            "base_amount_cents": 208100,
            "payment_method": "deposit_installment",
        },
    )
    db.session.add(pending)
    db.session.commit()
    try:
        with patch("app.routes.safe_cancel_payment_intent"):
            resp = client.post(
                "/api/discount/apply",
                json={
                    "payment_intent_id": pending.payment_intent_id,
                    "discount_code_id": code.id,
                    "discount_amount": 999999,
                },
            )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("discount_amount") == 2694
        assert data.get("base_amount_cents") == 208100
        assert data.get("forces_full_pay") is True
        db.session.refresh(pending)
        bd = pending.booking_data or {}
        assert bd.get("payment_method") == "full"
        assert all(p.get("payment_plan_type") == "full" for p in bd.get("packages") or [])
    finally:
        _cleanup(trip, pkg, addon, code)


def test_fake_coupon_cannot_force_full_on_installment_only(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    pkg.payment_plan_config = {
        "enabled": True,
        "allow_full_payment": False,
        "deposit_amount": 1796,
        "installments": [{"date": "2027-01-15", "amount": 2694}],
    }
    db.session.commit()
    payload = _payload(trip, pkg, addon, code="NOTAREALCODE", plan="full")
    try:
        resp = client.post(
            f"/trips/{trip.slug}",
            data=json.dumps({"booking_data": payload}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert resp.status_code == 400
        data = resp.get_json() or {}
        assert "requires installment" in (data.get("error") or "").lower()
        assert PendingBooking.query.filter_by(trip_id=trip.id).count() == 0
    finally:
        _cleanup(trip, pkg, addon)


def test_installment_only_package_accepts_full_with_valid_coupon(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    pkg.payment_plan_config = {
        "enabled": True,
        "allow_full_payment": False,
        "deposit_amount": 1796,
        "installments": [{"date": "2027-01-15", "amount": 2694}],
    }
    code = DiscountCode(trip_id=trip.id, code=_uniq("ONLY").upper(), type="fixed", amount=2694)
    db.session.add(code)
    db.session.commit()
    payload = _payload(trip, pkg, addon, code=code.code, plan="full")
    mock_pi = SimpleNamespace(id="pi_inst_only", client_secret="cs_inst_only")
    try:
        with patch("app.routes.create_payment_intent", return_value=mock_pi):
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("payment_plan") == "full"
        assert data.get("base_amount_cents") == 208100
    finally:
        _cleanup(trip, pkg, addon, code)


def test_validate_trip_code_requires_matching_trip_id(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("NEEDTRIP").upper(), type="percent", amount=40)
    db.session.add(code)
    db.session.commit()
    try:
        missing = client.post(
            "/api/discount/validate",
            json={"code": code.code, "packages": [{"package_id": pkg.id, "quantity": 1}]},
        ).get_json() or {}
        assert missing.get("valid") is False

        other = client.post(
            "/api/discount/validate",
            json={
                "code": code.code,
                "trip_id": trip.id + 99999,
                "packages": [{"package_id": pkg.id, "quantity": 1}],
            },
        ).get_json() or {}
        assert other.get("valid") is False
    finally:
        _cleanup(trip, pkg, addon, code)


def test_validate_ignores_packages_from_other_trips(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    other_trip, other_pkg, other_addon = _setup_trip()
    other_pkg.price = 99999
    code = DiscountCode(trip_id=trip.id, code=_uniq("SCOPE").upper(), type="percent", amount=40)
    db.session.add(code)
    db.session.commit()
    try:
        resp = client.post(
            "/api/discount/validate",
            json={
                "code": code.code,
                "trip_id": trip.id,
                "packages": [
                    {"package_id": pkg.id, "quantity": 1},
                    {"package_id": other_pkg.id, "quantity": 1},
                ],
                "addons": [{"addon_id": addon.id, "quantity": 1}],
            },
        )
        data = resp.get_json() or {}
        assert data.get("valid") is True
        disc = data["discount"]
        assert disc["discount_amount"] == 1796
        assert disc["final_amount"] == 2979
    finally:
        _cleanup(other_trip, other_pkg, other_addon)
        _cleanup(trip, pkg, addon, code)


def _post_booking(client, trip, payload, pi_id="pi_edge"):
    mock_pi = SimpleNamespace(id=pi_id, client_secret=f"cs_{pi_id}")
    with patch("app.routes.create_payment_intent", return_value=mock_pi) as create_pi:
        resp = client.post(
            f"/trips/{trip.slug}",
            data=json.dumps({"booking_data": payload}),
            content_type="application/json",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
    return resp, create_pi


def test_post_ignores_forged_discount_amount(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("FORGE").upper(), type="fixed", amount=2694)
    db.session.add(code)
    db.session.commit()
    payload = _payload(
        trip, pkg, addon, code=code.code,
        extra={"discount_amount": 999999, "discount_code_id": 0},
    )
    try:
        resp, create_pi = _post_booking(client, trip, payload, "pi_forge")
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("base_amount_cents") == 208100
        create_pi.assert_called_once()
        assert create_pi.call_args.kwargs.get("amount") == 2081
    finally:
        _cleanup(trip, pkg, addon, code)


def test_post_forged_amount_without_code_does_not_discount(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    db.session.commit()
    payload = _payload(
        trip, pkg, addon, plan="full",
        extra={"discount_amount": 999999, "discount_code": None},
    )
    try:
        resp, create_pi = _post_booking(client, trip, payload, "pi_nodisc")
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("base_amount_cents") == 477500
        assert create_pi.call_args.kwargs.get("amount") == 4775
    finally:
        _cleanup(trip, pkg, addon)


def test_post_two_travelers_scales_percent(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("QTY2").upper(), type="percent", amount=40)
    db.session.add(code)
    db.session.commit()
    payload = _payload(trip, pkg, addon, code=code.code, quantity=2, addon_qty=2)
    try:
        resp, create_pi = _post_booking(client, trip, payload, "pi_qty2")
        data = resp.get_json() or {}
        assert data.get("success") is True
        # packages 8980 * 40% = 3592 off; due = 8980 - 3592 + 570 = 5958
        assert data.get("base_amount_cents") == 595800
        assert data.get("payment_plan") == "full"
        assert create_pi.call_args.kwargs.get("amount") == 5958
    finally:
        _cleanup(trip, pkg, addon, code)


def test_post_percent_1_and_99_force_full(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    c1 = DiscountCode(trip_id=trip.id, code=_uniq("P1").upper(), type="percent", amount=1)
    c99 = DiscountCode(trip_id=trip.id, code=_uniq("P99").upper(), type="percent", amount=99)
    db.session.add_all([c1, c99])
    db.session.commit()
    try:
        resp, _ = _post_booking(
            client, trip, _payload(trip, pkg, addon, code=c1.code), "pi_p1"
        )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("payment_plan") == "full"
        assert data.get("base_amount_cents") == 473010  # 4490 - 44.90 + 285

        resp, _ = _post_booking(
            client, trip, _payload(trip, pkg, addon, code=c99.code), "pi_p99"
        )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("payment_plan") == "full"
        assert data.get("base_amount_cents") == 32990  # 4490 - 4445.10 + 285
    finally:
        _cleanup(trip, pkg, addon, c1, c99)


def test_post_percent_100_without_addon(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("FREE0").upper(), type="percent", amount=100)
    db.session.add(code)
    db.session.commit()
    payload = _payload(trip, pkg, addon, code=code.code, addon_qty=0)
    try:
        with patch("app.routes.create_payment_intent") as create_pi:
            resp = client.post(
                f"/trips/{trip.slug}",
                data=json.dumps({"booking_data": payload}),
                content_type="application/json",
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
        data = resp.get_json() or {}
        assert data.get("success") is True
        assert data.get("payment_required") is False
        assert data.get("base_amount_cents") == 0
        create_pi.assert_not_called()
    finally:
        _cleanup(trip, pkg, addon, code)


def test_validate_empty_unknown_and_forged_order_amount(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    code = DiscountCode(trip_id=trip.id, code=_uniq("VA").upper(), type="percent", amount=40)
    db.session.add(code)
    db.session.commit()
    try:
        empty = client.post("/api/discount/validate", json={"code": " ", "trip_id": trip.id}).get_json()
        assert empty.get("valid") is False
        unknown = client.post(
            "/api/discount/validate",
            json={"code": "NOPE123", "trip_id": trip.id},
        ).get_json()
        assert unknown.get("valid") is False
        forged = client.post(
            "/api/discount/validate",
            json={
                "code": code.code,
                "trip_id": trip.id,
                "order_amount": 1,
                "packages": [{"package_id": pkg.id, "quantity": 1}],
                "addons": [{"addon_id": addon.id, "quantity": 1}],
            },
        ).get_json()
        assert forged.get("valid") is True
        assert forged["discount"]["discount_amount"] == 1796
        assert forged["discount"]["final_amount"] == 2979
    finally:
        _cleanup(trip, pkg, addon, code)


def test_apply_missing_pi_and_wrong_trip_code(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    other, other_pkg, other_addon = _setup_trip()
    code = DiscountCode(trip_id=other.id, code=_uniq("WRONG").upper(), type="fixed", amount=100)
    db.session.add(code)
    pending = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"pi_miss_{uuid.uuid4().hex[:8]}",
        status="pending",
        booking_data={
            "trip_id": trip.id,
            "packages": [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}],
            "addons": [{"addon_id": addon.id, "quantity": 1}],
            "gross_amount": 4775,
            "base_amount_cents": 477500,
        },
    )
    db.session.add(pending)
    db.session.commit()
    try:
        missing = client.post("/api/discount/apply", json={"discount_code_id": code.id}).get_json()
        assert missing.get("success") is False
        wrong = client.post(
            "/api/discount/apply",
            json={
                "payment_intent_id": pending.payment_intent_id,
                "discount_code_id": code.id,
            },
        ).get_json()
        assert wrong.get("success") is False
        assert "not valid for this trip" in (wrong.get("message") or "").lower()
    finally:
        _cleanup(other, other_pkg, other_addon, code)
        _cleanup(trip, pkg, addon)


def test_create_free_rejects_nonzero_pending(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    pending = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"pi_nz_{uuid.uuid4().hex[:8]}",
        status="pending",
        booking_data={
            "trip_id": trip.id,
            "packages": [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}],
            "base_amount_cents": 28500,
        },
    )
    db.session.add(pending)
    db.session.commit()
    try:
        resp = client.post(
            "/api/booking/create-free",
            json={"payment_intent_id": pending.payment_intent_id},
        )
        data = resp.get_json() or {}
        assert data.get("success") is False
        assert resp.status_code == 400
    finally:
        _cleanup(trip, pkg, addon)


def test_create_free_amount_without_code_cannot_override_installment_only(app_ctx, client):
    trip, pkg, addon = _setup_trip()
    pkg.payment_plan_config = {
        "enabled": True,
        "allow_full_payment": False,
        "deposit_amount": 1796,
        "installments": [{"date": "2027-01-15", "amount": 2694}],
    }
    pending = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"free_fake_{uuid.uuid4().hex[:8]}",
        status="pending",
        booking_data={
            "trip_id": trip.id,
            "packages": [{"package_id": pkg.id, "quantity": 1, "payment_plan_type": "full"}],
            "discount_amount": 4775,
            "base_amount_cents": 0,
        },
    )
    db.session.add(pending)
    db.session.commit()
    try:
        resp = client.post(
            "/api/booking/create-free",
            json={"payment_intent_id": pending.payment_intent_id},
        )
        data = resp.get_json() or {}
        assert data.get("success") is False
        assert "installment" in (data.get("message") or "").lower()
        assert PendingBooking.query.filter_by(id=pending.id).first().status == "pending"
    finally:
        _cleanup(trip, pkg, addon)
