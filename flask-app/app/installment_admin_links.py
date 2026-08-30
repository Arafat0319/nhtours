"""Admin helpers for installment payment links and reminder eligibility."""

from __future__ import annotations

from flask import current_app, url_for

from app.models import Payment
from app.utils import generate_installment_token


def installment_unpaid_action_error(installment):
    """
    If installment cannot receive reminder / payment-link actions, return error message.
    Otherwise return None.
    """
    if not installment or not installment.booking:
        return 'Booking not found'
    status = (installment.status or '')
    if status == 'paid':
        return 'This installment is already paid'
    if status == 'cancelled':
        return 'This installment is cancelled'
    succeeded_pay = Payment.query.filter_by(
        installment_payment_id=installment.id,
        status='succeeded',
    ).first()
    if succeeded_pay:
        return 'This installment already has a successful payment'

    from app.payments import booking_has_processing_ach_payment, installment_has_processing_ach

    if installment_has_processing_ach(installment) or booking_has_processing_ach_payment(
        installment.booking_id
    ):
        return (
            'A bank transfer for this order is still processing; '
            'cannot send link until it clears'
        )
    return None


def build_installment_payment_urls(installment):
    """Return (payment_url, payoff_url) with signed tokens (_external)."""
    token = generate_installment_token(installment.id)
    try:
        payment_url = url_for(
            'main.pay_installment',
            installment_id=installment.id,
            token=token,
            _external=True,
        )
        payoff_url = url_for(
            'main.pay_installment_payoff',
            installment_id=installment.id,
            token=token,
            _external=True,
        )
    except Exception:
        base = (current_app.config.get('BASE_URL') or 'https://nhtours.com').rstrip('/')
        payment_url = f'{base}/pay-installment/{installment.id}?token={token}'
        payoff_url = f'{base}/pay-installment/{installment.id}/payoff?token={token}'
    return payment_url, payoff_url
