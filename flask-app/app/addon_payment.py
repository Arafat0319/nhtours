"""Settle Manage post-add addon payments (webhook + processing)."""
from __future__ import annotations

from datetime import datetime

from flask import current_app

from app import db
from app.addon_admin import (
    booking_addon_line_total,
    mark_addon_failed,
    mark_addon_paid,
    mark_addon_processing,
)
from app.models import Booking, BookingAddOn, Payment
from app.payments import (
    calculate_booking_total,
    extract_stripe_charge_id,
)


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def find_booking_addon_for_intent(payment_intent, metadata=None):
    metadata = metadata or (payment_intent.get('metadata') or {})
    ba_id = metadata.get('booking_addon_id')
    if ba_id:
        try:
            ba = BookingAddOn.query.get(int(ba_id))
            if ba:
                return ba
        except (TypeError, ValueError):
            pass
    pi_id = payment_intent.get('id') if isinstance(payment_intent, dict) else None
    if pi_id:
        return BookingAddOn.query.filter_by(stripe_payment_intent_id=pi_id).first()
    return None


def is_addon_purchase_intent(metadata):
    if not metadata:
        return False
    if (metadata.get('payment_type') or '') == 'addon_purchase':
        return True
    if (metadata.get('payment_step') or '') in ('addon', 'addon_purchase'):
        return True
    return False


def handle_addon_payment_processing(payment_intent):
    """ACH processing: Payment row + addon payment_status=processing + order_processing email."""
    from app.routes import send_order_processing_email, _payment_method_type_from_intent

    metadata = payment_intent.get('metadata') or {}
    if not is_addon_purchase_intent(metadata):
        return False

    ba = find_booking_addon_for_intent(payment_intent, metadata)
    if not ba or not ba.booking:
        current_app.logger.warning(
            'Addon processing: booking_addon not found for PI %s',
            payment_intent.get('id'),
        )
        return True

    booking = ba.booking
    payment_intent_id = payment_intent['id']
    pm_type = _payment_method_type_from_intent(payment_intent, metadata)
    total_amount_cents = payment_intent.get('amount', 0) or 0
    base_amount_cents = _parse_int(metadata.get('base_amount'))
    fee_cents = _parse_int(metadata.get('fee')) or 0
    tax_amount_cents = _parse_int(metadata.get('tax_amount')) or 0
    final_amount_cents = _parse_int(metadata.get('final_amount'))
    funding = metadata.get('funding') or ('ach' if pm_type == 'us_bank_account' else None)
    brand = metadata.get('brand') or ('us_bank' if pm_type == 'us_bank_account' else None)
    if final_amount_cents is None:
        final_amount_cents = total_amount_cents
    if base_amount_cents is None:
        base_amount_cents = max(0, total_amount_cents - fee_cents)
    total_amount = total_amount_cents / 100.0

    payment = (
        Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id)
        .with_for_update()
        .first()
    )
    if payment and payment.status == 'succeeded':
        return True

    if not payment:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=total_amount,
            stripe_payment_intent_id=payment_intent_id,
            status='processing',
            currency=(payment_intent.get('currency') or 'usd').upper(),
            payment_metadata=metadata,
        )
        db.session.add(payment)
    else:
        if payment.status != 'succeeded':
            payment.status = 'processing'
        payment.amount = total_amount
        payment.payment_metadata = metadata

    payment.payment_method_type = pm_type
    payment.funding = funding
    payment.brand = brand
    payment.base_amount_cents = base_amount_cents
    payment.fee_cents = fee_cents
    payment.tax_amount_cents = tax_amount_cents
    payment.final_amount_cents = final_amount_cents
    if metadata.get('payment_method_id'):
        payment.payment_method_id = metadata.get('payment_method_id')

    db.session.flush()
    mark_addon_processing(ba, payment)
    db.session.commit()

    try:
        send_order_processing_email(booking, payment, is_new_order=False)
    except Exception as e:
        current_app.logger.warning(
            'Addon ACH processing email failed booking=%s: %s', booking.id, e
        )
    current_app.logger.info(
        'Addon ACH processing: ba=%s payment=%s booking=%s',
        ba.id,
        payment_intent_id,
        booking.id,
    )
    return True


def handle_addon_payment_succeeded(payment_intent):
    """Card/ACH succeeded: mark addon paid, bump amount_paid, send receipt email."""
    from app.routes import (
        send_booking_confirmation_email,
        _payment_method_type_from_intent,
    )

    metadata = payment_intent.get('metadata') or {}
    if not is_addon_purchase_intent(metadata):
        return False

    ba = find_booking_addon_for_intent(payment_intent, metadata)
    if not ba or not ba.booking:
        current_app.logger.error(
            'Addon succeeded: booking_addon missing for PI %s',
            payment_intent.get('id'),
        )
        return True

    booking = ba.booking
    payment_intent_id = payment_intent['id']

    payment = (
        Payment.query.filter_by(stripe_payment_intent_id=payment_intent_id)
        .with_for_update()
        .first()
    )
    if payment and payment.status == 'succeeded':
        if (ba.payment_status or '') != 'paid':
            mark_addon_paid(ba, payment, base_amount=0)  # already in amount_paid
            ba.payment_status = 'paid'
            ba.payment_id = payment.id
            db.session.commit()
        return True

    total_amount_cents = payment_intent.get('amount', 0) or 0
    base_amount_cents = _parse_int(metadata.get('base_amount'))
    fee_cents = _parse_int(metadata.get('fee')) or 0
    tax_amount_cents = _parse_int(metadata.get('tax_amount'))
    final_amount_cents = _parse_int(metadata.get('final_amount'))
    funding = metadata.get('funding')
    brand = metadata.get('brand')
    pm_type = _payment_method_type_from_intent(payment_intent, metadata)

    if final_amount_cents is not None and abs(final_amount_cents - total_amount_cents) > 1:
        final_amount_cents = total_amount_cents
    if base_amount_cents is not None:
        expected_total = base_amount_cents + fee_cents
        if abs(expected_total - total_amount_cents) > 1:
            base_amount_cents = max(0, total_amount_cents - fee_cents)
    if base_amount_cents is not None:
        base_amount = base_amount_cents / 100.0
    else:
        base_amount = max(0, total_amount_cents - fee_cents) / 100.0
    total_amount = total_amount_cents / 100.0

    prior_status = payment.status if payment else None
    if not payment:
        payment = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=total_amount,
            stripe_payment_intent_id=payment_intent_id,
            status='succeeded',
            paid_at=datetime.utcnow(),
            currency=(payment_intent.get('currency') or 'usd').upper(),
            payment_metadata=metadata,
        )
        db.session.add(payment)
    else:
        payment.status = 'succeeded'
        payment.paid_at = datetime.utcnow()
        payment.amount = total_amount
        payment.currency = (payment_intent.get('currency') or 'usd').upper()
        payment.payment_metadata = metadata
        payment.booking_id = booking.id

    if base_amount_cents is not None:
        payment.base_amount_cents = base_amount_cents
    payment.fee_cents = fee_cents
    if tax_amount_cents is not None:
        payment.tax_amount_cents = tax_amount_cents
    payment.final_amount_cents = (
        final_amount_cents if final_amount_cents is not None else total_amount_cents
    )
    if funding:
        payment.funding = funding
    if brand:
        payment.brand = brand
    payment.payment_method_type = pm_type
    if metadata.get('payment_method_id'):
        payment.payment_method_id = metadata.get('payment_method_id')

    charge_id = extract_stripe_charge_id(payment_intent)
    if charge_id and not payment.stripe_charge_id:
        payment.stripe_charge_id = charge_id

    db.session.flush()

    # Only bump amount_paid when transitioning into succeeded
    if prior_status != 'succeeded':
        mark_addon_paid(ba, payment, base_amount=base_amount)
    else:
        ba.payment_status = 'paid'
        ba.payment_id = payment.id

    db.session.commit()

    total_info = calculate_booking_total(booking)
    is_full = (booking.amount_paid or 0.0) >= total_info['total'] - 0.001
    try:
        send_booking_confirmation_email(booking, is_full, payment=payment)
    except Exception as e:
        current_app.logger.error('Addon receipt email failed: %s', e)

    current_app.logger.info(
        'Addon paid: ba=%s base=%.2f booking=%s',
        ba.id,
        base_amount,
        booking.id,
    )
    return True


def handle_addon_payment_failed(payment_intent):
    metadata = payment_intent.get('metadata') or {}
    if not is_addon_purchase_intent(metadata):
        return False
    ba = find_booking_addon_for_intent(payment_intent, metadata)
    if ba and (ba.payment_status or '') != 'paid':
        mark_addon_failed(ba)
        db.session.commit()
    return True
