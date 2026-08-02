"""Security gates (use existing DB; no drop_all)."""
import pytest
from app.models import Booking, User, db
from app.utils import generate_receipt_token, load_receipt_token


def test_user_role_property():
    admin = User(username="x", role="admin")
    staff = User(username="y", role="staff")
    assert admin.is_admin is True
    assert staff.is_admin is False


def test_receipt_token_optional_payment_id(app):
    with app.app_context():
        tok = generate_receipt_token(1)
        assert load_receipt_token(tok, 1) == {'booking_id': 1}
        tok2 = generate_receipt_token(1, payment_id=7)
        assert load_receipt_token(tok2, 1) == {'booking_id': 1, 'payment_id': 7}
        assert load_receipt_token(tok2, 2) is None


def test_summary_requires_token_or_pi(client, app):
    with app.app_context():
        booking = Booking.query.order_by(Booking.id.desc()).first()
        if not booking:
            pytest.skip("no booking fixture")
        bid = booking.id
        tok = generate_receipt_token(bid)

    r = client.get(f"/api/booking/{bid}/summary")
    assert r.status_code == 403

    r2 = client.get(f"/api/booking/{bid}/summary?token={tok}")
    assert r2.status_code == 200


def test_booking_payment_requires_token(client, app):
    with app.app_context():
        booking = Booking.query.filter(Booking.status != "cancelled").order_by(Booking.id.desc()).first()
        if not booking:
            pytest.skip("no booking fixture")
        bid = booking.id

    r = client.get(f"/booking/payment/{bid}")
    assert r.status_code == 403


def test_staff_blocked_from_export(client, app):
    with app.app_context():
        staff = User.query.filter_by(role="staff").first()
        if not staff:
            staff = User(username="_pytest_staff", role="staff")
            staff.set_password("pytest-staff-temp")
            db.session.add(staff)
            db.session.commit()
        staff_id = staff.id

    # Flask-Login session
    with client.session_transaction() as sess:
        sess["_user_id"] = str(staff_id)
        sess["_fresh"] = True

    r = client.get("/admin/payments/export")
    assert r.status_code == 403


def test_test_routes_gated(client, app):
    app.debug = False
    assert client.get("/test/installment-modal").status_code == 404
    assert client.get("/test/installment-payment-preview").status_code == 404
