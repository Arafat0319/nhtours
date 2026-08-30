"""Smoke tests for Manage post-add add-ons."""
from app.addon_admin import booking_addon_line_total, create_manual_booking_addon
from app.addon_payment import is_addon_purchase_intent
from app.models import Booking, TripAddOn, db
from app.payments import booking_payoff_due, unpaid_manual_addons_total


def test_is_addon_purchase_intent():
    assert is_addon_purchase_intent({'payment_type': 'addon_purchase'})
    assert is_addon_purchase_intent({'payment_step': 'addon'})
    assert not is_addon_purchase_intent({'payment_step': 'installment'})


def test_create_manual_addon_and_payoff_excludes(app, client):
    with app.app_context():
        booking = Booking.query.filter(Booking.status != 'cancelled').first()
        if not booking or not booking.trip_id:
            return
        ta = TripAddOn.query.filter_by(trip_id=booking.trip_id).first()
        if not ta:
            return
        first = next(
            (
                p
                for p in booking.participants
                if (getattr(p, 'status', None) or 'active') != 'withdrawn'
            ),
            None,
        )
        before_unpaid = unpaid_manual_addons_total(booking)
        before_payoff = booking_payoff_due(booking)
        ba, err = create_manual_booking_addon(booking, ta.id, quantity=1)
        assert err is None
        assert ba is not None
        assert ba.source == 'admin_manual'
        assert ba.payment_status == 'unpaid'
        if first:
            assert ba.participant_id == first.id
        db.session.commit()
        line = booking_addon_line_total(ba)
        assert unpaid_manual_addons_total(booking) >= before_unpaid + line - 0.01
        assert abs(booking_payoff_due(booking) - before_payoff) < 0.02
        db.session.delete(ba)
        db.session.commit()


def test_full_refund_reopens_manual_addon(app):
    """全额退回 addon Payment 后，行应回 unpaid 并可再计入 unpaid_manual。"""
    from app.models import BookingAddOn, Payment
    from app.payments import apply_refund_to_ledger, unpaid_manual_addons_total

    with app.app_context():
        booking = Booking.query.filter(Booking.status != 'cancelled').first()
        if not booking or not booking.trip_id:
            return
        ta = TripAddOn.query.filter_by(trip_id=booking.trip_id).first()
        if not ta:
            return
        ba, err = create_manual_booking_addon(booking, ta.id, quantity=1)
        assert err is None
        line = booking_addon_line_total(ba)
        pay = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=line,
            status='succeeded',
            currency='usd',
            base_amount_cents=int(round(line * 100)),
            final_amount_cents=int(round(line * 100)),
            payment_metadata={'booking_addon_id': ba.id, 'payment_type': 'addon_purchase'},
        )
        db.session.add(pay)
        db.session.flush()
        ba.payment_status = 'paid'
        ba.payment_id = pay.id
        booking.amount_paid = float(booking.amount_paid or 0) + line
        db.session.commit()
        before = unpaid_manual_addons_total(booking)
        apply_refund_to_ledger(pay, booking, line, reason='unit refund reopen')
        db.session.commit()
        db.session.refresh(ba)
        assert ba.payment_status == 'unpaid'
        assert ba.payment_id is None
        assert unpaid_manual_addons_total(booking) >= before + line - 0.01
        db.session.delete(ba)
        db.session.delete(pay)
        db.session.commit()
