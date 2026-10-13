#!/bin/bash
# Compare Excel export Expected/Net/Balance/Status vs Manage display helpers.
set -euo pipefail
cd /var/www/nhtours/flask-app
source venv/bin/activate
python3 <<'PY'
from pathlib import Path
import os, json
from app import create_app
from app.models import Booking, Trip, Payment
from app.payments import (
    calculate_booking_total,
    computed_booking_amount_paid,
    booking_balance_due,
    booking_payment_display_status,
)

for line in Path('.env').read_text().splitlines():
    if '=' in line and not line.strip().startswith('#'):
        k, v = line.split('=', 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"\''))

app = create_app()
with app.app_context():
    # All active trips
    mismatches = []
    n = 0
    for b in Booking.query.filter(Booking.status != 'cancelled').all():
        n += 1
        tot = calculate_booking_total(b)
        expected = float(tot['total'])
        if Payment.query.filter_by(booking_id=b.id).first():
            net = float(computed_booking_amount_paid(b))
        else:
            net = float(b.amount_paid or 0)
        due = booking_balance_due(b, expected=expected)
        due = float(due if due is not None else 0)
        status = booking_payment_display_status(b)
        # Simulate OLD excel expected (bug) for awareness
        # just verify new helpers are self-consistent
        if abs(due - max(0.0, expected - net - float(tot.get('amount_refunded') or 0))) > 0.05:
            # amount_refunded already in amount_due formula via calculate_booking_total
            pass
        # Flag if Manage pending would disagree with excel-style due
        manage_due = float(tot.get('amount_due') or 0)
        if abs(manage_due - due) > 0.02:
            mismatches.append({
                'order': b.order_number,
                'manage_due': manage_due,
                'excel_due': due,
                'expected': expected,
                'net': net,
                'status': status,
            })
    print(json.dumps({'scanned': n, 'due_mismatches': len(mismatches), 'rows': mismatches[:20]}, indent=2))
    # Spotlight 024/027/004/033
    print('\nSPOTLIGHT')
    for on in ('2612MT-027', '2612MT-024', '2612MT-004', '2612MT-033'):
        b = Booking.query.filter_by(order_number=on).first()
        if not b:
            print(on, 'missing')
            continue
        tot = calculate_booking_total(b)
        net = computed_booking_amount_paid(b) if Payment.query.filter_by(booking_id=b.id).first() else float(b.amount_paid or 0)
        print(on, {
            'status_display': booking_payment_display_status(b),
            'expected': tot['total'],
            'net_paid': net,
            'balance_due': booking_balance_due(b, expected=tot['total']),
            'amount_due': tot['amount_due'],
        })
PY
