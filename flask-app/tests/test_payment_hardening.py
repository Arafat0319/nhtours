"""
支付路径漏洞回归：防「钱到账无订单 / 账本双加 / Waiver+DOB 建单崩溃」。
不依赖真实 Stripe；用本地 DB + 模拟 PaymentIntent dict。
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from unittest.mock import patch

import pytest

from app import db
from app.models import (
    Booking,
    BookingPackage,
    Client,
    Payment,
    PendingBooking,
    Trip,
    TripPackage,
)
from app.routes import (
    _create_booking_from_metadata,
    handle_booking_payment_intent_succeeded,
)


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _seed_trip_package(capacity=None, price=100.0):
    trip = Trip(
        title=_uniq("vuln-trip"),
        slug=_uniq("vuln-trip"),
        status="published",
        is_published=True,
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 10),
        trip_abbr="VT",
    )
    db.session.add(trip)
    db.session.flush()
    pkg = TripPackage(
        trip_id=trip.id,
        name="Standard",
        price=price,
        capacity=capacity,
        status="available",
    )
    db.session.add(pkg)
    db.session.flush()
    return trip, pkg


def _pending_payload(trip, pkg, *, email=None, pi_id=None, qty=1):
    email = email or f"{_uniq('buyer')}@example.com"
    pi_id = pi_id or f"pi_test_{uuid.uuid4().hex}"
    booking_data = {
        "trip_id": trip.id,
        "trip_slug": trip.slug,
        "buyer_info": {
            "first_name": "Test",
            "last_name": "Buyer",
            "email": email,
            "phone": "5551234567",
        },
        "packages": [
            {
                "package_id": pkg.id,
                "quantity": qty,
                "payment_plan_type": "full",
            }
        ],
        "participants": [
            {
                "first_name": "Kid",
                "last_name": "One",
                "dob": "2015-05-05",
            }
        ],
        "addons": [],
        "payment_method": "full",
        "base_amount_cents": int(round(pkg.price * 100)),
        "deposit_amount": pkg.price,
        "discount_amount": 0,
        "parental_waiver": {
            "accepted": True,
            "version": "2026-08-parental-v1",
            "accepted_at": datetime.utcnow().isoformat() + "Z",
        },
    }
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        booking_data=booking_data,
        status="pending",
        expires_at=datetime.utcnow(),
    )
    db.session.add(pb)
    db.session.commit()
    return pb, pi_id, email


def _pi_dict(pi_id, amount_cents, *, base_cents=None, fee_cents=0):
    base_cents = amount_cents if base_cents is None else base_cents
    return {
        "id": pi_id,
        "amount": amount_cents,
        "currency": "usd",
        "status": "succeeded",
        "metadata": {
            "base_amount": str(base_cents),
            "fee": str(fee_cents),
            "final_amount": str(amount_cents),
            "payment_method_type": "card",
        },
        "payment_method_types": ["card"],
    }


def _cleanup(*objs):
    for o in objs:
        if o is None:
            continue
        try:
            db.session.delete(o)
        except Exception:
            pass
    db.session.commit()


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield app


def test_create_booking_with_waiver_and_dob_no_unboundlocal(app_ctx):
    """回归：Waiver 写 datetime + 参与者 DOB 不得再 UnboundLocalError。"""
    trip, pkg = _seed_trip_package(price=150.0)
    pb, pi_id, email = _pending_payload(trip, pkg)
    try:
        booking = _create_booking_from_metadata(pi_id)
        assert booking is not None
        assert booking.buyer_email == email
        assert booking.parental_waiver_version == "2026-08-parental-v1"
        assert booking.parental_waiver_accepted_at is not None
        parts = list(booking.participants)
        assert len(parts) == 1
        assert parts[0].dob == date(2015, 5, 5)
        db.session.rollback()
    finally:
        # 清理本测试产生的行
        b = Booking.query.filter_by(buyer_email=email).order_by(Booking.id.desc()).first()
        if b:
            for bp in list(b.booking_packages):
                db.session.delete(bp)
            for p in list(b.participants):
                db.session.delete(p)
            db.session.delete(b)
        client = Client.query.filter_by(email=email).first()
        pb2 = PendingBooking.query.filter_by(payment_intent_id=pi_id).first()
        _cleanup(pb2, client, pkg, trip)


def test_succeeded_handler_does_not_double_amount_paid(app_ctx):
    """同一 PI 连续 finalize 两次，amount_paid 只应加一次。"""
    trip, pkg = _seed_trip_package(price=200.0)
    pb, pi_id, email = _pending_payload(trip, pkg)
    amount_cents = 20000
    pi = _pi_dict(pi_id, amount_cents, base_cents=20000, fee_cents=0)

    with patch("app.routes.send_booking_confirmation_email", return_value=True):
        handle_booking_payment_intent_succeeded(pi)
        pay = Payment.query.filter_by(stripe_payment_intent_id=pi_id).first()
        assert pay is not None
        assert pay.status == "succeeded"
        booking_id = pay.booking_id
        booking = Booking.query.get(booking_id)
        assert booking is not None
        first_paid = float(booking.amount_paid or 0)

        # 第二次（模拟 webhook + status 并发后的重复调用）
        handle_booking_payment_intent_succeeded(pi)
        db.session.expire_all()
        booking2 = Booking.query.get(booking_id)
        second_paid = float(booking2.amount_paid or 0)
        assert second_paid == pytest.approx(first_paid)
        assert second_paid == pytest.approx(200.0)
        pays = Payment.query.filter_by(stripe_payment_intent_id=pi_id).count()
        assert pays == 1

    # cleanup
    booking = Booking.query.get(booking_id)
    pay = Payment.query.filter_by(stripe_payment_intent_id=pi_id).first()
    if pay:
        db.session.delete(pay)
    if booking:
        for bp in list(booking.booking_packages):
            db.session.delete(bp)
        for p in list(booking.participants):
            db.session.delete(p)
        for inst in list(booking.installments):
            db.session.delete(inst)
        db.session.delete(booking)
    client = Client.query.filter_by(email=email).first()
    pb2 = PendingBooking.query.filter_by(payment_intent_id=pi_id).first()
    _cleanup(pb2, client, pkg, trip)


def test_over_capacity_still_creates_booking_after_payment(app_ctx):
    """已扣款场景：套餐名义售罄仍必须建单（不得 abort）。"""
    trip, pkg = _seed_trip_package(capacity=1, price=100.0)
    # 先占满 1 个名额
    filler_email = f"{_uniq('fill')}@example.com"
    client = Client(email=filler_email, first_name="F", last_name="Ill")
    db.session.add(client)
    db.session.flush()
    filler = Booking(
        trip_id=trip.id,
        client_id=client.id,
        buyer_email=filler_email,
        status="fully_paid",
        amount_paid=100,
        passenger_count=1,
    )
    db.session.add(filler)
    db.session.flush()
    db.session.add(
        BookingPackage(
            booking_id=filler.id,
            package_id=pkg.id,
            quantity=1,
            payment_plan_type="full",
            status="fully_paid",
            amount_paid=100,
            unit_price=100,
        )
    )
    db.session.commit()

    pb, pi_id, email = _pending_payload(trip, pkg)
    try:
        booking = _create_booking_from_metadata(pi_id)
        assert booking is not None, "sold-out must not block create after payment"
        assert booking.buyer_email == email
    finally:
        b = Booking.query.filter_by(buyer_email=email).order_by(Booking.id.desc()).first()
        if b:
            for bp in list(b.booking_packages):
                db.session.delete(bp)
            for p in list(b.participants):
                db.session.delete(p)
            db.session.delete(b)
        for bp in list(filler.booking_packages):
            db.session.delete(bp)
        db.session.delete(filler)
        client2 = Client.query.filter_by(email=email).first()
        pb2 = PendingBooking.query.filter_by(payment_intent_id=pi_id).first()
        _cleanup(pb2, client2, client, pkg, trip)


def test_create_fails_raises_for_webhook_retry(app_ctx):
    """建单失败应 raise，供 webhook 回 5xx（Stripe 重试）。"""
    with patch(
        "app.routes._create_booking_from_metadata",
        return_value=None,
    ):
        with pytest.raises(RuntimeError, match="Failed to create booking"):
            handle_booking_payment_intent_succeeded(
                _pi_dict("pi_missing_pending_xyz", 1000)
            )
