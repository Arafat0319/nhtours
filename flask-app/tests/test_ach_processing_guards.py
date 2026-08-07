"""ACH processing guards: coverage helpers."""

from types import SimpleNamespace

from app.payments import (
    booking_has_processing_ach_payment,
    find_processing_ach_covering_installment,
    installment_has_processing_ach,
    payment_covers_installment,
)


def test_payment_covers_installment_direct_and_catch_up():
    inst = SimpleNamespace(id=10, booking_id=1, payment_intent_id='pi_a')
    other = SimpleNamespace(id=11, booking_id=1, payment_intent_id=None)

    direct = SimpleNamespace(
        installment_payment_id=10,
        booking_id=1,
        stripe_payment_intent_id='pi_a',
        payment_metadata={},
    )
    assert payment_covers_installment(direct, inst) is True
    assert payment_covers_installment(direct, other) is False

    catch = SimpleNamespace(
        installment_payment_id=11,
        booking_id=1,
        stripe_payment_intent_id='pi_b',
        payment_metadata={'catch_up_ids': '10,11', 'payment_step': 'catch_up'},
    )
    assert payment_covers_installment(catch, inst) is True
    assert payment_covers_installment(catch, other) is True

    payoff = SimpleNamespace(
        installment_payment_id=None,
        booking_id=1,
        stripe_payment_intent_id='pi_c',
        payment_metadata={'payment_step': 'payoff'},
    )
    assert payment_covers_installment(payoff, inst) is True


def test_processing_helpers_with_db(app):
    from datetime import date, timedelta

    from app import db
    from app.models import Booking, Client, InstallmentPayment, Payment, Trip

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            return

        client = Client(email='ach-guard@example.com', first_name='A', last_name='G')
        db.session.add(client)
        db.session.flush()

        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            buyer_email='ach-guard@example.com',
            buyer_first_name='A',
            status='deposit_paid',
            amount_paid=200,
        )
        db.session.add(booking)
        db.session.flush()

        inst = InstallmentPayment(
            booking_id=booking.id,
            installment_number=1,
            amount=400,
            due_date=date.today() + timedelta(days=3),
            status='pending',
            payment_intent_id=f'pi_guard_{booking.id}',
        )
        db.session.add(inst)
        db.session.flush()

        assert booking_has_processing_ach_payment(booking.id) is False
        assert installment_has_processing_ach(inst) is False

        pay = Payment(
            booking_id=booking.id,
            client_id=client.id,
            trip_id=trip.id,
            amount=400,
            status='processing',
            stripe_payment_intent_id=inst.payment_intent_id,
            installment_payment_id=inst.id,
            currency='USD',
            payment_metadata={
                'catch_up_ids': str(inst.id),
                'payment_step': 'installment',
            },
        )
        db.session.add(pay)
        db.session.commit()

        assert booking_has_processing_ach_payment(booking.id) is True
        assert installment_has_processing_ach(inst) is True
        found = find_processing_ach_covering_installment(inst)
        assert found is not None
        assert found.id == pay.id

        db.session.delete(pay)
        db.session.delete(inst)
        db.session.delete(booking)
        db.session.delete(client)
        db.session.commit()
