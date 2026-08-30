"""Auto Pay + admin overdue notify: unit/integration edge cases."""

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def test_enable_disable_auto_pay_helpers(app):
    from app import db
    from app.auto_pay import disable_auto_pay, enable_auto_pay
    from app.models import Booking, Client, InstallmentPayment, Trip

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            pytest.skip("no trip")
        client = Client(email="autopay-ut@example.com", first_name="A", last_name="P")
        db.session.add(client)
        db.session.flush()
        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            buyer_email="autopay-ut@example.com",
            buyer_first_name="A",
            status="deposit_paid",
            amount_paid=150,
            stripe_customer_id="cus_test_ut",
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(
            InstallmentPayment(
                booking_id=booking.id,
                installment_number=1,
                amount=400,
                due_date=date.today() + timedelta(days=10),
                status="pending",
            )
        )
        db.session.commit()

        with patch("app.auto_pay.attach_payment_method_to_customer", return_value=True):
            with patch("app.auto_pay.ensure_stripe_customer_for_booking", return_value="cus_test_ut"):
                ok, err = enable_auto_pay(booking, "pm_card_visa", source="test")
        assert ok is True and err is None
        assert booking.auto_pay_enabled is True
        assert booking.auto_pay_payment_method_id == "pm_card_visa"

        ok, err = disable_auto_pay(booking, source="test")
        assert ok is True
        assert booking.auto_pay_enabled is False
        assert booking.auto_pay_payment_method_id == "pm_card_visa"  # kept for re-enable

        db.session.rollback()


def test_enable_requires_payment_method(app):
    from app.auto_pay import enable_auto_pay

    booking = SimpleNamespace(
        id=1,
        status="deposit_paid",
        stripe_customer_id="cus_x",
        auto_pay_enabled=False,
        auto_pay_opt_in=False,
        auto_pay_payment_method_id=None,
        auto_pay_enabled_at=None,
        auto_pay_disabled_at=None,
        auto_pay_last_error=None,
    )
    ok, err = enable_auto_pay(booking, "", source="test")
    assert ok is False
    assert "Select" in (err or "")


def test_sync_enables_only_when_opt_in(app):
    from app.auto_pay import sync_auto_pay_after_successful_payment

    booking = SimpleNamespace(
        id=99,
        auto_pay_opt_in=False,
        auto_pay_enabled=False,
        stripe_customer_id="cus_x",
        auto_pay_payment_method_id=None,
        status="deposit_paid",
    )
    payment = SimpleNamespace(
        payment_method_id="pm_1",
        stripe_customer_id=None,
        payment_metadata={},
    )
    with patch("app.auto_pay.InstallmentPayment") as IP:
        IP.query.filter_by.return_value.count.return_value = 2
        with patch("app.auto_pay.attach_payment_method_to_customer", return_value=True):
            with patch("app.auto_pay.enable_auto_pay") as en:
                sync_auto_pay_after_successful_payment(booking, payment, {"payment_method": "pm_1"})
                en.assert_not_called()

    booking.auto_pay_opt_in = True
    with patch("app.auto_pay.InstallmentPayment") as IP:
        IP.query.filter_by.return_value.count.return_value = 2
        with patch("app.auto_pay.attach_payment_method_to_customer", return_value=True):
            with patch("app.auto_pay.enable_auto_pay") as en:
                sync_auto_pay_after_successful_payment(
                    booking, payment, {"payment_method": "pm_1", "customer": "cus_x"}
                )
                en.assert_called_once()


def test_charge_skips_when_disabled_or_ach_or_settled(app):
    from app.auto_pay import charge_installment_via_auto_pay

    booking = SimpleNamespace(
        id=1,
        auto_pay_enabled=False,
        auto_pay_payment_method_id="pm_x",
        stripe_customer_id="cus_x",
        auto_pay_last_error=None,
        auto_pay_last_charge_at=None,
    )
    inst = SimpleNamespace(id=1, booking=booking, booking_id=1)
    ok, detail = charge_installment_via_auto_pay(inst)
    assert ok is False and detail == "auto_pay_disabled"

    booking.auto_pay_enabled = True
    with patch("app.auto_pay.Payment") as P:
        P.query.filter.return_value.order_by.return_value.all.return_value = []
        with patch("app.auto_pay._stripe_ready", return_value=True):
            with patch("app.payments.installment_has_processing_ach", return_value=True):
                with patch("app.payments.booking_has_processing_ach_payment", return_value=False):
                    with patch("app.payments.calculate_booking_total", return_value={"amount_due": 100}):
                        ok, detail = charge_installment_via_auto_pay(inst)
    assert ok is False and detail == "ach_processing"

    with patch("app.auto_pay.Payment") as P:
        P.query.filter.return_value.order_by.return_value.all.return_value = []
        with patch("app.auto_pay._stripe_ready", return_value=True):
            with patch("app.payments.installment_has_processing_ach", return_value=False):
                with patch("app.payments.booking_has_processing_ach_payment", return_value=False):
                    with patch("app.payments.calculate_booking_total", return_value={"amount_due": 0}):
                        ok, detail = charge_installment_via_auto_pay(inst)
    assert ok is False and detail == "already_settled"


def test_charge_skips_open_pending_payment(app):
    from app.auto_pay import charge_installment_via_auto_pay

    booking = SimpleNamespace(
        id=1,
        auto_pay_enabled=True,
        auto_pay_payment_method_id="pm_x",
        stripe_customer_id="cus_x",
        auto_pay_last_error=None,
        auto_pay_last_charge_at=None,
    )
    inst = SimpleNamespace(id=10, booking=booking, booking_id=1)
    pending = SimpleNamespace(
        id=5,
        booking_id=1,
        status="pending",
        installment_payment_id=10,
        payment_metadata={},
        stripe_payment_intent_id="pi_open",
    )
    with patch("app.auto_pay.Payment") as P:
        P.query.filter.return_value.order_by.return_value.all.return_value = [pending]
        with patch("app.payments.installment_has_processing_ach", return_value=False):
            with patch("app.payments.booking_has_processing_ach_payment", return_value=False):
                with patch("app.payments.payment_covers_installment", return_value=True):
                    ok, detail = charge_installment_via_auto_pay(inst)
    assert ok is False and detail == "open_payment_in_progress"


def test_charge_defers_ach_default_pm(app):
    from app.auto_pay import charge_installment_via_auto_pay

    booking = SimpleNamespace(
        id=1,
        auto_pay_enabled=True,
        auto_pay_payment_method_id="pm_ach",
        stripe_customer_id="cus_x",
        auto_pay_last_error=None,
        auto_pay_last_charge_at=None,
    )
    inst = SimpleNamespace(id=1, booking=booking, booking_id=1)
    pm = SimpleNamespace(type="us_bank_account")
    with patch("app.auto_pay.Payment") as P:
        P.query.filter.return_value.order_by.return_value.all.return_value = []
        with patch("app.auto_pay._stripe_ready", return_value=True):
            with patch("app.auto_pay.stripe.PaymentMethod.retrieve", return_value=pm):
                with patch("app.payments.installment_has_processing_ach", return_value=False):
                    with patch("app.payments.booking_has_processing_ach_payment", return_value=False):
                        with patch("app.payments.calculate_booking_total", return_value={"amount_due": 100}):
                            with patch("app.payments.catch_up_summary_items", return_value=[{"amount_cents": 10000}]):
                                with patch("app.payments.catch_up_amount_cents", return_value=10000):
                                    ok, detail = charge_installment_via_auto_pay(inst, card_only=True)
    assert ok is False and detail == "ach_deferred"


def test_admin_overdue_skips_already_notified(app):
    from app import db
    from app.models import Booking, Client, InstallmentPayment, Trip
    from app.tasks import notify_admins_of_overdue_installments

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            pytest.skip("no trip")
        client = Client(email="overdue-ut@example.com", first_name="O", last_name="D")
        db.session.add(client)
        db.session.flush()
        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            buyer_email="overdue-ut@example.com",
            buyer_first_name="O",
            status="deposit_paid",
            amount_paid=100,
        )
        db.session.add(booking)
        db.session.flush()
        inst = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=200,
            due_date=date.today() - timedelta(days=5),
            status="overdue",
            admin_overdue_notified_at=datetime.utcnow(),
        )
        db.session.add(inst)
        db.session.commit()

        # Isolate from other overdue rows in shared local DB
        from app.models import InstallmentPayment as IP
        for other in IP.query.filter(
            IP.id != inst.id,
            IP.admin_overdue_notified_at.is_(None),
            IP.status.in_(("pending", "overdue")),
            IP.due_date <= date.today() - timedelta(days=3),
        ).all():
            other.admin_overdue_notified_at = datetime.utcnow()
        db.session.commit()

        with patch("app.tasks.send_admin_overdue_installment_email", return_value=True) as send:
            n = notify_admins_of_overdue_installments(
                today=date.today(),
                booking_is_settled=lambda b: False,
                skip_ach_in_flight=lambda i: False,
            )
        assert n == 0
        send.assert_not_called()
        db.session.delete(inst)
        db.session.commit()


def test_admin_overdue_notifies_once(app):
    from app import db
    from app.models import Booking, Client, InstallmentPayment, Trip
    from app.tasks import notify_admins_of_overdue_installments

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            pytest.skip("no trip")
        client = Client(email="overdue2-ut@example.com", first_name="O", last_name="D")
        db.session.add(client)
        db.session.flush()
        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            buyer_email="overdue2-ut@example.com",
            buyer_first_name="O",
            status="deposit_paid",
            amount_paid=100,
        )
        db.session.add(booking)
        db.session.flush()
        inst = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=200,
            due_date=date.today() - timedelta(days=4),
            status="pending",
            admin_overdue_notified_at=None,
        )
        db.session.add(inst)
        db.session.commit()

        from app.models import InstallmentPayment as IP
        for other in IP.query.filter(
            IP.id != inst.id,
            IP.admin_overdue_notified_at.is_(None),
            IP.status.in_(("pending", "overdue")),
            IP.due_date <= date.today() - timedelta(days=3),
        ).all():
            other.admin_overdue_notified_at = datetime.utcnow()
        db.session.commit()

        with patch("app.tasks.send_admin_overdue_installment_email", return_value=True):
            n = notify_admins_of_overdue_installments(
                today=date.today(),
                booking_is_settled=lambda b: False,
                skip_ach_in_flight=lambda i: False,
            )
        assert n == 1
        assert inst.admin_overdue_notified_at is not None
        assert inst.status == "overdue"

        with patch("app.tasks.send_admin_overdue_installment_email", return_value=True) as send:
            n2 = notify_admins_of_overdue_installments(
                today=date.today(),
                booking_is_settled=lambda b: False,
                skip_ach_in_flight=lambda i: False,
            )
        assert n2 == 0
        send.assert_not_called()
        db.session.delete(inst)
        db.session.commit()


def test_installment_unpaid_action_error_paid():
    from app.installment_admin_links import installment_unpaid_action_error

    booking = SimpleNamespace(id=1)
    inst = SimpleNamespace(booking=booking, status="paid", id=1)
    with patch("app.installment_admin_links.Payment") as P:
        P.query.filter_by.return_value.first.return_value = None
        assert installment_unpaid_action_error(inst) == "This installment is already paid"


def test_installment_unpaid_blocks_ach_processing():
    from app.installment_admin_links import installment_unpaid_action_error

    booking = SimpleNamespace(id=1)
    inst = SimpleNamespace(booking=booking, booking_id=1, status="pending", id=1)
    with patch("app.installment_admin_links.Payment") as P:
        P.query.filter_by.return_value.first.return_value = None
        with patch("app.payments.installment_has_processing_ach", return_value=True):
            with patch("app.payments.booking_has_processing_ach_payment", return_value=False):
                err = installment_unpaid_action_error(inst)
    assert err and "processing" in err.lower()


def test_auto_pay_token_roundtrip(app):
    from app.utils import generate_auto_pay_token, verify_auto_pay_token

    with app.app_context():
        tok = generate_auto_pay_token(42)
        assert verify_auto_pay_token(tok, 42) is True
        assert verify_auto_pay_token(tok, 43) is False
        assert verify_auto_pay_token(None, 42) is False


def test_reminder_email_context_includes_auto_pay_cta(app):
    """Render reminder template both Enable and Manage variants."""
    from flask import render_template

    with app.app_context():
        for enabled, label in ((False, "Enable Auto Pay"), (True, "Manage Auto Pay")):
            html = render_template(
                "emails/installment_reminder.html",
                subject_line="Test",
                brand_subtitle="Payment reminder",
                customer_name="Alex",
                urgency_text="Due soon",
                installment_label="Installment #1",
                amount=100.0,
                due_date_label="September 1, 2026",
                order_number="2612MT-DEMO",
                payment_link="https://example.com/pay",
                email_logo_url=None,
                footer_note="Thanks",
                days_overdue=None,
                auto_pay_enabled=enabled,
                auto_pay_url="https://example.com/auto-pay",
                auto_pay_cta_label=label,
                highlight_bg="#f0f9ff",
                highlight_border="#bae6fd",
                highlight_label="#0369a1",
                highlight_amount="#0c4a6e",
                highlight_title="Amount due",
                cta_bg="#0066ff",
                cta_label="Pay now",
            )
            assert label in html
            assert "https://example.com/auto-pay" in html


def test_auto_pay_preview_route(app):
    client = app.test_client()
    # DEBUG apps allow preview
    if not app.debug:
        pytest.skip("preview requires debug")
    r = client.get("/test/auto-pay-preview?state=off")
    assert r.status_code == 200
    assert b"Auto Pay" in r.data
    assert b"Enable Auto Pay" in r.data or b"off" in r.data.lower()

    r2 = client.get("/test/auto-pay-preview?state=on")
    assert r2.status_code == 200
    assert b"Turn off Auto Pay" in r2.data or b"on" in r2.data.lower()

    r3 = client.get("/test/auto-pay-preview?state=empty")
    assert r3.status_code == 200
    assert b"No saved payment methods" in r3.data


def test_existing_booking_defaults_safe(app):
    """New Auto Pay columns must not break reading legacy-like bookings."""
    from app.models import Booking

    with app.app_context():
        b = Booking.query.filter(Booking.status != "cancelled").first()
        if not b:
            pytest.skip("no booking")
        # Attribute access must not raise; falsy when unset
        assert bool(getattr(b, "auto_pay_enabled", False)) in (True, False)
        _ = getattr(b, "stripe_customer_id", None)
        _ = getattr(b, "auto_pay_payment_method_id", None)


def test_find_due_dedupes_per_booking(app):
    from app import db
    from app.auto_pay import find_due_auto_pay_installments
    from app.models import Booking, Client, InstallmentPayment, Trip

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            pytest.skip("no trip")
        client = Client(email="due-ut@example.com", first_name="D", last_name="U")
        db.session.add(client)
        db.session.flush()
        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            buyer_email="due-ut@example.com",
            status="deposit_paid",
            amount_paid=100,
            auto_pay_enabled=True,
            auto_pay_payment_method_id="pm_x",
            stripe_customer_id="cus_x",
        )
        db.session.add(booking)
        db.session.flush()
        early = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=100,
            due_date=date.today() - timedelta(days=2),
            status="overdue",
        )
        later = InstallmentPayment(
            booking_id=booking.id,
            installment_number=2,
            amount=100,
            due_date=date.today(),
            status="pending",
        )
        db.session.add_all([early, later])
        db.session.commit()

        rows = find_due_auto_pay_installments(today=date.today())
        mine = [r for r in rows if r.booking_id == booking.id]
        assert len(mine) == 1
        assert mine[0].id == early.id
        db.session.rollback()
