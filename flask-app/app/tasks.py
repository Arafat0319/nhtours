"""
定时任务模块
使用 APScheduler 实现分期付款提醒、过期 PendingBooking 清理等功能
"""

from datetime import datetime, timedelta, date
from flask import current_app, render_template, url_for
from sqlalchemy import or_, and_
from app import db
from app.models import Booking, InstallmentPayment, PendingBooking
from app.utils import send_email_via_ses, generate_installment_token

# 未付分期：含 pending / overdue（逾期催款后会标 overdue，须继续可催）
_UNPAID_INSTALLMENT_STATUSES = ('pending', 'overdue')


def _email_brand_logo_url():
    """催款/收据邮件页脚 logo（PNG；邮件客户端基本不支持 SVG）。"""
    base = (current_app.config.get('BASE_URL') or '').rstrip('/') or 'https://nhtours.com'
    return f'{base}/static/images/icons/nexus-horizons-email.png'


def _installment_payment_link(installment):
    try:
        payment_token = generate_installment_token(installment.id)
        return url_for(
            'main.pay_installment',
            installment_id=installment.id,
            token=payment_token,
            _external=True,
        )
    except Exception:
        payment_token = generate_installment_token(installment.id)
        base = (current_app.config.get('BASE_URL') or 'https://nhtours.com').rstrip('/')
        return f'{base}/pay-installment/{installment.id}?token={payment_token}'


def _installment_label(installment):
    if installment.installment_number is None or installment.installment_number == 0:
        return 'Deposit'
    return f'Installment #{installment.installment_number}'


def _reminder_style(days_until_due=None, days_overdue=None):
    """主题色：3天蓝 / 明天琥珀 / 当天与逾期红。"""
    if days_overdue is not None:
        return {
            'brand_subtitle': 'Overdue payment notice',
            'highlight_bg': '#fef2f2',
            'highlight_border': '#fecaca',
            'highlight_label': '#b91c1c',
            'highlight_amount': '#7f1d1d',
            'highlight_title': 'Amount overdue',
            'cta_bg': '#dc2626',
            'cta_label': 'Pay now',
        }
    if days_until_due == 0:
        return {
            'brand_subtitle': 'Payment due today',
            'highlight_bg': '#fef2f2',
            'highlight_border': '#fecaca',
            'highlight_label': '#b91c1c',
            'highlight_amount': '#7f1d1d',
            'highlight_title': 'Amount due today',
            'cta_bg': '#dc2626',
            'cta_label': 'Pay today',
        }
    if days_until_due == 1:
        return {
            'brand_subtitle': 'Payment reminder',
            'highlight_bg': '#fffbeb',
            'highlight_border': '#fde68a',
            'highlight_label': '#b45309',
            'highlight_amount': '#92400e',
            'highlight_title': 'Amount due tomorrow',
            'cta_bg': '#d97706',
            'cta_label': 'Pay installment',
        }
    return {
        'brand_subtitle': 'Payment reminder',
        'highlight_bg': '#f0f9ff',
        'highlight_border': '#bae6fd',
        'highlight_label': '#0369a1',
        'highlight_amount': '#0c4a6e',
        'highlight_title': 'Upcoming payment',
        'cta_bg': '#0066ff',
        'cta_label': 'Pay installment',
    }


def _send_installment_notice_email(installment, *, subject, urgency_text, footer_note,
                                   days_until_due=None, days_overdue=None):
    """渲染 HTML 催款模板并经 SES 发送（含纯文本备援）。"""
    booking = installment.booking
    if not booking or not booking.buyer_email:
        current_app.logger.warning(
            f'InstallmentPayment {getattr(installment, "id", "?")} missing booking/email'
        )
        return False

    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    due_date_label = (
        installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'
    )
    style = _reminder_style(days_until_due=days_until_due, days_overdue=days_overdue)
    context = {
        'subject_line': subject,
        'customer_name': booking.buyer_first_name or 'Customer',
        'trip_title': trip_title,
        'urgency_text': urgency_text,
        'installment_label': _installment_label(installment),
        'amount': float(installment.amount or 0),
        'due_date_label': due_date_label,
        'order_number': booking.order_number or booking.id,
        'payment_link': _installment_payment_link(installment),
        'email_logo_url': _email_brand_logo_url(),
        'footer_note': footer_note,
        'days_overdue': days_overdue,
        **style,
    }

    html_body = render_template('emails/installment_reminder.html', **context)
    text_body = render_template('emails/installment_reminder.txt', **context)
    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'noreply@nhtours.com'
    )
    success, detail = send_email_via_ses(
        sender,
        booking.buyer_email,
        subject,
        html_body,
        text_body,
    )
    if not success:
        current_app.logger.error(
            f'Installment notice email failed for installment {installment.id}: {detail}'
        )
    return success


def cleanup_expired_pending_bookings():
    """
    清理过期未支付的 PendingBooking（创建时 expires_at = now+24h）。
    - status=pending 且已过期 → 标为 expired
    - 尽量取消对应 Stripe PaymentIntent（已成功/已取消则忽略）
    每天由 APScheduler 调用。
    """
    import stripe

    try:
        now = datetime.utcnow()
        cutoff = now - timedelta(hours=24)
        expired = (
            PendingBooking.query.filter(
                PendingBooking.status == 'pending',
                or_(
                    and_(PendingBooking.expires_at.isnot(None), PendingBooking.expires_at <= now),
                    and_(PendingBooking.expires_at.is_(None), PendingBooking.created_at <= cutoff),
                ),
            )
            .all()
        )

        if not expired:
            current_app.logger.info("PendingBooking cleanup: nothing to expire")
            return 0

        stripe.api_key = current_app.config.get('STRIPE_SECRET_KEY')
        cancelled_pi = 0
        from app.payments import safe_cancel_payment_intent
        for pb in expired:
            pi_id = pb.payment_intent_id
            if pi_id and not str(pi_id).startswith('free_'):
                if safe_cancel_payment_intent(pi_id, reason=f'pending cleanup id={pb.id}'):
                    cancelled_pi += 1
            pb.status = 'expired'

        db.session.commit()
        current_app.logger.info(
            f"PendingBooking cleanup: expired={len(expired)}, stripe_cancelled={cancelled_pi}"
        )
        return len(expired)
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"PendingBooking cleanup failed: {e}", exc_info=True)
        return 0


def _active_unpaid_installments_query():
    """未付分期，且所属订单未取消。"""
    return (
        InstallmentPayment.query.join(Booking, InstallmentPayment.booking_id == Booking.id)
        .filter(
            InstallmentPayment.status.in_(_UNPAID_INSTALLMENT_STATUSES),
            Booking.status != 'cancelled',
        )
    )


def send_installment_reminders():
    """
    发送分期付款提醒邮件
    每天运行，检查即将到期的分期付款
    提醒时机：
    - 3 天前：首次提醒
    - 1 天前：二次提醒
    - 到期当天：最后提醒
    - 逾期后：催款邮件（每 3 天一次，最多 3 次；status 可为 pending 或 overdue）
    """
    try:
        today = date.today()
        sent_pre = 0
        sent_overdue = 0

        # 1. 3 天前提醒
        three_days_later = today + timedelta(days=3)
        installments_3days = (
            _active_unpaid_installments_query()
            .filter(
                InstallmentPayment.due_date == three_days_later,
                InstallmentPayment.reminder_sent == False,
            )
            .all()
        )

        for installment in installments_3days:
            if send_installment_reminder_email(installment, days_until_due=3):
                installment.reminder_sent = True
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                sent_pre += 1

        # 2. 1 天前提醒（不要求必有 D-3，避免漏发后断档）
        one_day_later = today + timedelta(days=1)
        installments_1day = (
            _active_unpaid_installments_query()
            .filter(InstallmentPayment.due_date == one_day_later)
            .all()
        )

        for installment in installments_1day:
            if installment.reminder_sent_at and installment.reminder_sent_at.date() >= today:
                continue
            if send_installment_reminder_email(installment, days_until_due=1):
                installment.reminder_sent = True
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                sent_pre += 1

        # 3. 到期当天提醒
        installments_today = (
            _active_unpaid_installments_query()
            .filter(InstallmentPayment.due_date == today)
            .all()
        )

        for installment in installments_today:
            if installment.reminder_sent_at and installment.reminder_sent_at.date() >= today:
                continue
            if send_installment_reminder_email(installment, days_until_due=0):
                installment.reminder_sent = True
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                sent_pre += 1

        # 4. 逾期催款（含 status=overdue；每 3 天一次，最多 6 次总提醒）
        overdue_installments = (
            _active_unpaid_installments_query()
            .filter(
                InstallmentPayment.due_date < today,
                InstallmentPayment.reminder_count < 6,
            )
            .all()
        )

        for installment in overdue_installments:
            days_overdue = (today - installment.due_date).days
            should_send = False

            if not installment.reminder_sent_at:
                should_send = True
            else:
                days_since_last = (today - installment.reminder_sent_at.date()).days
                if days_since_last >= 3:
                    should_send = True

            if should_send and send_overdue_reminder_email(installment, days_overdue):
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                if installment.status == 'pending':
                    installment.status = 'overdue'
                sent_overdue += 1

        db.session.commit()
        current_app.logger.info(
            f"Installment reminders processed: pre_due={sent_pre} overdue={sent_overdue}"
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error sending installment reminders: {str(e)}")
        import traceback
        traceback.print_exc()


def send_installment_reminder_email(installment, days_until_due=3):
    """
    发送分期付款提醒邮件（HTML，与收据同品牌样式）

    Args:
        installment: InstallmentPayment 对象
        days_until_due: 距离到期日还有几天（0 表示今天到期）
    """
    if not installment.booking:
        current_app.logger.warning(
            f"InstallmentPayment {installment.id} has no associated booking"
        )
        return False

    booking = installment.booking
    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    due_label = (
        installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'
    )

    if days_until_due == 0:
        subject = f"URGENT: Payment Due Today - {trip_title}"
        urgency_text = "Your payment is due TODAY. Please complete it as soon as possible."
    elif days_until_due == 1:
        subject = f"Payment Reminder: Due Tomorrow - {trip_title}"
        urgency_text = f"Your payment is due TOMORROW ({due_label})."
    else:
        subject = f"Payment Reminder: Due in {days_until_due} Days - {trip_title}"
        urgency_text = f"Your payment is due in {days_until_due} days ({due_label})."

    ok = _send_installment_notice_email(
        installment,
        subject=subject,
        urgency_text=urgency_text,
        footer_note=(
            "If you have already made this payment, please ignore this email. "
            "Thank you for your prompt attention."
        ),
        days_until_due=days_until_due,
    )
    if ok:
        current_app.logger.info(
            f"Reminder email sent for installment {installment.id} "
            f"(due in {days_until_due} days)"
        )
    return ok


def send_overdue_reminder_email(installment, days_overdue):
    """
    发送逾期催款邮件（HTML）

    Args:
        installment: InstallmentPayment 对象
        days_overdue: 逾期天数
    """
    if not installment.booking:
        return False

    booking = installment.booking
    trip_title = booking.trip.title if booking.trip else 'Trip Booking'

    subject = f"OVERDUE Payment Notice - {trip_title}"
    urgency_text = (
        f"This is an overdue payment notice. Your payment is now "
        f"{days_overdue} day(s) overdue."
    )
    ok = _send_installment_notice_email(
        installment,
        subject=subject,
        urgency_text=urgency_text,
        footer_note=(
            "If you have already made this payment, please contact us so we can update "
            "your record. Failure to pay may result in cancellation of your booking."
        ),
        days_overdue=days_overdue,
    )
    if ok:
        current_app.logger.info(
            f"Overdue reminder email sent for installment {installment.id} "
            f"({days_overdue} days overdue)"
        )
    return ok


def send_scheduled_messages():
    """
    发送到期的 Trip Message（Manage → Schedule）。
    每分钟由 APScheduler 调用；实现见 app.messaging.send_due_scheduled_messages。
    """
    from app.messaging import send_due_scheduled_messages

    try:
        n = send_due_scheduled_messages()
        if n:
            current_app.logger.info(f"Scheduled messages processed: {n}")
        return n
    except Exception as e:
        current_app.logger.error(f"send_scheduled_messages failed: {e}", exc_info=True)
        return 0
