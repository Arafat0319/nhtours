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
from app.models import Booking, BookingAddOn, Payment, TripAddOn

for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

app = create_app()
with app.app_context():
    for pid in (80, 129, 130, 131, 132):
        p = Payment.query.get(pid)
        print('=' * 60)
        print('pay', pid, 'local', p.status if p else None)
        if not p:
            continue
        print(' amount', p.amount, 'base_cents', p.base_amount_cents, 'final', p.final_amount_cents, 'fee', p.fee_cents)
        print(' paid_at', p.paid_at, 'created', p.created_at)
        print(' meta', json.dumps(p.payment_metadata or {}, ensure_ascii=False))
        pi_id = p.stripe_payment_intent_id
        if pi_id and not str(pi_id).startswith('free_'):
            pi = stripe.PaymentIntent.retrieve(pi_id, expand=['latest_charge', 'payment_method'])
            ch = pi.latest_charge
            if isinstance(ch, str):
                ch = stripe.Charge.retrieve(ch)
            print(' STRIPE', {
                'id': pi.id,
                'status': pi.status,
                'amount': pi.amount,
                'amount_received': pi.amount_received,
                'created': datetime.utcfromtimestamp(pi.created).isoformat()+'Z',
                'pm': getattr(pi.payment_method, 'id', pi.payment_method),
                'charge': None if not ch else {
                    'id': ch.id,
                    'status': ch.status,
                    'paid': ch.paid,
                    'amount': ch.amount,
                    'refunded': getattr(ch, 'refunded', None),
                    'created': datetime.utcfromtimestamp(ch.created).isoformat()+'Z',
                },
            })

    print('\n=== Addons with catalog names ===')
    for ba in BookingAddOn.query.filter_by(booking_id=57).all():
        ta = TripAddOn.query.get(ba.addon_id) if ba.addon_id else None
        print({
            'ba_id': ba.id,
            'catalog': getattr(ta, 'name', None),
            'price': ba.price_at_booking,
            'source': ba.source,
            'payment_status': ba.payment_status,
            'payment_id': ba.payment_id,
            'pi': ba.stripe_payment_intent_id,
        })

    b = Booking.query.get(57)
    print('\n booking discount fields if any')
    for c in b.__table__.columns:
        if 'discount' in c.name or 'promo' in c.name:
            print(c.name, getattr(b, c.name))
PY
