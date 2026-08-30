"""
Auto Pay helpers: Stripe Customer / PaymentMethod, enable/disable, due-day card charge.
"""

from __future__ import annotations

from datetime import datetime

import stripe
from flask import current_app, url_for

from app import db
from app.models import Booking, InstallmentPayment, Payment
from app.utils import pacific_today


def _stripe_ready():
    key = current_app.config.get('STRIPE_SECRET_KEY')
    if not key:
        return False
    stripe.api_key = key
    return True


def ensure_stripe_customer_for_booking(booking, *, email=None, name=None):
    """
    Return Stripe Customer id for booking; create if missing.
    Does not commit.
    """
    if not booking:
        return None
    if booking.stripe_customer_id:
        return booking.stripe_customer_id
    if not _stripe_ready():
        return None

    email = (email or booking.buyer_email or '').strip() or None
    name = (name or booking.buyer_name or '').strip() or None
    try:
        customer = stripe.Customer.create(
            email=email,
            name=name,
            metadata={
                'booking_id': str(booking.id),
                'order_number': str(booking.order_number or ''),
            },
        )
        booking.stripe_customer_id = customer.id
        return customer.id
    except Exception as e:
        current_app.logger.error(
            'Auto Pay: create Customer failed booking=%s: %s', booking.id, e
        )
        return None


def ensure_stripe_customer_from_buyer(*, email, name=None, metadata=None):
    """Create a Stripe Customer before Booking exists (PendingBooking / PI create)."""
    if not _stripe_ready():
        return None
    email = (email or '').strip() or None
    if not email:
        return None
    try:
        customer = stripe.Customer.create(
            email=email,
            name=(name or '').strip() or None,
            metadata=metadata or {},
        )
        return customer.id
    except Exception as e:
        current_app.logger.error('Auto Pay: create Customer (pre-booking) failed: %s', e)
        return None


def attach_payment_method_to_customer(customer_id, payment_method_id):
    """Attach PM to Customer if not already; return True on success."""
    if not customer_id or not payment_method_id or not _stripe_ready():
        return False
    try:
        pm = stripe.PaymentMethod.retrieve(payment_method_id)
        existing = getattr(pm, 'customer', None)
        if existing and existing != customer_id:
            # Already on another customer — cannot re-attach; leave as-is
            current_app.logger.warning(
                'Auto Pay: PM %s already on customer %s (wanted %s)',
                payment_method_id,
                existing,
                customer_id,
            )
            return False
        if not existing:
            stripe.PaymentMethod.attach(payment_method_id, customer=customer_id)
        return True
    except Exception as e:
        current_app.logger.error(
            'Auto Pay: attach PM %s to %s failed: %s',
            payment_method_id,
            customer_id,
            e,
        )
        return False


def list_customer_payment_methods(customer_id):
    """Return list of dicts: id, type, brand, last4, label."""
    if not customer_id or not _stripe_ready():
        return []
    methods = []
    try:
        for pm_type in ('card', 'us_bank_account'):
            resp = stripe.PaymentMethod.list(customer=customer_id, type=pm_type, limit=20)
            for pm in (resp.data or []):
                methods.append(_pm_display(pm))
    except Exception as e:
        current_app.logger.error('Auto Pay: list PMs failed customer=%s: %s', customer_id, e)
    return methods


def _pm_display(pm):
    pm_id = getattr(pm, 'id', None) or ''
    pm_type = getattr(pm, 'type', None) or 'unknown'
    brand = ''
    last4 = ''
    if pm_type == 'card' and getattr(pm, 'card', None):
        brand = (pm.card.get('brand') if isinstance(pm.card, dict) else getattr(pm.card, 'brand', '')) or ''
        last4 = (pm.card.get('last4') if isinstance(pm.card, dict) else getattr(pm.card, 'last4', '')) or ''
        label = f"{brand.title() if brand else 'Card'} ···· {last4}".strip()
    elif pm_type == 'us_bank_account' and getattr(pm, 'us_bank_account', None):
        bank = pm.us_bank_account
        brand = (bank.get('bank_name') if isinstance(bank, dict) else getattr(bank, 'bank_name', '')) or 'Bank'
        last4 = (bank.get('last4') if isinstance(bank, dict) else getattr(bank, 'last4', '')) or ''
        label = f"{brand} ···· {last4}".strip()
    else:
        label = pm_type
    return {
        'id': pm_id,
        'type': pm_type,
        'brand': brand,
        'last4': last4,
        'label': label,
    }


def payment_method_id_from_intent(payment_intent):
    """Extract PM id from Stripe PI dict/object."""
    if not payment_intent:
        return None
    if isinstance(payment_intent, dict):
        pm = payment_intent.get('payment_method')
    else:
        pm = getattr(payment_intent, 'payment_method', None)
    if isinstance(pm, str):
        return pm
    if pm is not None and hasattr(pm, 'id'):
        return pm.id
    return None


def sync_auto_pay_after_successful_payment(booking, payment, payment_intent=None):
    """
    After a succeeded payment: ensure Customer + attach PM.
    If booking.auto_pay_opt_in and not yet enabled → enable with this PM.
    Does not commit.
    """
    if not booking or not payment:
        return
    # Only meaningful for installment / deposit plans
    has_installments = (
        InstallmentPayment.query.filter_by(booking_id=booking.id).count() > 0
    )
    if not has_installments and not booking.auto_pay_opt_in and not booking.auto_pay_enabled:
        return

    pm_id = (
        getattr(payment, 'payment_method_id', None)
        or payment_method_id_from_intent(payment_intent)
        or ((payment.payment_metadata or {}).get('payment_method_id') if payment.payment_metadata else None)
    )
    customer_id = booking.stripe_customer_id or getattr(payment, 'stripe_customer_id', None)
    if not customer_id and isinstance(payment_intent, dict):
        customer_id = payment_intent.get('customer')
    elif payment_intent is not None and not isinstance(payment_intent, dict):
        customer_id = getattr(payment_intent, 'customer', None) or customer_id

    if not customer_id:
        customer_id = ensure_stripe_customer_for_booking(booking)

    if customer_id and pm_id:
        if attach_payment_method_to_customer(customer_id, pm_id):
            booking.stripe_customer_id = customer_id
            payment.stripe_customer_id = payment.stripe_customer_id or customer_id
            payment.payment_method_id = payment.payment_method_id or pm_id

    # First-time enable from signup checkbox
    if booking.auto_pay_opt_in and not booking.auto_pay_enabled and pm_id and booking.stripe_customer_id:
        enable_auto_pay(booking, pm_id, source='signup')


def enable_auto_pay(booking, payment_method_id, *, source='customer'):
    """Enable Auto Pay with given PM. Does not commit. Returns (ok, error_message)."""
    if not booking:
        return False, 'Booking not found'
    if booking.status == 'cancelled':
        return False, 'Booking is cancelled'
    if not payment_method_id:
        return False, 'Select a payment method'
    customer_id = booking.stripe_customer_id or ensure_stripe_customer_for_booking(booking)
    # Local visual / fixture PMs — skip Stripe attach (not a real PaymentMethod).
    is_dummy_pm = str(payment_method_id).startswith('pm_dummy_')
    if not is_dummy_pm:
        if not customer_id:
            return False, 'Could not create payment profile'
        if not attach_payment_method_to_customer(customer_id, payment_method_id):
            return False, 'Could not save payment method'
    elif not customer_id:
        customer_id = 'cus_dummy_local'
    booking.stripe_customer_id = customer_id
    booking.auto_pay_payment_method_id = payment_method_id
    booking.auto_pay_enabled = True
    booking.auto_pay_opt_in = True
    booking.auto_pay_enabled_at = datetime.utcnow()
    booking.auto_pay_disabled_at = None
    booking.auto_pay_last_error = None
    current_app.logger.info(
        'Auto Pay enabled booking=%s pm=%s source=%s',
        booking.id,
        payment_method_id,
        source,
    )
    return True, None


def disable_auto_pay(booking, *, source='customer'):
    """Turn off Auto Pay. Does not commit."""
    if not booking:
        return False, 'Booking not found'
    booking.auto_pay_enabled = False
    booking.auto_pay_disabled_at = datetime.utcnow()
    # Keep payment_method_id / customer for re-enable
    current_app.logger.info('Auto Pay disabled booking=%s source=%s', booking.id, source)
    return True, None


def auto_pay_manage_url(booking):
    from app.utils import generate_auto_pay_token

    token = generate_auto_pay_token(booking.id)
    try:
        return url_for('main.manage_auto_pay', booking_id=booking.id, token=token, _external=True)
    except Exception:
        base = (current_app.config.get('BASE_URL') or 'https://nhtours.com').rstrip('/')
        return f'{base}/booking/{booking.id}/auto-pay?token={token}'


def payment_methods_for_booking(booking):
    """
    Stripe Customer PMs for this booking, plus any stored booking.auto_pay_payment_method_id
    not already in the list (e.g. local dummy / orphaned id).
    """
    methods = list_customer_payment_methods(getattr(booking, 'stripe_customer_id', None))
    stored = (getattr(booking, 'auto_pay_payment_method_id', None) or '').strip()
    if stored and not any(m.get('id') == stored for m in methods):
        if stored.startswith('pm_dummy_'):
            label = 'Demo card ···· 4242'
            pm_type = 'card'
        else:
            label = f'Saved method ({stored[:18]}…)' if len(stored) > 18 else f'Saved method ({stored})'
            pm_type = 'unknown'
        methods.insert(0, {
            'id': stored,
            'type': pm_type,
            'brand': '',
            'last4': '',
            'label': label,
        })
    return methods


def send_auto_pay_invite_email(booking):
    """Email customer the Auto Pay manage/enable link. Returns (ok, message)."""
    from flask import render_template
    from app.utils import send_email_via_ses

    if not booking:
        return False, 'Booking not found'
    email = (booking.buyer_email or '').strip()
    if not email and booking.client:
        email = (booking.client.email or '').strip()
    if not email:
        return False, 'No buyer email on this booking'

    trip_title = booking.trip.title if booking.trip else 'your trip'
    order_label = booking.order_number or f'#{booking.id}'
    auto_pay_url = auto_pay_manage_url(booking)
    customer_name = booking.buyer_first_name or 'Customer'
    subject = f'Enable Auto Pay — {trip_title} ({order_label})'
    context = {
        'customer_name': customer_name,
        'trip_title': trip_title,
        'order_number': order_label,
        'auto_pay_url': auto_pay_url,
        'subject_line': subject,
    }
    try:
        html_body = render_template('emails/auto_pay_invite.html', **context)
        text_body = render_template('emails/auto_pay_invite.txt', **context)
    except Exception as e:
        current_app.logger.error('Auto Pay invite template failed: %s', e)
        return False, 'Could not render email'

    sender = current_app.config.get('SENDER_EMAIL') or current_app.config.get(
        'RECIPIENT_EMAIL', 'info@nhtours.com'
    )
    ok, msg = send_email_via_ses(sender, email, subject, html_body, text_body)
    if ok:
        current_app.logger.info(
            'Auto Pay invite emailed booking=%s to=%s', booking.id, email
        )
    return ok, msg if not ok else f'Sent to {email}'


def booking_has_installment_plan(booking):
    if not booking:
        return False
    return (
        InstallmentPayment.query.filter(
            InstallmentPayment.booking_id == booking.id,
            InstallmentPayment.status != 'cancelled',
        ).count()
        > 0
    )


def find_due_auto_pay_installments(today=None):
    """
    Unpaid installments due today (or earlier) on Auto Pay–enabled bookings.
    One row per booking: earliest unpaid due date (anchor for catch-up).
    """
    today = today or pacific_today()
    rows = (
        InstallmentPayment.query.join(Booking, InstallmentPayment.booking_id == Booking.id)
        .filter(
            Booking.auto_pay_enabled.is_(True),
            Booking.status != 'cancelled',
            InstallmentPayment.status.in_(('pending', 'overdue')),
            InstallmentPayment.due_date <= today,
            Booking.auto_pay_payment_method_id.isnot(None),
            Booking.stripe_customer_id.isnot(None),
        )
        .order_by(InstallmentPayment.booking_id, InstallmentPayment.due_date.asc())
        .all()
    )
    # Deduplicate by booking: first (earliest due) unpaid
    seen = set()
    out = []
    for inst in rows:
        if inst.booking_id in seen:
            continue
        seen.add(inst.booking_id)
        out.append(inst)
    return out


def charge_installment_via_auto_pay(installment, *, card_only=True):
    """
    Off-session charge for catch-up amount on due day (Card first).
    Returns (ok, detail). Settles ledger via handle_payment_intent_succeeded when succeeded.
    """
    from app.payments import (
        booking_has_processing_ach_payment,
        calculate_booking_total,
        catch_up_amount_cents,
        catch_up_metadata_fields,
        catch_up_summary_items,
        installment_has_processing_ach,
        payment_covers_installment,
        _normalize_metadata,
    )

    booking = installment.booking
    if not booking or not booking.auto_pay_enabled:
        return False, 'auto_pay_disabled'
    if not booking.auto_pay_payment_method_id or not booking.stripe_customer_id:
        return False, 'missing_payment_method'
    if installment_has_processing_ach(installment) or booking_has_processing_ach_payment(booking.id):
        return False, 'ach_processing'

    # 客户可能已打开付款链接留下 pending Payment / PI — 避免双扣
    open_pay = (
        Payment.query.filter(
            Payment.booking_id == booking.id,
            Payment.status.in_(('pending', 'processing')),
        )
        .order_by(Payment.id.desc())
        .all()
    )
    for pay in open_pay:
        if payment_covers_installment(pay, installment):
            return False, 'open_payment_in_progress'
    try:
        due = float(calculate_booking_total(booking).get('amount_due') or 0)
    except Exception:
        due = 1.0
    if due <= 0.001:
        return False, 'already_settled'

    summary_items = catch_up_summary_items(installment)
    base_cents = catch_up_amount_cents(installment)
    if base_cents <= 0:
        return False, 'zero_amount'

    pm_id = booking.auto_pay_payment_method_id
    if card_only and _stripe_ready():
        try:
            pm = stripe.PaymentMethod.retrieve(pm_id)
            if getattr(pm, 'type', None) == 'us_bank_account':
                return False, 'ach_deferred'
        except Exception:
            pass

    catch_meta = catch_up_metadata_fields(installment, summary_items=summary_items)
    metadata = {
        'payment_flow': 'auto_pay',
        'payment_plan': 'installment',
        'booking_id': str(booking.id),
        'installment_id': str(installment.id),
        'auto_pay': '1',
        'base_amount': str(base_cents),
        'payment_method_id': pm_id,
        **{k: str(v) for k, v in catch_meta.items() if v is not None},
    }

    if not _stripe_ready():
        return False, 'stripe_not_configured'

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(base_cents),
            currency='usd',
            customer=booking.stripe_customer_id,
            payment_method=pm_id,
            off_session=True,
            confirm=True,
            payment_method_types=['card'],
            metadata=_normalize_metadata(metadata),
            error_on_requires_action=True,
        )
    except stripe.error.CardError as e:
        err = getattr(e, 'user_message', None) or str(e)
        booking.auto_pay_last_error = (err or 'card_error')[:500]
        current_app.logger.warning(
            'Auto Pay card decline booking=%s installment=%s: %s',
            booking.id,
            installment.id,
            err,
        )
        return False, err
    except Exception as e:
        booking.auto_pay_last_error = str(e)[:500]
        current_app.logger.error(
            'Auto Pay charge failed booking=%s installment=%s: %s',
            booking.id,
            installment.id,
            e,
            exc_info=True,
        )
        return False, str(e)

    status = getattr(intent, 'status', None)
    installment.payment_intent_id = intent.id
    booking.auto_pay_last_charge_at = datetime.utcnow()
    booking.auto_pay_last_error = None
    db.session.flush()

    if status == 'succeeded':
        from app.routes import _stripe_intent_as_dict, handle_payment_intent_succeeded

        try:
            handle_payment_intent_succeeded(_stripe_intent_as_dict(intent))
        except Exception as e:
            current_app.logger.error(
                'Auto Pay: handle_payment_intent_succeeded failed pi=%s: %s',
                intent.id,
                e,
                exc_info=True,
            )
            return False, f'settle_failed:{e}'
        return True, intent.id

    return False, f'status_{status}'


def notify_admin_auto_pay_failure(booking, installment, error_detail):
    """Email admin when Auto Pay charge fails (branded admin template)."""
    from flask import render_template
    from app.utils import send_email_via_ses, _email_brand_logo_url
    from app.payments import installment_display_label

    recipient = current_app.config.get('RECIPIENT_EMAIL') or 'info@nhtours.com'
    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'nhtours-noreply@nhtours.com'
    )
    order_number = booking.order_number or booking.id
    subject = f'[NH Tours] Auto Pay failed — {order_number}'
    trip_title = booking.trip.title if booking.trip else 'Trip'
    manage_url = None
    if booking.trip_id:
        try:
            manage_url = url_for('admin.manage_trip', id=booking.trip_id, _external=True)
        except Exception:
            base = (current_app.config.get('BASE_URL') or 'https://nhtours.com').rstrip('/')
            manage_url = f'{base}/admin/trips/{booking.trip_id}/manage'

    due_date_label = (
        installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'
    )
    customer_email = (booking.buyer_email or '').strip() or 'n/a'
    context = {
        'subject_line': subject,
        'brand_subtitle': 'Auto Pay failed',
        'order_number': order_number,
        'customer_name': booking.buyer_name or 'Customer',
        'customer_email': customer_email,
        'trip_title': trip_title,
        'installment_label': installment_display_label(installment),
        'due_date_label': due_date_label,
        'amount': float(installment.amount or 0),
        'error_detail': error_detail or 'Unknown error',
        'manage_url': manage_url,
        'email_logo_url': _email_brand_logo_url(),
    }
    html = render_template('emails/auto_pay_admin_failure_notify.html', **context)
    text = render_template('emails/auto_pay_admin_failure_notify.txt', **context)
    send_email_via_ses(sender, recipient, subject, html, text)
