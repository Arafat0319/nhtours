"""已付清 / Manage 非 Overdue 的客户不得收到逾期催款信。"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

from app.tasks import (
    _installment_customer_notice_blocked,
    _should_skip_customer_overdue_notice,
    customer_installment_notice_block_reason,
    send_overdue_reminder_email,
)


def _booking(**kwargs):
    defaults = dict(
        id=27,
        status='deposit_paid',
        order_number='2706ERJP-006',
        buyer_email='parent@example.com',
        auto_pay_enabled=False,
        trip=SimpleNamespace(title='2027 Japan Trip'),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def _inst(**kwargs):
    defaults = dict(
        id=112,
        booking_id=27,
        installment_number=1,
        amount=399.0,
        due_date=date(2026, 10, 6),
        status='paid',
        booking=_booking(),
    )
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_skip_paid_and_cancelled_without_db():
    assert customer_installment_notice_block_reason(None) == 'missing'
    assert customer_installment_notice_block_reason(_inst(status='paid')) == 'paid'
    assert customer_installment_notice_block_reason(_inst(status='cancelled')) == 'cancelled'
    assert customer_installment_notice_block_reason(
        _inst(status='overdue', booking=_booking(status='cancelled'))
    ) == 'booking_cancelled'
    assert _should_skip_customer_overdue_notice(None) is True
    assert _should_skip_customer_overdue_notice(_inst(status='paid')) is True
    assert _should_skip_customer_overdue_notice(_inst(status='cancelled')) is True
    assert _should_skip_customer_overdue_notice(
        _inst(status='overdue', booking=_booking(status='cancelled'))
    ) is True


def test_pre_due_reminder_does_not_require_overdue_display(app):
    inst = _inst(status='pending')
    with app.app_context():
        with patch('app.payments.installment_has_processing_ach', return_value=False):
            with patch('app.payments.booking_has_processing_ach_payment', return_value=False):
                with patch('app.models.Payment.query') as q:
                    q.filter.return_value.all.return_value = []
                    with patch(
                        'app.payments.booking_payment_display_status',
                        return_value='deposit_paid',
                    ):
                        assert _installment_customer_notice_blocked(
                            inst, require_overdue_display=False
                        ) is False
                        assert _should_skip_customer_overdue_notice(inst) is True


def test_skip_when_payment_covers_installment(app):
    inst = _inst(status='overdue')
    pay = SimpleNamespace(id=91, status='succeeded')
    with app.app_context():
        with patch('app.payments.installment_has_processing_ach', return_value=False):
            with patch('app.payments.booking_has_processing_ach_payment', return_value=False):
                with patch('app.models.Payment.query') as q:
                    q.filter.return_value.all.return_value = [pay]
                    with patch(
                        'app.payments.payment_covers_installment', return_value=True
                    ):
                        assert _should_skip_customer_overdue_notice(inst) is True


def test_real_overdue_display_is_not_skipped(app):
    inst = _inst(status='overdue')
    with app.app_context():
        with patch('app.payments.installment_has_processing_ach', return_value=False):
            with patch('app.payments.booking_has_processing_ach_payment', return_value=False):
                with patch('app.models.Payment.query') as q:
                    q.filter.return_value.all.return_value = []
                    with patch(
                        'app.payments.booking_payment_display_status',
                        return_value='overdue',
                    ):
                        assert _should_skip_customer_overdue_notice(inst) is False


def test_send_overdue_does_not_email_paid_installment(app):
    inst = _inst(status='paid')
    with app.app_context():
        with patch('app.tasks.send_email_via_ses') as send:
            with patch('app.ops_log.notify_ops_issue') as note:
                assert send_overdue_reminder_email(inst, 14) is False
                send.assert_not_called()
                note.assert_called_once()
                assert note.call_args.kwargs.get('audience') == 'admin'


def test_send_overdue_does_not_email_when_manage_not_overdue(app):
    inst = _inst(status='overdue')
    with app.app_context():
        with patch('app.payments.installment_has_processing_ach', return_value=False):
            with patch('app.payments.booking_has_processing_ach_payment', return_value=False):
                with patch('app.models.Payment.query') as q:
                    q.filter.return_value.all.return_value = []
                    with patch(
                        'app.payments.booking_payment_display_status',
                        return_value='deposit_paid',
                    ):
                        with patch('app.tasks.send_email_via_ses') as send:
                            with patch('app.ops_log.notify_ops_issue') as note:
                                assert send_overdue_reminder_email(inst, 14) is False
                                send.assert_not_called()
                                note.assert_called_once()


def test_ach_processing_blocks_without_admin_page(app):
    inst = _inst(status='overdue')
    with app.app_context():
        with patch('app.payments.installment_has_processing_ach', return_value=True):
            with patch('app.tasks.send_email_via_ses') as send:
                with patch('app.ops_log.notify_ops_issue') as note:
                    assert send_overdue_reminder_email(inst, 14) is False
                    send.assert_not_called()
                    note.assert_not_called()


def test_anomaly_reason_classification():
    from app.ops_log import is_anomaly_block_reason

    assert is_anomaly_block_reason('paid') is True
    assert is_anomaly_block_reason('payment_covers') is True
    assert is_anomaly_block_reason('display_not_overdue:deposit_paid') is True
    assert is_anomaly_block_reason('ach_processing') is False
    assert is_anomaly_block_reason('booking_cancelled') is False
