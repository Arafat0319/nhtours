"""每日 Overdue digest：有逾期才发；含 reminder_count。"""

from datetime import date, datetime, timedelta
from unittest.mock import patch

import pytest


def test_daily_overdue_digest_skips_when_none(app):
    from app.tasks import send_admin_daily_overdue_digest

    with app.app_context():
        with patch("app.tasks.collect_overdue_bookings_for_digest", return_value=[]):
            with patch("app.tasks.send_email_via_ses") as send:
                result = send_admin_daily_overdue_digest(today=date.today())
        assert result["count"] == 0
        assert result["sent"] is False
        assert result.get("skipped_reason") == "none"
        send.assert_not_called()


def test_daily_overdue_digest_sends_with_details(app):
    from app.tasks import send_admin_daily_overdue_digest

    row = {
        "order_number": "2601UT-OD-001",
        "customer_name": "Test Parent",
        "customer_email": "parent@example.com",
        "trip_title": "Unit Test Trip",
        "balance_due": 450.0,
        "oldest_due_date": date.today() - timedelta(days=5),
        "oldest_due_label": "January 1, 2026",
        "days_overdue": 5,
        "reminders_sent": 3,
        "last_reminder_label": "Jan 10, 2026",
        "manage_url": "https://nhtours.com/admin/trips/1/manage",
        "booking_id": 1,
    }

    with app.app_context():
        with patch("app.tasks.collect_overdue_bookings_for_digest", return_value=[row]):
            with patch(
                "app.tasks.send_email_via_ses", return_value=(True, "ok")
            ) as send:
                result = send_admin_daily_overdue_digest(today=date.today())

        assert result["count"] == 1
        assert result["sent"] is True
        send.assert_called_once()
        _sender, _recipient, subject, html_body, text_body = send.call_args[0]
        assert "Daily overdue digest" in subject
        assert "1 booking" in subject
        assert "2601UT-OD-001" in html_body
        assert "Reminders sent" in html_body
        assert ">3<" in html_body or "Reminders sent:</strong> 3" in html_body
        assert "Reminders sent: 3" in text_body
        assert "450.00" in html_body


def test_collect_overdue_includes_reminder_count(app):
    from app import db
    from app.models import Booking, Client, InstallmentPayment, Trip
    from app.tasks import collect_overdue_bookings_for_digest

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            pytest.skip("no trip")

        client = Client(
            email="digest-ut@example.com", first_name="Digest", last_name="UT"
        )
        db.session.add(client)
        db.session.flush()
        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            order_number="2601UT-DIGEST-001",
            buyer_email="digest-ut@example.com",
            buyer_first_name="Digest",
            buyer_last_name="UT",
            status="deposit_paid",
            amount_paid=100,
        )
        db.session.add(booking)
        db.session.flush()
        today = date.today()
        inst = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=200,
            due_date=today - timedelta(days=4),
            status="overdue",
            reminder_count=2,
            reminder_sent=True,
            reminder_sent_at=datetime.utcnow() - timedelta(days=1),
        )
        db.session.add(inst)
        db.session.commit()
        booking_id = booking.id
        inst_id = inst.id

        try:
            with patch(
                "app.payments.booking_payment_display_status", return_value="overdue"
            ):
                with patch("app.payments.booking_balance_due", return_value=200.0):
                    rows = collect_overdue_bookings_for_digest(today=today)

            match = [r for r in rows if r.get("booking_id") == booking_id]
            assert len(match) == 1
            assert match[0]["reminders_sent"] == 2
            assert match[0]["days_overdue"] == 4
            assert match[0]["balance_due"] == 200.0
            assert match[0]["order_number"] == "2601UT-DIGEST-001"
        finally:
            db.session.delete(InstallmentPayment.query.get(inst_id))
            db.session.delete(Booking.query.get(booking_id))
            db.session.delete(Client.query.get(client.id))
            db.session.commit()


def test_scan_ledger_calls_digest_in_finally(app):
    from app.tasks import scan_ledger_anomalies

    with app.app_context():
        app.config["LEDGER_ALERTS_ENABLED"] = False
        with patch(
            "app.tasks.send_admin_daily_overdue_digest",
            return_value={"count": 0, "sent": False, "skipped_reason": "none"},
        ) as digest:
            result = scan_ledger_anomalies()
        digest.assert_called_once()
        assert result.get("overdue_digest", {}).get("skipped_reason") == "none"
