"""Smoke tests for Manage post-add add-ons."""
from app.addon_admin import (
    ach_verify_display_amount_dollars,
    booking_addon_line_total,
    cancel_manual_booking_addon,
    create_manual_booking_addon,
    manual_addon_can_cancel,
    resolve_manual_addon_base_cents,
    serialize_booking_addon,
)
from app.addon_payment import is_addon_purchase_intent
from app.models import Booking, BookingAddOn, Payment, TripAddOn, db
from app.payments import booking_payoff_due, calculate_booking_total, unpaid_manual_addons_total


def test_is_addon_purchase_intent():
    assert is_addon_purchase_intent({'payment_type': 'addon_purchase'})
    assert is_addon_purchase_intent({'payment_step': 'addon'})
    assert not is_addon_purchase_intent({'payment_step': 'installment'})


def test_ach_verify_email_amount_prefers_addon_line(app):
    """微验证邮件金额用 addon 行，不用被污染的 PI.amount。"""
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
        poisoned_cents = int(round(line * 100)) + 219000
        shown = ach_verify_display_amount_dollars(
            {
                'amount': poisoned_cents,
                'metadata': {
                    'booking_addon_id': str(ba.id),
                    'base_amount': str(poisoned_cents),
                    'payment_type': 'addon_purchase',
                },
            }
        )
        assert shown == line
        db.session.delete(ba)
        db.session.commit()


def test_quote_rejects_unknown_payment_step_for_booking(app, client):
    """未知 payment_step 不得再按整单 total 报价。"""
    with app.app_context():
        booking = Booking.query.filter(Booking.status != 'cancelled').first()
        if not booking:
            return
        bid = booking.id
    resp = client.post(
        '/api/payment/quote',
        json={
            'booking_id': bid,
            'payment_method_id': 'pm_card_visa',
            'payment_step': 'deposit_installment',
        },
    )
    assert resp.status_code == 400
    assert resp.get_json().get('error') == 'unsupported_payment_step'


def test_resolve_manual_addon_base_not_full_booking_total(app):
    """后加 add-on 报价必须是行金额，不能是套餐+附加的整单 total（2612MT-004 类 bug）。"""
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
        line_cents = int(round(line * 100))
        pay = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=line,
            status='pending',
            currency='usd',
            stripe_payment_intent_id='pi_test_addon_amt_guard',
            base_amount_cents=line_cents,
            final_amount_cents=line_cents,
            payment_metadata={
                'booking_addon_id': ba.id,
                'payment_type': 'addon_purchase',
                'payment_step': 'addon',
            },
        )
        ba.stripe_payment_intent_id = pay.stripe_payment_intent_id
        db.session.add(pay)
        db.session.commit()

        cents, resolved, err = resolve_manual_addon_base_cents(
            booking_id=booking.id,
            payment_intent_id=pay.stripe_payment_intent_id,
            booking_addon_id=ba.id,
        )
        assert err is None
        assert resolved.id == ba.id
        assert cents == line_cents

        total_info = calculate_booking_total(booking)
        full_cents = int(round(total_info['total'] * 100))
        # 有套餐时整单 total 应严格大于单独 addon 行（否则本用例无法回归）
        if full_cents > line_cents:
            assert cents != full_cents

        db.session.delete(ba)
        db.session.delete(pay)
        db.session.commit()


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


def test_cancel_manual_addon_unpaid_ok_processing_blocked(app):
    """未付可取消；Processing / 已绑支付方式的 pending 不可取消。"""
    with app.app_context():
        booking = Booking.query.filter(Booking.status != 'cancelled').first()
        if not booking or not booking.trip_id:
            return
        ta = TripAddOn.query.filter_by(trip_id=booking.trip_id).first()
        if not ta:
            return

        ba, err = create_manual_booking_addon(booking, ta.id, quantity=1)
        assert err is None
        db.session.commit()
        ba_id = ba.id
        can, reason = manual_addon_can_cancel(ba)
        assert can is True, reason
        assert serialize_booking_addon(ba)['can_cancel'] is True

        # Empty Incomplete pending (no PM) still cancellable
        pay_empty = Payment(
            booking_id=booking.id,
            client_id=booking.client_id,
            trip_id=booking.trip_id,
            amount=booking_addon_line_total(ba),
            status='pending',
            currency='usd',
            stripe_payment_intent_id='pi_test_addon_cancel_empty',
            payment_metadata={
                'booking_addon_id': ba.id,
                'payment_step': 'addon',
                'payment_type': 'addon_purchase',
            },
        )
        ba.stripe_payment_intent_id = pay_empty.stripe_payment_intent_id
        db.session.add(pay_empty)
        db.session.commit()
        can2, _ = manual_addon_can_cancel(ba)
        assert can2 is True

        # Pending with payment method → blocked
        pay_empty.payment_method_id = 'pm_test_started'
        db.session.commit()
        can3, reason3 = manual_addon_can_cancel(ba)
        assert can3 is False
        assert 'started' in (reason3 or '').lower() or 'pending' in (reason3 or '').lower()

        pay_empty.payment_method_id = None
        pay_empty.status = 'failed'
        db.session.commit()

        ok, msg = cancel_manual_booking_addon(ba)
        assert ok is True, msg
        db.session.commit()
        assert BookingAddOn.query.get(ba_id) is None
        db.session.delete(pay_empty)
        db.session.commit()

        ba2, err2 = create_manual_booking_addon(booking, ta.id, quantity=1)
        assert err2 is None
        ba2.payment_status = 'processing'
        db.session.commit()
        can4, _ = manual_addon_can_cancel(ba2)
        assert can4 is False
        db.session.delete(ba2)
        db.session.commit()


def test_full_refund_reopens_manual_addon(app):
    """全额退回 addon Payment 后，行应回 unpaid 并可再计入 unpaid_manual。"""
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
