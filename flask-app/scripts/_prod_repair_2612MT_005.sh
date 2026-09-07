#!/bin/bash
# Scan + repair 2612MT-005 after deploying code fix is preferred;
# this script can repair ledger alone and list similar stuck rows.
set -e
cd /var/www/nhtours/flask-app
. venv/bin/activate
python3 <<'PY'
from datetime import datetime
from app import create_app, db
from sqlalchemy import text
import stripe

app = create_app()
with app.app_context():
    stripe.api_key = app.config.get('STRIPE_SECRET_KEY')
    from app.models import Booking, Payment, InstallmentPayment
    from app.payments import calculate_booking_total

    print('=== SCAN: pending/processing Payment whose Stripe PI is succeeded ===')
    stuck = []
    rows = Payment.query.filter(Payment.status.in_(('pending', 'processing'))).order_by(Payment.id).all()
    for p in rows:
        if not p.stripe_payment_intent_id:
            continue
        try:
            pi = stripe.PaymentIntent.retrieve(p.stripe_payment_intent_id)
        except Exception as e:
            print('  retrieve fail', p.id, p.stripe_payment_intent_id, e)
            continue
        if pi.status == 'succeeded':
            b = p.booking
            stuck.append((p, b, pi))
            print(
                f"  STUCK pay={p.id} booking={getattr(b,'order_number',None)} "
                f"local={p.status} stripe=succeeded amount={p.amount} pi={p.stripe_payment_intent_id}"
            )
        elif pi.status == 'canceled' and p.status == 'pending':
            print(
                f"  STALE pending+canceled pi pay={p.id} booking={getattr(p.booking,'order_number',None)} "
                f"pi={p.stripe_payment_intent_id}"
            )

    print(f'stuck_succeeded_count={len(stuck)}')

    # Repair 2612MT-005
    print('\n=== REPAIR 2612MT-005 ===')
    b = Booking.query.filter_by(order_number='2612MT-005').first()
    if not b:
        print('booking missing')
        raise SystemExit(1)
    pi_ok = 'pi_3UCQ302V9wZ5aq3l0dtSzA4q'
    pi_bad = 'pi_3UCKKA2V9wZ5aq3l0lfHGBUD'
    pay_ok = Payment.query.filter_by(stripe_payment_intent_id=pi_ok).first()
    pay_bad = Payment.query.filter_by(stripe_payment_intent_id=pi_bad).first()
    inst15 = InstallmentPayment.query.get(15)
    inst20 = InstallmentPayment.query.get(20)
    if not pay_ok or not inst15 or not inst20:
        print('missing rows', pay_ok, inst15, inst20)
        raise SystemExit(1)

    pi = stripe.PaymentIntent.retrieve(pi_ok)
    assert pi.status == 'succeeded'
    paid_at = datetime.utcfromtimestamp(pi.created) if not getattr(pi, 'charges', None) else datetime.utcnow()
    # prefer charge created
    try:
        ch = pi.latest_charge
        if isinstance(ch, str):
            ch = stripe.Charge.retrieve(ch)
        if ch and getattr(ch, 'created', None):
            paid_at = datetime.utcfromtimestamp(ch.created)
    except Exception:
        pass

    before = {
        'amount_paid': b.amount_paid,
        'pay_ok': pay_ok.status,
        'pay_bad': pay_bad.status if pay_bad else None,
        'i15': (inst15.status, inst15.payment_intent_id),
        'i20': (inst20.status, inst20.payment_intent_id),
    }
    print('before', before)

    # Apply repair
    pay_ok.status = 'succeeded'
    pay_ok.paid_at = paid_at
    pay_ok.amount = 1270.0
    pay_ok.base_amount_cents = 127000
    pay_ok.final_amount_cents = 127000
    meta = pay_ok.payment_metadata if isinstance(pay_ok.payment_metadata, dict) else {}
    # keep / set catch_up metadata
    if not meta.get('catch_up_ids'):
        meta = dict(meta or {})
        meta.update({
            'payment_step': 'catch_up',
            'catch_up_ids': '15,20',
            'catch_up_breakdown': 'Installment #1 $580.00 + Installment #1 $690.00',
            'base_amount': '127000',
        })
        pay_ok.payment_metadata = meta

    if pay_bad and pay_bad.status in ('pending', 'processing', 'failed'):
        pay_bad.status = 'canceled'
        meta_bad = dict(pay_bad.payment_metadata or {}) if isinstance(pay_bad.payment_metadata, dict) else {}
        meta_bad['voided_attempt'] = True
        meta_bad['hidden_from_admin_history'] = True
        pay_bad.payment_metadata = meta_bad

    for inst in (inst15, inst20):
        inst.status = 'paid'
        inst.paid_at = paid_at
    inst15.payment_intent_id = pi_ok
    inst20.payment_intent_id = None

    # amount_paid: was 200; add 1270 if not already included
    paid = float(b.amount_paid or 0)
    if paid < 1470 - 0.01:
        # if still at ~200, add 1270
        if paid < 250:
            b.amount_paid = round(paid + 1270.0, 2)
        else:
            b.amount_paid = 1470.0

    # clear auto pay block error if any
    if hasattr(b, 'auto_pay_last_error'):
        b.auto_pay_last_error = None

    db.session.commit()

    db.session.refresh(b)
    db.session.refresh(pay_ok)
    db.session.refresh(inst15)
    db.session.refresh(inst20)
    totals = calculate_booking_total(b)
    print('after', {
        'amount_paid': b.amount_paid,
        'pay_ok': pay_ok.status,
        'pay_bad': pay_bad.status if pay_bad else None,
        'i15': (inst15.status, inst15.payment_intent_id),
        'i20': (inst20.status, inst20.payment_intent_id),
        'due': totals.get('amount_due'),
        'total': totals.get('total'),
    })
    print('REPAIR_OK')
PY
