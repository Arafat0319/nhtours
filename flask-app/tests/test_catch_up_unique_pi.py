"""Catch-up covering multiple installment rows must not violate unique PI index."""
from datetime import date, datetime

from app import db
from app.models import (
    Booking,
    BookingPackage,
    Client,
    InstallmentPayment,
    Payment,
    Trip,
    TripPackage,
)
from app.routes import handle_payment_intent_succeeded


def test_catch_up_two_package_rows_unique_pi(app):
    with app.app_context():
        trip = Trip.query.first()
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        if not trip or not pkg:
            return
        client = Client.query.filter_by(email='catchup-unique-pi@example.com').first()
        if not client:
            client = Client(name='Catchup QA', email='catchup-unique-pi@example.com')
            db.session.add(client)
            db.session.flush()

        old = Booking.query.filter_by(order_number='2609QA-CATCHUP').first()
        if old:
            Payment.query.filter_by(booking_id=old.id).delete()
            InstallmentPayment.query.filter_by(booking_id=old.id).delete()
            BookingPackage.query.filter_by(booking_id=old.id).delete()
            db.session.delete(old)
            db.session.commit()

        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            order_number='2609QA-CATCHUP',
            status='deposit_paid',
            amount_paid=200.0,
            buyer_email='catchup-unique-pi@example.com',
            buyer_first_name='Catch',
            buyer_last_name='Up',
            passenger_count=2,
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(
            BookingPackage(
                booking_id=booking.id,
                package_id=pkg.id,
                quantity=1,
                payment_plan_type='deposit_installment',
                amount_paid=200.0,
                status='deposit_paid',
                unit_price=float(pkg.price or 2000),
            )
        )
        today = date.today()
        a = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=580.0,
            due_date=today,
            status='pending',
            payment_intent_id='pi_catchup_anchor_test',
        )
        b = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=690.0,
            due_date=today,
            status='pending',
            payment_intent_id='pi_catchup_other_test',
        )
        db.session.add_all([a, b])
        db.session.flush()
        pay = Payment(
            booking_id=booking.id,
            client_id=client.id,
            trip_id=trip.id,
            amount=1270.0,
            status='pending',
            currency='usd',
            stripe_payment_intent_id='pi_catchup_anchor_test',
            installment_payment_id=a.id,
            base_amount_cents=127000,
            final_amount_cents=127000,
        )
        db.session.add(pay)
        db.session.commit()

        handle_payment_intent_succeeded(
            {
                'id': 'pi_catchup_anchor_test',
                'amount': 127000,
                'currency': 'usd',
                'metadata': {
                    'base_amount': '127000',
                    'fee': '0',
                    'final_amount': '127000',
                    'payment_step': 'catch_up',
                    'catch_up_ids': f'{a.id},{b.id}',
                    'catch_up_breakdown': 'Installment #1 $580.00 + Installment #1 $690.00',
                    'booking_id': str(booking.id),
                    'installment_id': str(a.id),
                },
            }
        )
        db.session.refresh(a)
        db.session.refresh(b)
        db.session.refresh(pay)
        db.session.refresh(booking)

        assert a.status == 'paid'
        assert b.status == 'paid'
        assert a.payment_intent_id == 'pi_catchup_anchor_test'
        assert b.payment_intent_id is None
        assert pay.status == 'succeeded'
        assert abs(float(booking.amount_paid) - 1470.0) < 0.02


def test_catch_up_when_sibling_already_holds_success_pi(app):
    """Sibling mistakenly holds the success PI — clear-then-anchor must not IntegrityError."""
    with app.app_context():
        trip = Trip.query.first()
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        if not trip or not pkg:
            return
        client = Client.query.filter_by(email='catchup-swap-pi@example.com').first()
        if not client:
            client = Client(name='Catchup Swap', email='catchup-swap-pi@example.com')
            db.session.add(client)
            db.session.flush()

        old = Booking.query.filter_by(order_number='2609QA-CATCHUP2').first()
        if old:
            Payment.query.filter_by(booking_id=old.id).delete()
            InstallmentPayment.query.filter_by(booking_id=old.id).delete()
            BookingPackage.query.filter_by(booking_id=old.id).delete()
            db.session.delete(old)
            db.session.commit()

        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            order_number='2609QA-CATCHUP2',
            status='deposit_paid',
            amount_paid=200.0,
            buyer_email='catchup-swap-pi@example.com',
            buyer_first_name='Catch',
            buyer_last_name='Swap',
            passenger_count=2,
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(
            BookingPackage(
                booking_id=booking.id,
                package_id=pkg.id,
                quantity=1,
                payment_plan_type='deposit_installment',
                amount_paid=200.0,
                status='deposit_paid',
                unit_price=float(pkg.price or 2000),
            )
        )
        today = date.today()
        a = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=580.0,
            due_date=today,
            status='pending',
            payment_intent_id=None,
        )
        b = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=690.0,
            due_date=today,
            status='pending',
            payment_intent_id='pi_catchup_swap_test',
        )
        db.session.add_all([a, b])
        db.session.flush()
        pay = Payment(
            booking_id=booking.id,
            client_id=client.id,
            trip_id=trip.id,
            amount=1270.0,
            status='pending',
            currency='usd',
            stripe_payment_intent_id='pi_catchup_swap_test',
            installment_payment_id=a.id,
            base_amount_cents=127000,
            final_amount_cents=127000,
        )
        db.session.add(pay)
        db.session.commit()

        handle_payment_intent_succeeded(
            {
                'id': 'pi_catchup_swap_test',
                'amount': 127000,
                'currency': 'usd',
                'metadata': {
                    'base_amount': '127000',
                    'fee': '0',
                    'final_amount': '127000',
                    'payment_step': 'catch_up',
                    'catch_up_ids': f'{a.id},{b.id}',
                    'catch_up_breakdown': 'Installment #1 $580.00 + Installment #1 $690.00',
                    'booking_id': str(booking.id),
                    'installment_id': str(a.id),
                },
            }
        )
        db.session.refresh(a)
        db.session.refresh(b)
        db.session.refresh(pay)
        assert a.status == 'paid' and a.payment_intent_id == 'pi_catchup_swap_test'
        assert b.status == 'paid' and b.payment_intent_id is None
        assert pay.status == 'succeeded'


def test_catch_up_resume_siblings_when_payment_already_succeeded(app):
    """Payment succeeded but sibling still pending — resume without double amount_paid."""
    from app.routes import _payment_intent_is_installment_flow

    with app.app_context():
        assert _payment_intent_is_installment_flow({
            'id': 'pi_x',
            'metadata': {'payment_step': 'catch_up', 'installment_id': '1'},
        })
        assert not _payment_intent_is_installment_flow({
            'id': 'pi_y',
            'metadata': {'payment_step': 'initial'},
        })

        trip = Trip.query.first()
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        if not trip or not pkg:
            return
        client = Client.query.filter_by(email='catchup-resume@example.com').first()
        if not client:
            client = Client(name='Catchup Resume', email='catchup-resume@example.com')
            db.session.add(client)
            db.session.flush()

        old = Booking.query.filter_by(order_number='2609QA-CATCHUP3').first()
        if old:
            Payment.query.filter_by(booking_id=old.id).delete()
            InstallmentPayment.query.filter_by(booking_id=old.id).delete()
            BookingPackage.query.filter_by(booking_id=old.id).delete()
            db.session.delete(old)
            db.session.commit()

        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            order_number='2609QA-CATCHUP3',
            status='deposit_paid',
            amount_paid=1470.0,
            buyer_email='catchup-resume@example.com',
            buyer_first_name='Catch',
            buyer_last_name='Resume',
            passenger_count=2,
        )
        db.session.add(booking)
        db.session.flush()
        today = date.today()
        a = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=580.0,
            due_date=today,
            status='paid',
            payment_intent_id='pi_catchup_resume',
            paid_at=datetime.utcnow(),
        )
        b = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=690.0,
            due_date=today,
            status='pending',
            payment_intent_id=None,
        )
        db.session.add_all([a, b])
        db.session.flush()
        pay = Payment(
            booking_id=booking.id,
            client_id=client.id,
            trip_id=trip.id,
            amount=1270.0,
            status='succeeded',
            currency='usd',
            stripe_payment_intent_id='pi_catchup_resume',
            installment_payment_id=a.id,
            base_amount_cents=127000,
            final_amount_cents=127000,
            paid_at=datetime.utcnow(),
        )
        db.session.add(pay)
        db.session.commit()

        handle_payment_intent_succeeded(
            {
                'id': 'pi_catchup_resume',
                'amount': 127000,
                'currency': 'usd',
                'metadata': {
                    'base_amount': '127000',
                    'fee': '0',
                    'final_amount': '127000',
                    'payment_step': 'catch_up',
                    'catch_up_ids': f'{a.id},{b.id}',
                    'booking_id': str(booking.id),
                    'installment_id': str(a.id),
                },
            }
        )
        db.session.refresh(a)
        db.session.refresh(b)
        db.session.refresh(booking)
        assert a.status == 'paid'
        assert b.status == 'paid'
        assert abs(float(booking.amount_paid) - 1470.0) < 0.02
