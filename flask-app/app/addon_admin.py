"""Admin post-booking Add-on purchase helpers."""
from __future__ import annotations

from datetime import datetime

from flask import current_app, url_for

from app import db
from app.models import BookingAddOn, Payment, TripAddOn
from app.payments import booking_addon_unit_price


def booking_addon_line_total(ba):
    qty = int(ba.quantity or 1)
    return round(booking_addon_unit_price(ba) * qty, 2)


def addon_payment_url(ba):
    from app.utils import generate_addon_payment_token

    token = generate_addon_payment_token(ba.id)
    try:
        return url_for(
            'main.pay_booking_addon',
            booking_addon_id=ba.id,
            token=token,
            _external=True,
        )
    except Exception:
        base = (current_app.config.get('BASE_URL') or 'https://nhtours.com').rstrip('/')
        return f'{base}/pay-addon/{ba.id}?token={token}'


def serialize_booking_addon(ba):
    """JSON shape for Manage Order Summary Add-ons."""
    qty = int(ba.quantity or 1)
    price = booking_addon_unit_price(ba)
    subtotal = round(price * qty, 2)
    source = (getattr(ba, 'source', None) or 'booking').strip() or 'booking'
    status = (getattr(ba, 'payment_status', None) or 'paid').strip() or 'paid'
    participant = ba.participant
    return {
        'booking_addon_id': ba.id,
        'id': ba.addon.id if ba.addon else ba.addon_id,
        'name': ba.addon.name if ba.addon else f'Add-on #{ba.addon_id}',
        'price': price,
        'quantity': qty,
        'subtotal': subtotal,
        'participant_id': ba.participant_id,
        'participant_name': participant.name if participant else None,
        'source': source,
        'is_manual': source == 'admin_manual',
        'payment_status': status,
        'payment_id': ba.payment_id,
    }


def create_manual_booking_addon(booking, trip_addon_id, quantity=1, participant_id=None):
    """
    Admin adds an add-on to an existing booking. Starts unpaid.
    Returns (booking_addon, error_message).

    Participant: explicit id if given; else first active participant
    (same fallback as customer signup add-ons).
    """
    if not booking or booking.status == 'cancelled':
        return None, 'Booking is cancelled or missing'
    trip_addon = TripAddOn.query.get(trip_addon_id)
    if not trip_addon or trip_addon.trip_id != booking.trip_id:
        return None, 'Add-on not found on this trip'
    try:
        qty = max(1, int(quantity or 1))
    except (TypeError, ValueError):
        return None, 'Invalid quantity'

    active_participants = [
        p for p in booking.participants
        if (getattr(p, 'status', None) or 'active') != 'withdrawn'
    ]
    resolved_participant_id = None
    if participant_id:
        ok_ids = {p.id for p in active_participants} | {
            p.id for p in booking.participants
        }
        if int(participant_id) not in ok_ids:
            return None, 'Participant not on this booking'
        resolved_participant_id = int(participant_id)
    elif active_participants:
        # Align with signup: hang on first participant when not specified
        resolved_participant_id = active_participants[0].id

    from app.payments import booking_has_processing_ach_payment
    if booking_has_processing_ach_payment(booking.id):
        return None, 'A payment is still processing (ACH). Wait until it completes.'

    ba = BookingAddOn(
        booking_id=booking.id,
        addon_id=trip_addon.id,
        participant_id=resolved_participant_id,
        quantity=qty,
        price_at_booking=float(trip_addon.price or 0),
        source='admin_manual',
        payment_status='unpaid',
    )
    db.session.add(ba)
    db.session.flush()
    return ba, None


def mark_addon_processing(ba, payment):
    ba.payment_status = 'processing'
    if payment:
        ba.payment_id = payment.id
        if payment.stripe_payment_intent_id:
            ba.stripe_payment_intent_id = payment.stripe_payment_intent_id


def mark_addon_paid(ba, payment, *, base_amount):
    """Mark addon paid and bump booking.amount_paid. Caller commits."""
    ba.payment_status = 'paid'
    if payment:
        ba.payment_id = payment.id
        if payment.stripe_payment_intent_id:
            ba.stripe_payment_intent_id = payment.stripe_payment_intent_id
    booking = ba.booking
    if booking:
        booking.amount_paid = round(float(booking.amount_paid or 0) + float(base_amount or 0), 2)
        from app.payments import calculate_booking_total
        total_info = calculate_booking_total(booking)
        if booking.amount_paid >= total_info['total'] - 0.001:
            booking.status = 'fully_paid'
        elif booking.status in ('pending', 'processing') and booking.amount_paid > 0.001:
            booking.status = 'deposit_paid'


def mark_addon_failed(ba):
    if (ba.payment_status or '') != 'paid':
        ba.payment_status = 'failed'


def send_addon_payment_email(ba):
    """Email customer a pay link for a manual unpaid/processing addon. Returns (ok, msg)."""
    from flask import render_template
    from app.utils import send_email_via_ses, _email_brand_logo_url

    booking = ba.booking
    if not booking:
        return False, 'Booking not found'
    email = (booking.buyer_email or '').strip()
    if not email and booking.client:
        email = (booking.client.email or '').strip()
    if not email:
        return False, 'No buyer email on this booking'

    trip_title = booking.trip.title if booking.trip else 'your trip'
    order_label = booking.order_number or f'#{booking.id}'
    amount = booking_addon_line_total(ba)
    pay_url = addon_payment_url(ba)
    name = ba.addon.name if ba.addon else 'Add-on'
    subject = f'Pay for add-on — {name} ({order_label})'
    context = {
        'subject_line': subject,
        'brand_subtitle': 'Add-on payment',
        'customer_name': booking.buyer_first_name or 'Customer',
        'intro_text': (
            f'An add-on was added to your booking for {trip_title} '
            f'(order {order_label}). Please complete payment using the button below.'
        ),
        'highlight_title': 'Amount due',
        'trip_title': trip_title,
        'addon_label': f'{name} × {int(ba.quantity or 1)}',
        'amount': amount,
        'order_number': order_label,
        'payment_link': pay_url,
        'email_logo_url': _email_brand_logo_url(),
        'cta_label': 'Pay now',
        'footer_note': 'If you have already paid, please ignore this email. Thank you.',
    }
    try:
        html = render_template('emails/addon_payment_invite.html', **context)
        text = render_template('emails/addon_payment_invite.txt', **context)
    except Exception as e:
        current_app.logger.error('Addon payment invite template failed: %s', e)
        return False, 'Could not render email'
    sender = current_app.config.get('SENDER_EMAIL') or current_app.config.get(
        'RECIPIENT_EMAIL', 'info@nhtours.com'
    )
    ok, msg = send_email_via_ses(sender, email, subject, html, text)
    return ok, (msg if not ok else f'Sent to {email}')
