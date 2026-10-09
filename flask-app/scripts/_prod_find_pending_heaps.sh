#!/bin/bash
set -euo pipefail
cd /var/www/nhtours/flask-app
source venv/bin/activate
python3 <<'PY'
from app import create_app, db
from app.models import Booking, Payment
from sqlalchemy import func

app = create_app()
with app.app_context():
    q = (
        db.session.query(
            Booking.id,
            Booking.order_number,
            Booking.amount_paid,
            Booking.buyer_email,
            func.count(Payment.id),
        )
        .join(Payment, Payment.booking_id == Booking.id)
        .filter(Payment.status == 'pending')
        .group_by(Booking.id)
        .having(func.count(Payment.id) >= 3)
        .order_by(func.count(Payment.id).desc())
        .limit(20)
    )
    print('=== bookings with >=3 pending payments ===')
    for bid, on, paid, email, n in q.all():
        print(f'  {on} id={bid} amount_paid={paid} pending_n={n} email={email}')
        pays = (
            Payment.query.filter_by(booking_id=bid)
            .order_by(Payment.id)
            .all()
        )
        for p in pays:
            print(
                f'    pay#{p.id} ${p.amount} {p.status} '
                f'{p.brand or p.payment_method_type or "-"} '
                f'pi={p.stripe_payment_intent_id}'
            )
PY
