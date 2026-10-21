"""
对照本地现有订单：新守卫不得把「原样保存」挡掉，也不得对已付期再催。
只读扫描，不改账本。
"""
from app.installment_admin_links import installment_unpaid_action_error
from app.payments import (
    booking_manual_status_edit_error,
    computed_booking_amount_paid,
)
from app.tasks import customer_installment_notice_block_reason


def test_save_changes_allows_current_status_and_paid_on_existing_bookings(app):
    from app.models import Booking

    blocked = []
    with app.app_context():
        rows = Booking.query.order_by(Booking.id.desc()).limit(400).all()
        for booking in rows:
            err = booking_manual_status_edit_error(
                booking, booking.status, booking.amount_paid
            )
            if err:
                blocked.append((booking.id, booking.order_number, booking.status, err))
            try:
                display = computed_booking_amount_paid(booking)
            except Exception:
                display = booking.amount_paid
            err2 = booking_manual_status_edit_error(
                booking, booking.status, display
            )
            if err2:
                blocked.append(
                    (booking.id, booking.order_number, 'display_echo', err2)
                )
    assert blocked == [], blocked[:8]


def test_paid_and_cancelled_installments_are_blocked_from_notices(app):
    from app.models import InstallmentPayment

    leaked = []
    with app.app_context():
        rows = (
            InstallmentPayment.query.filter(
                InstallmentPayment.status.in_(('paid', 'cancelled'))
            )
            .order_by(InstallmentPayment.id.desc())
            .limit(400)
            .all()
        )
        for inst in rows:
            reason = customer_installment_notice_block_reason(inst)
            if not reason:
                leaked.append((inst.id, inst.booking_id, inst.status, inst.installment_number))
            err = installment_unpaid_action_error(inst)
            if not err:
                leaked.append((inst.id, 'unpaid_action_allowed', inst.status))
    assert leaked == [], leaked[:8]
