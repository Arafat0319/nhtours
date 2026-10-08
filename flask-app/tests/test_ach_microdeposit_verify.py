"""ACH microdeposit verify: Pending extend + customer email edge cases."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app import db
from app.models import Booking, Client, Payment, PendingBooking, Trip
from app.payments import (
    ACH_MICRODEPOSIT_HOLD_DAYS,
    extend_pending_for_microdeposit,
    pending_microdeposit_hard_cap,
)
from app.routes import (
    _payment_intent_microdeposit_verify_url,
    handle_payment_intent_failed,
    handle_payment_intent_requires_action,
    send_ach_microdeposit_verify_email,
)
from app.tasks import cleanup_expired_pending_bookings


def _uniq(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _microdeposit_pi(
    pi_id="pi_micro_test",
    *,
    url="https://payments.stripe.com/microdeposit/test_verify",
    amount=147000,
    metadata=None,
):
    return {
        "id": pi_id,
        "status": "requires_action",
        "amount": amount,
        "currency": "usd",
        "metadata": metadata or {},
        "next_action": {
            "type": "verify_with_microdeposits",
            "verify_with_microdeposits": {
                "hosted_verification_url": url,
                "microdeposit_type": "descriptor_code",
            },
        },
    }


@pytest.fixture()
def app_ctx(app):
    with app.app_context():
        yield


def test_microdeposit_url_helper_variants():
    assert _payment_intent_microdeposit_verify_url(None) is None
    assert _payment_intent_microdeposit_verify_url({"status": "processing"}) is None
    assert (
        _payment_intent_microdeposit_verify_url(
            {
                "status": "requires_action",
                "next_action": {"type": "use_stripe_sdk"},
            }
        )
        is None
    )
    assert (
        _payment_intent_microdeposit_verify_url(
            {
                "status": "requires_action",
                "next_action": {
                    "type": "verify_with_microdeposits",
                    "verify_with_microdeposits": {},
                },
            }
        )
        is None
    )
    url = "https://payments.stripe.com/microdeposit/abc"
    assert (
        _payment_intent_microdeposit_verify_url(_microdeposit_pi(url=url)) == url
    )
    # Stripe SDK-like object
    details = SimpleNamespace(hosted_verification_url=url)
    na = SimpleNamespace(type="verify_with_microdeposits", verify_with_microdeposits=details)
    obj = SimpleNamespace(status="requires_action", next_action=na)
    assert _payment_intent_microdeposit_verify_url(obj) == url


def test_send_ach_verify_email_rejects_missing(app_ctx):
    with patch("app.routes.send_email_via_ses") as send:
        assert (
            send_ach_microdeposit_verify_email(
                recipient_email="",
                customer_name="A",
                trip_title="T",
                order_ref="r",
                amount=10,
                verify_url="https://example.com",
            )
            is False
        )
        assert (
            send_ach_microdeposit_verify_email(
                recipient_email="a@example.com",
                customer_name="A",
                trip_title="T",
                order_ref="r",
                amount=10,
                verify_url="",
            )
            is False
        )
        send.assert_not_called()


def test_send_ach_verify_email_renders_and_sends(app_ctx):
    with patch("app.routes.send_email_via_ses", return_value=(True, "ok")) as send:
        ok = send_ach_microdeposit_verify_email(
            recipient_email="guest@example.com",
            customer_name="Fong",
            trip_title="Mark Twain Trip",
            order_ref="registration hold #34",
            amount=1470.0,
            verify_url="https://payments.stripe.com/microdeposit/demo",
        )
        assert ok is True
        send.assert_called_once()
        args = send.call_args[0]
        assert args[1] == "guest@example.com"
        assert "verify your bank payment" in args[2].lower()
        html = args[3]
        text = args[4]
        assert "Enter verification code" in html
        assert "https://payments.stripe.com/microdeposit/demo" in html
        assert "SMXXXX" in html
        assert "not finished yet" in html.lower() or "not finished yet" in text.lower()
        assert "do not need to return" in text.lower() or "do not need to return" in html.lower()
        # open redirect / XSS: URL is attribute-escaped by Jinja for quotes; still present
        assert 'href="https://payments.stripe.com/microdeposit/demo"' in html


def test_handler_extends_pending_and_sends_once(app_ctx):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 1, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pi_id = f"pi_{_uniq('md')}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        expires_at=datetime.utcnow() - timedelta(hours=1),
        booking_data={
            "buyer_info": {
                "first_name": "Fong",
                "last_name": "Britton",
                "email": "fong-test@example.com",
            },
            "trip_slug": trip.slug,
        },
    )
    db.session.add(pb)
    db.session.commit()
    pb_id = pb.id
    created = pb.created_at
    cap = pending_microdeposit_hard_cap(pb)

    with patch("app.routes.send_email_via_ses", return_value=(True, "ok")) as send:
        handle_payment_intent_requires_action(_microdeposit_pi(pi_id))
        assert send.call_count == 1
        # idempotent second call
        handle_payment_intent_requires_action(_microdeposit_pi(pi_id))
        assert send.call_count == 1

    pb2 = PendingBooking.query.get(pb_id)
    assert pb2.status == "pending"
    # 硬上限 = created_at + 12d（非无限 now+14）
    assert pb2.expires_at.replace(microsecond=0) == cap.replace(microsecond=0)
    assert pb2.expires_at <= created + timedelta(days=ACH_MICRODEPOSIT_HOLD_DAYS, minutes=1)
    assert pb2.booking_data.get("ach_verify_email_sent") == "1"
    assert "microdeposit" in (pb2.booking_data.get("ach_verify_url") or "")

    db.session.delete(pb2)
    db.session.delete(trip)
    db.session.commit()


def test_handler_skips_non_microdeposit_requires_action(app_ctx):
    with patch("app.routes.send_email_via_ses") as send:
        handle_payment_intent_requires_action(
            {
                "id": "pi_other",
                "status": "requires_action",
                "amount": 100,
                "metadata": {},
                "next_action": {"type": "use_stripe_sdk"},
            }
        )
        send.assert_not_called()


def test_handler_no_pending_no_booking_logs_no_crash(app_ctx):
    with patch("app.routes.send_email_via_ses") as send:
        handle_payment_intent_requires_action(_microdeposit_pi("pi_orphan_none"))
        send.assert_not_called()


def test_handler_existing_booking_path(app_ctx):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 2, 1),
        end_date=date(2027, 2, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    client = Client(email=_uniq("c") + "@example.com", first_name="A", last_name="B")
    db.session.add(client)
    db.session.flush()
    booking = Booking(
        client_id=client.id,
        trip_id=trip.id,
        buyer_email=client.email,
        buyer_first_name="A",
        status="deposit_paid",
        amount_paid=100,
        order_number=_uniq("ORD"),
    )
    db.session.add(booking)
    db.session.flush()
    pi_id = f"pi_{_uniq('bk')}"
    pay = Payment(
        booking_id=booking.id,
        client_id=client.id,
        trip_id=trip.id,
        amount=400,
        status="pending",
        stripe_payment_intent_id=pi_id,
        currency="USD",
        payment_metadata={},
    )
    db.session.add(pay)
    db.session.commit()

    with patch("app.routes.send_email_via_ses", return_value=(True, "ok")) as send:
        handle_payment_intent_requires_action(
            _microdeposit_pi(pi_id, metadata={"booking_id": str(booking.id)})
        )
        assert send.call_count == 1
        handle_payment_intent_requires_action(
            _microdeposit_pi(pi_id, metadata={"booking_id": str(booking.id)})
        )
        assert send.call_count == 1

    pay2 = Payment.query.get(pay.id)
    assert pay2.payment_metadata.get("ach_verify_email_sent") == "1"

    db.session.delete(pay2)
    db.session.delete(booking)
    db.session.delete(client)
    db.session.delete(trip)
    db.session.commit()


def test_handler_resolves_booking_from_payment_without_metadata_booking_id(app_ctx):
    """metadata 缺 booking_id 时仍能按 PI 找到 Payment/Booking 并发信。"""
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 1, 1),
        end_date=date(2027, 1, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    client = Client(email=_uniq("c") + "@example.com", first_name="Joe", last_name="Z")
    db.session.add(client)
    db.session.flush()
    booking = Booking(
        client_id=client.id,
        trip_id=trip.id,
        buyer_email=None,
        buyer_first_name="Joe",
        status="fully_paid",
        amount_paid=2190,
        order_number=_uniq("ORD"),
    )
    db.session.add(booking)
    db.session.flush()
    pi_id = f"pi_{_uniq('nometabook')}"
    pay = Payment(
        booking_id=booking.id,
        client_id=client.id,
        trip_id=trip.id,
        amount=1600,
        status="pending",
        stripe_payment_intent_id=pi_id,
        currency="USD",
        payment_metadata={
            "payment_type": "addon_purchase",
            "payment_step": "addon",
            "booking_addon_id": "33",
        },
    )
    db.session.add(pay)
    db.session.commit()

    with patch("app.routes.send_email_via_ses", return_value=(True, "ok")) as send:
        handle_payment_intent_requires_action(
            _microdeposit_pi(
                pi_id,
                amount=160000,
                metadata={
                    "payment_type": "addon_purchase",
                    "payment_step": "addon",
                    "booking_addon_id": "33",
                },
            )
        )
        assert send.call_count == 1
        html = send.call_args[0][3]
        text = send.call_args[0][4]
        assert "add-on" in html.lower() or "add-on" in text.lower()
        assert client.email in str(send.call_args)

    db.session.delete(pay)
    db.session.delete(booking)
    db.session.delete(client)
    db.session.delete(trip)
    db.session.commit()


def test_cleanup_keeps_microdeposit_pending(app_ctx):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 3, 1),
        end_date=date(2027, 3, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pi_keep = f"pi_{_uniq('keep')}"
    pi_drop = f"pi_{_uniq('drop')}"
    pb_keep = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_keep,
        status="pending",
        expires_at=datetime.utcnow() - timedelta(hours=2),
        booking_data={"buyer_info": {"email": "keep@example.com"}},
    )
    pb_drop = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_drop,
        status="pending",
        expires_at=datetime.utcnow() - timedelta(hours=2),
        booking_data={"buyer_info": {"email": "drop@example.com"}},
    )
    db.session.add_all([pb_keep, pb_drop])
    db.session.commit()
    keep_id, drop_id = pb_keep.id, pb_drop.id
    keep_cap = pending_microdeposit_hard_cap(pb_keep)

    def fake_retrieve(pi_id):
        if pi_id == pi_keep:
            return SimpleNamespace(
                status="requires_action",
                next_action=SimpleNamespace(
                    type="verify_with_microdeposits",
                    verify_with_microdeposits=SimpleNamespace(
                        hosted_verification_url="https://example.com/v"
                    ),
                ),
            )
        if pi_id == pi_drop:
            return SimpleNamespace(status="requires_payment_method", next_action=None)
        return None

    with patch("app.payments.retrieve_payment_intent", side_effect=fake_retrieve), patch(
        "app.payments.safe_cancel_payment_intent", return_value=True
    ) as cancel:
        cleanup_expired_pending_bookings()

    kept = PendingBooking.query.get(keep_id)
    dropped = PendingBooking.query.get(drop_id)
    assert kept.status == "pending"
    assert kept.expires_at.replace(microsecond=0) == keep_cap.replace(microsecond=0)
    assert dropped.status == "expired"
    assert cancel.called

    db.session.delete(kept)
    db.session.delete(dropped)
    db.session.delete(trip)
    db.session.commit()


def test_cleanup_expires_microdeposit_past_hard_cap(app_ctx):
    """超过 created_at+12d 硬上限：即使 Stripe 仍 requires_action 也 expire。"""
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 6, 1),
        end_date=date(2027, 6, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pi_id = f"pi_{_uniq('oldmd')}"
    old = datetime.utcnow() - timedelta(days=ACH_MICRODEPOSIT_HOLD_DAYS + 1)
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        created_at=old,
        expires_at=datetime.utcnow() - timedelta(hours=1),
        booking_data={"buyer_info": {"email": "old@example.com"}},
    )
    db.session.add(pb)
    db.session.commit()
    pb_id = pb.id

    with patch(
        "app.payments.retrieve_payment_intent",
        return_value=SimpleNamespace(
            status="requires_action",
            next_action=SimpleNamespace(
                type="verify_with_microdeposits",
                verify_with_microdeposits=SimpleNamespace(
                    hosted_verification_url="https://payments.stripe.com/x"
                ),
            ),
        ),
    ), patch("app.payments.safe_cancel_payment_intent", return_value=True) as cancel:
        cleanup_expired_pending_bookings()
        cancel.assert_called()

    pb2 = PendingBooking.query.get(pb_id)
    assert pb2.status == "expired"
    db.session.delete(pb2)
    db.session.delete(trip)
    db.session.commit()


def test_payment_failed_expires_pending_immediately(app_ctx):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 7, 1),
        end_date=date(2027, 7, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pi_id = f"pi_{_uniq('fail')}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(days=10),
        booking_data={"buyer_info": {"email": "fail@example.com"}},
    )
    db.session.add(pb)
    db.session.commit()
    pb_id = pb.id

    with patch("app.payments.safe_cancel_payment_intent", return_value=True) as cancel:
        handle_payment_intent_failed(
            {
                "id": pi_id,
                "metadata": {},
                "last_payment_error": {
                    "code": "payment_method_microdeposit_verification_timeout",
                    "message": "Microdeposit verification timed out",
                },
            }
        )
        cancel.assert_called()

    pb2 = PendingBooking.query.get(pb_id)
    assert pb2.status == "expired"
    assert pb2.booking_data.get("expired_reason")
    # idempotent
    handle_payment_intent_failed({"id": pi_id, "metadata": {}})
    assert PendingBooking.query.get(pb_id).status == "expired"

    db.session.delete(pb2)
    db.session.delete(trip)
    db.session.commit()


def test_extend_helper_rejects_past_hard_cap(app_ctx):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 8, 1),
        end_date=date(2027, 8, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=f"pi_{_uniq('cap')}",
        status="pending",
        created_at=datetime.utcnow() - timedelta(days=ACH_MICRODEPOSIT_HOLD_DAYS + 2),
        expires_at=datetime.utcnow() - timedelta(hours=1),
        booking_data={},
    )
    db.session.add(pb)
    db.session.commit()
    assert extend_pending_for_microdeposit(pb) is False
    db.session.delete(pb)
    db.session.delete(trip)
    db.session.commit()


def test_cleanup_keeps_processing_still(app_ctx):
    """Regression: processing path still extended."""
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 4, 1),
        end_date=date(2027, 4, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pi_id = f"pi_{_uniq('proc')}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        expires_at=datetime.utcnow() - timedelta(hours=1),
        booking_data={},
    )
    db.session.add(pb)
    db.session.commit()
    pb_id = pb.id

    with patch(
        "app.payments.retrieve_payment_intent",
        return_value=SimpleNamespace(status="processing", next_action=None),
    ), patch("app.payments.safe_cancel_payment_intent") as cancel:
        cleanup_expired_pending_bookings()
        cancel.assert_not_called()

    pb2 = PendingBooking.query.get(pb_id)
    assert pb2.status == "pending"
    assert pb2.expires_at > datetime.utcnow() + timedelta(days=10)
    db.session.delete(pb2)
    db.session.delete(trip)
    db.session.commit()


def test_email_fails_does_not_mark_sent(app_ctx):
    trip = Trip(
        title=_uniq("title"),
        slug=_uniq("slug"),
        status="published",
        is_published=True,
        start_date=date(2027, 5, 1),
        end_date=date(2027, 5, 10),
        trip_abbr="MT",
    )
    db.session.add(trip)
    db.session.flush()
    pi_id = f"pi_{_uniq('failmail')}"
    pb = PendingBooking(
        trip_id=trip.id,
        payment_intent_id=pi_id,
        status="pending",
        expires_at=datetime.utcnow() + timedelta(hours=1),
        booking_data={
            "buyer_info": {"first_name": "X", "email": "failmail@example.com"},
        },
    )
    db.session.add(pb)
    db.session.commit()
    pb_id = pb.id
    cap = pending_microdeposit_hard_cap(pb)

    with patch("app.routes.send_email_via_ses", return_value=(False, "ses down")):
        handle_payment_intent_requires_action(_microdeposit_pi(pi_id))

    pb2 = PendingBooking.query.get(pb_id)
    # expires still set to hard cap; sent flag must NOT be set so retry can work
    assert pb2.expires_at.replace(microsecond=0) == cap.replace(microsecond=0)
    assert pb2.booking_data.get("ach_verify_email_sent") != "1"

    with patch("app.routes.send_email_via_ses", return_value=(True, "ok")) as send:
        handle_payment_intent_requires_action(_microdeposit_pi(pi_id))
        assert send.call_count == 1

    pb3 = PendingBooking.query.get(pb_id)
    assert pb3.booking_data.get("ach_verify_email_sent") == "1"
    db.session.delete(pb3)
    db.session.delete(trip)
    db.session.commit()


def test_verify_url_rejects_non_stripe_schemes(app_ctx):
    from app.routes import _is_safe_stripe_hosted_verify_url

    assert _is_safe_stripe_hosted_verify_url("https://payments.stripe.com/microdeposit/x")
    assert _is_safe_stripe_hosted_verify_url("https://checkout.stripe.com/c/pay/x")
    assert not _is_safe_stripe_hosted_verify_url("javascript:alert(1)")
    assert not _is_safe_stripe_hosted_verify_url("http://payments.stripe.com/x")
    assert not _is_safe_stripe_hosted_verify_url("https://evil.com/stripe")
    assert not _is_safe_stripe_hosted_verify_url("https://payments.stripe.com.evil.com/x")

    with patch("app.routes.send_email_via_ses") as send:
        assert (
            send_ach_microdeposit_verify_email(
                recipient_email="x@example.com",
                customer_name="X",
                trip_title="T",
                order_ref="r",
                amount=1,
                verify_url="javascript:alert(1)",
            )
            is False
        )
        send.assert_not_called()
        # evil host in PI next_action must not email
        handle_payment_intent_requires_action(
            _microdeposit_pi("pi_evil", url="https://evil.example/phish")
        )
        send.assert_not_called()
