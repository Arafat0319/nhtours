#!/bin/bash
set -euo pipefail
cd /var/www/nhtours/flask-app
source venv/bin/activate
python3 <<'PY'
from pathlib import Path
import json
import os
from datetime import datetime

import stripe

from app import create_app, db
from app.models import (
    Booking,
    BookingAddOn,
    BookingPackage,
    BookingParticipant,
    InstallmentPayment,
    Payment,
    TripPackage,
)
from app.payments import (
    booking_balance_due,
    calculate_booking_total,
    payment_base_amount,
    payment_refunded_clamped,
)

for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

ORDER = '2612MT-027'

app = create_app()
with app.app_context():
    b = Booking.query.filter_by(order_number=ORDER).first()
    if not b:
        print('NOT FOUND')
        raise SystemExit(1)

    print('=== BOOKING ===')
    print(json.dumps({
        'id': b.id,
        'order_number': b.order_number,
        'status': b.status,
        'buyer': f'{b.buyer_first_name} {b.buyer_last_name}',
        'email': b.buyer_email,
        'phone': b.buyer_phone,
        'created_at': str(b.created_at),
        'amount_paid': b.amount_paid,
        'discount_amount': getattr(b, 'discount_amount', None),
        'discount_code': getattr(b, 'discount_code', None),
    }, indent=2, ensure_ascii=False, default=str))

    try:
        tot = calculate_booking_total(b)
        bal = booking_balance_due(b)
        print('\n=== calculate_booking_total / balance ===')
        print(json.dumps({'total': tot, 'balance': bal}, indent=2, default=str))
    except Exception as e:
        print('total err', e)

    print('\n=== PACKAGES ===')
    for bp in BookingPackage.query.filter_by(booking_id=b.id).all():
        tp = db.session.get(TripPackage, bp.package_id)
        print(json.dumps({
            'bp_id': bp.id,
            'name': getattr(tp, 'name', None),
            'unit_price': bp.unit_price,
            'qty': bp.quantity,
            'plan': bp.payment_plan_type,
            'status': bp.status,
            'amount_paid': bp.amount_paid,
        }, ensure_ascii=False))

    print('\n=== ADDONS ===')
    for ba in BookingAddOn.query.filter_by(booking_id=b.id).all():
        print(json.dumps({c.name: getattr(ba, c.name) for c in ba.__table__.columns}, ensure_ascii=False, default=str))

    print('\n=== PARTICIPANTS ===')
    for pax in BookingParticipant.query.filter_by(booking_id=b.id).all():
        print(pax.id, pax.first_name, pax.last_name, getattr(pax, 'status', None))

    print('\n=== INSTALLMENTS ===')
    insts = InstallmentPayment.query.filter_by(booking_id=b.id).all()
    print('(none)' if not insts else '')
    for i in insts:
        print(i.id, i.installment_number, i.amount, i.due_date, i.status)

    print('\n=== PAYMENTS ===')
    net = 0.0
    for p in Payment.query.filter_by(booking_id=b.id).order_by(Payment.id).all():
        base = payment_base_amount(p)
        ref = payment_refunded_clamped(p)
        contrib = 0.0
        if p.status in ('succeeded', 'partially_refunded', 'refunded'):
            contrib = max(0.0, base - ref)
            net += contrib
        st = None
        if p.stripe_payment_intent_id and not str(p.stripe_payment_intent_id).startswith('free_'):
            try:
                pi = stripe.PaymentIntent.retrieve(p.stripe_payment_intent_id)
                st = pi.status
            except Exception as e:
                st = f'err:{e}'
        meta = dict(p.payment_metadata or {})
        print(json.dumps({
            'pay_id': p.id,
            'amount': p.amount,
            'base': base,
            'refunded': ref,
            'contrib_to_paid': contrib,
            'local': p.status,
            'stripe': st,
            'step': meta.get('payment_step') or meta.get('payment_type'),
            'addon': meta.get('booking_addon_id') or meta.get('addon_name'),
            'paid_at': str(p.paid_at),
            'created_at': str(p.created_at),
            'pi': p.stripe_payment_intent_id,
            'brand': p.brand or p.payment_method_type,
            'base_cents': p.base_amount_cents,
            'final_cents': p.final_amount_cents,
            'fee_cents': p.fee_cents,
        }, ensure_ascii=False))

    print('\n=== LEDGER CHECK ===')
    ap = round(float(b.amount_paid or 0), 2)
    net = round(net, 2)
    print(f'amount_paid={ap}')
    print(f'sum(succeeded net base)={net}')
    print(f'GAP={round(ap - net, 2)}  (positive => amount_paid higher than payment rows)')

    # booking_data-ish columns if any
    for attr in ('notes', 'admin_notes', 'booking_metadata', 'metadata'):
        if hasattr(b, attr):
            print(attr, getattr(b, attr))
PY
