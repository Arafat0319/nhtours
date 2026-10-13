#!/bin/bash
# Repair 2612MT-027: Stripe-succeeded pay#131 was wrongly local failed.
# amount_paid already 285 — do NOT bump again.
set -euo pipefail
cd /var/www/nhtours/flask-app
source venv/bin/activate
python3 <<'PY'
from datetime import datetime
from pathlib import Path
import os

import stripe

from app import create_app, db
from app.models import Booking, BookingAddOn, Payment
from app.payments import (
    computed_booking_amount_paid,
    extract_stripe_charge_id,
    reconcile_booking_ledger,
)

for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

ORDER = '2612MT-027'
PAY_ID = 131
KEEP_PI = 'pi_3UPv292V9wZ5aq3l0qxz6GZU'
BA_ID = 39

app = create_app()
with app.app_context():
    b = Booking.query.filter_by(order_number=ORDER).first()
    p = Payment.query.get(PAY_ID)
    ba = BookingAddOn.query.get(BA_ID)
    if not b or not p or not ba:
        print('missing', bool(b), bool(p), bool(ba))
        raise SystemExit(1)
    if p.booking_id != b.id or ba.booking_id != b.id:
        print('booking mismatch')
        raise SystemExit(2)
    if p.stripe_payment_intent_id != KEEP_PI:
        print('PI mismatch', p.stripe_payment_intent_id)
        raise SystemExit(3)

    pi = stripe.PaymentIntent.retrieve(KEEP_PI)
    print('stripe', pi.status, 'amount_received', pi.amount_received)
    if pi.status != 'succeeded':
        print('Stripe not succeeded; abort')
        raise SystemExit(4)

    before = {
        'amount_paid': b.amount_paid,
        'pay_status': p.status,
        'ba_status': ba.payment_status,
        'ba_payment_id': ba.payment_id,
        'ba_pi': ba.stripe_payment_intent_id,
        'computed': computed_booking_amount_paid(b),
    }
    print('before', before)

    paid_at = p.paid_at or datetime.utcnow()
    try:
        ch = pi.latest_charge
        if isinstance(ch, str):
            ch = stripe.Charge.retrieve(ch)
        if ch and getattr(ch, 'created', None):
            paid_at = datetime.utcfromtimestamp(ch.created)
        if ch and getattr(ch, 'id', None) and not p.stripe_charge_id:
            p.stripe_charge_id = ch.id
    except Exception as e:
        print('charge enrich warn', e)

    p.status = 'succeeded'
    p.paid_at = paid_at
    if not p.stripe_charge_id:
        cid = extract_stripe_charge_id(pi)
        if cid:
            p.stripe_charge_id = cid

    ba.payment_status = 'paid'
    ba.payment_id = p.id
    ba.stripe_payment_intent_id = KEEP_PI
    # amount_paid already includes the $285 — leave unchanged
    print('amount_paid left at', b.amount_paid)

    db.session.commit()

    after = {
        'amount_paid': b.amount_paid,
        'pay_status': Payment.query.get(PAY_ID).status,
        'ba_status': BookingAddOn.query.get(BA_ID).payment_status,
        'ba_payment_id': BookingAddOn.query.get(BA_ID).payment_id,
        'ba_pi': BookingAddOn.query.get(BA_ID).stripe_payment_intent_id,
        'computed': computed_booking_amount_paid(Booking.query.get(b.id)),
        'reconcile': reconcile_booking_ledger(Booking.query.get(b.id), check_stripe=False),
    }
    print('after', after)
    if not after['reconcile'].get('ok'):
        print('WARNING reconcile still not ok', after['reconcile'])
        raise SystemExit(5)
    print('OK')
PY
