"""Cancelled order pay-link redirects must not look like Already Paid."""
from app.models import Booking, InstallmentPayment, db
from app.utils import generate_installment_token, generate_receipt_token


def test_cancelled_booking_installment_pay_redirects_to_cancelled(app, client):
    with app.app_context():
        booking = Booking.query.filter_by(status='cancelled').first()
        if not booking:
            return
        inst = (
            InstallmentPayment.query.filter_by(booking_id=booking.id)
            .filter(InstallmentPayment.installment_number > 0)
            .first()
        )
        if not inst:
            # Force a cancelled installment for the test booking
            inst = InstallmentPayment.query.filter_by(booking_id=booking.id).first()
        if not inst:
            return
        tok = generate_installment_token(inst.id)
        r = client.get(f'/pay-installment/{inst.id}?token={tok}', follow_redirects=False)
        assert r.status_code in (302, 303)
        loc = r.headers.get('Location') or ''
        assert 'cancelled=1' in loc
        assert 'already_paid=1' not in loc
        r2 = client.get(loc, follow_redirects=True)
        assert r2.status_code == 200
        body = r2.data.decode('utf-8', errors='ignore')
        assert 'Order Cancelled' in body
        assert 'Already Paid' not in body


def test_cancelled_booking_payment_page_redirects(app, client):
    with app.app_context():
        booking = Booking.query.filter_by(status='cancelled').first()
        if not booking:
            return
        tok = generate_receipt_token(booking.id)
        r = client.get(f'/booking/payment/{booking.id}?token={tok}', follow_redirects=False)
        assert r.status_code in (302, 303)
        loc = r.headers.get('Location') or ''
        assert 'cancelled=1' in loc


def test_forged_cancelled_query_ignored_on_active_booking(app, client):
    with app.app_context():
        booking = (
            Booking.query.filter(Booking.status.in_(('deposit_paid', 'fully_paid', 'pending')))
            .filter(Booking.status != 'cancelled')
            .first()
        )
        if not booking:
            return
        tok = generate_receipt_token(booking.id)
        r = client.get(
            f'/booking/success?booking_id={booking.id}&cancelled=1&token={tok}',
            follow_redirects=True,
        )
        assert r.status_code == 200
        body = r.data.decode('utf-8', errors='ignore')
        assert 'Order Cancelled' not in body
