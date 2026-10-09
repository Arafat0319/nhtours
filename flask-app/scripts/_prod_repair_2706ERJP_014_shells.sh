#!/bin/bash
# Repair 2706ERJP-014: void Incomplete catch-up Payment shells + cancel Stripe PIs.
# KEEP: pay#61 succeeded Initial, pay#62 processing Installment #1 ACH.
set -euo pipefail
cd /var/www/nhtours/flask-app
source venv/bin/activate
python3 <<'PY'
from datetime import datetime
from pathlib import Path
import os

import stripe

from app import create_app, db
from app.models import Booking, InstallmentPayment, Payment

ORDER = '2706ERJP-014'
KEEP_PAY_IDS = {61, 62}
# Explicit void list from audit (pending catch-up shells)
VOID_PAY_IDS = {63, 64, 66, 68, 69, 70}

for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')

app = create_app()
with app.app_context():
    b = Booking.query.filter_by(order_number=ORDER).first()
    if not b:
        print('booking missing', ORDER)
        raise SystemExit(1)
    print('booking', b.id, b.order_number, 'amount_paid=', b.amount_paid, 'status=', b.status)

    pays = Payment.query.filter_by(booking_id=b.id).order_by(Payment.id).all()
    print('=== BEFORE ===')
    for p in pays:
        st = None
        if p.stripe_payment_intent_id:
            try:
                st = stripe.PaymentIntent.retrieve(p.stripe_payment_intent_id).status
            except Exception as e:
                st = f'err:{e}'
        print(
            f'  pay#{p.id} ${p.amount} local={p.status} stripe={st} '
            f'inst={p.installment_payment_id} pi={p.stripe_payment_intent_id}'
        )

    voided = []
    skipped = []
    for pid in sorted(VOID_PAY_IDS):
        p = Payment.query.get(pid)
        if not p or p.booking_id != b.id:
            skipped.append((pid, 'missing_or_wrong_booking'))
            continue
        if p.id in KEEP_PAY_IDS:
            skipped.append((pid, 'keep_list'))
            continue
        if p.status not in ('pending', 'failed'):
            skipped.append((pid, f'local_status={p.status}'))
            continue
        pi_id = p.stripe_payment_intent_id
        if pi_id:
            pi = stripe.PaymentIntent.retrieve(pi_id)
            st = getattr(pi, 'status', None)
            if st in ('processing', 'succeeded', 'requires_capture'):
                skipped.append((pid, f'stripe={st}_keep'))
                continue
            if st == 'requires_action':
                skipped.append((pid, 'stripe=requires_action_keep'))
                continue
            if st not in ('canceled',):
                if st != 'requires_payment_method':
                    skipped.append((pid, f'stripe={st}_unexpected'))
                    continue
                try:
                    stripe.PaymentIntent.cancel(pi_id)
                    print(f'  cancelled stripe {pi_id} (was {st})')
                except Exception as e:
                    err = str(e).lower()
                    if 'already' not in err and 'canceled' not in err:
                        skipped.append((pid, f'cancel_fail:{e}'))
                        continue
                    print(f'  stripe already canceled {pi_id}')
            else:
                print(f'  stripe already canceled {pi_id}')
        # Clear installment link to this dead PI
        if p.installment_payment_id:
            inst = InstallmentPayment.query.get(p.installment_payment_id)
            if inst and inst.payment_intent_id == pi_id:
                print(f'  clear installment#{inst.id} payment_intent_id')
                inst.payment_intent_id = None
                inst.payment_link = None
        # Also clear any installment pointing at this PI
        for inst in InstallmentPayment.query.filter_by(
            booking_id=b.id, payment_intent_id=pi_id
        ).all():
            print(f'  clear installment#{inst.id} payment_intent_id (by pi)')
            inst.payment_intent_id = None
            inst.payment_link = None

        p.status = 'failed'
        meta = dict(p.payment_metadata or {})
        meta['voided_reason'] = 'empty_shell_cleanup_2706ERJP_014'
        meta['voided_at'] = datetime.utcnow().isoformat() + 'Z'
        meta['hidden_from_admin_history'] = True
        p.payment_metadata = meta
        voided.append(pid)

    # Safety: never touch keep rows
    for kid in KEEP_PAY_IDS:
        k = Payment.query.get(kid)
        if k:
            print(f'KEEP pay#{k.id} status={k.status} (unchanged)')

    db.session.commit()

    print('=== AFTER ===')
    print('voided=', voided)
    print('skipped=', skipped)
    pays2 = Payment.query.filter_by(booking_id=b.id).order_by(Payment.id).all()
    for p in pays2:
        st = None
        if p.stripe_payment_intent_id:
            try:
                st = stripe.PaymentIntent.retrieve(p.stripe_payment_intent_id).status
            except Exception as e:
                st = f'err:{e}'
        print(
            f'  pay#{p.id} ${p.amount} local={p.status} stripe={st} '
            f'hidden={bool((p.payment_metadata or {}).get("hidden_from_admin_history"))}'
        )
    print('amount_paid still', Booking.query.get(b.id).amount_paid)
PY
