"""
定时任务模块
使用 APScheduler 实现分期付款提醒、过期 PendingBooking 清理等功能
"""

from datetime import datetime, timedelta, date
from flask import current_app, render_template, url_for
from sqlalchemy import or_, and_
from app import db
from app.models import Booking, InstallmentPayment, PendingBooking, Testimonial
from app.utils import (
    send_email_via_ses,
    generate_installment_token,
    pacific_today,
    to_pacific_date,
    _email_brand_logo_url,
)

# 未付分期：含 pending / overdue（逾期催款后会标 overdue，须继续可催）
_UNPAID_INSTALLMENT_STATUSES = ('pending', 'overdue')


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
    from app.payments import installment_display_label
    return installment_display_label(installment)


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
    auto_pay_enabled = bool(getattr(booking, 'auto_pay_enabled', False))
    auto_pay_url = None
    try:
        from app.auto_pay import auto_pay_manage_url, booking_has_installment_plan
        if booking_has_installment_plan(booking):
            auto_pay_url = auto_pay_manage_url(booking)
    except Exception:
        auto_pay_url = None
    # Auto Pay 已开启：主按钮仍可提前付；副文案改为管理方式
    if auto_pay_enabled and days_overdue is None:
        style = dict(style)
        style['brand_subtitle'] = 'Auto Pay reminder'
        style['cta_label'] = 'Pay now'
        style['highlight_title'] = (
            'Amount due today' if days_until_due == 0
            else 'Amount due tomorrow' if days_until_due == 1
            else 'Upcoming Auto Pay charge'
        )
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
        'auto_pay_enabled': auto_pay_enabled,
        'auto_pay_url': auto_pay_url,
        'auto_pay_cta_label': (
            'Manage Auto Pay' if auto_pay_enabled else 'Enable Auto Pay'
        ),
        'auto_pay_blurb': (
            'Need to change or turn off Auto Pay?'
            if auto_pay_enabled
            else 'Want us to charge your card automatically on due dates?'
        ),
        **style,
    }

    html_body = render_template('emails/installment_reminder.html', **context)
    text_body = render_template('emails/installment_reminder.txt', **context)
    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'nhtours-noreply@nhtours.com'
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


def send_payment_failed_email(installment, *, failure_reason=None, days_overdue=None):
    """
    Customer email when a payment attempt / Auto Pay charge fails.
    Branded template (emails/payment_failed.*) — not the generic reminder.
    """
    booking = installment.booking
    if not booking or not booking.buyer_email:
        current_app.logger.warning(
            'Payment failed email skipped: missing booking/email for installment %s',
            getattr(installment, 'id', '?'),
        )
        return False

    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    due_date_label = (
        installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'
    )
    auto_pay_enabled = bool(getattr(booking, 'auto_pay_enabled', False))
    auto_pay_url = None
    try:
        from app.auto_pay import auto_pay_manage_url, booking_has_installment_plan
        if booking_has_installment_plan(booking):
            auto_pay_url = auto_pay_manage_url(booking)
    except Exception:
        auto_pay_url = None

    reason = (failure_reason or '').strip() or None
    if auto_pay_enabled:
        subject = f'Auto Pay failed — action needed · {trip_title}'
        intro = (
            'We could not complete your automatic payment. '
            'Please pay using the link below or update your payment method.'
        )
        brand_subtitle = 'Auto Pay failed'
        highlight_title = 'Auto Pay charge failed'
    else:
        subject = f'Payment failed — action needed · {trip_title}'
        intro = (
            'Your payment could not be completed. '
            'No charge was made. Please try again using the link below.'
        )
        brand_subtitle = 'Payment failed'
        highlight_title = 'Payment not completed'

    context = {
        'subject_line': subject,
        'brand_subtitle': brand_subtitle,
        'customer_name': booking.buyer_first_name or 'Customer',
        'intro_text': intro,
        'highlight_title': highlight_title,
        'trip_title': trip_title,
        'installment_label': _installment_label(installment),
        'amount': float(installment.amount or 0),
        'due_date_label': due_date_label,
        'order_number': booking.order_number or booking.id,
        'payment_link': _installment_payment_link(installment),
        'email_logo_url': _email_brand_logo_url(),
        'footer_note': (
            'If you already paid this installment, please ignore this email. '
            'Thank you.'
        ),
        'days_overdue': days_overdue,
        'failure_reason': reason,
        'cta_label': 'Pay now',
        'auto_pay_enabled': auto_pay_enabled,
        'auto_pay_url': auto_pay_url,
        'auto_pay_cta_label': 'Manage Auto Pay' if auto_pay_enabled else 'Enable Auto Pay',
        'auto_pay_blurb': (
            'Need to change or turn off Auto Pay?'
            if auto_pay_enabled
            else 'Want us to charge your card automatically on due dates?'
        ),
    }
    html_body = render_template('emails/payment_failed.html', **context)
    text_body = render_template('emails/payment_failed.txt', **context)
    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'nhtours-noreply@nhtours.com'
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
            'Payment failed email failed for installment %s: %s',
            installment.id,
            detail,
        )
    return success


def cleanup_expired_pending_bookings():
    """
    清理过期未支付的 PendingBooking（创建时 expires_at = now+24h）。
    - status=pending 且已过期 → 标为 expired
    - PI 已 processing/succeeded：不 expire（ACH 清算可能超过 24h），并延长 expires_at
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
        skipped_active = 0
        from app.payments import safe_cancel_payment_intent, retrieve_payment_intent
        for pb in expired:
            pi_id = pb.payment_intent_id
            if pi_id and not str(pi_id).startswith('free_') and not str(pi_id).startswith('pending_'):
                intent = retrieve_payment_intent(pi_id)
                st = getattr(intent, 'status', None) if intent else None
                if st in ('processing', 'succeeded', 'requires_capture'):
                    # 保留报名草稿，等 webhook / status 补建单
                    pb.expires_at = now + timedelta(days=14)
                    skipped_active += 1
                    current_app.logger.info(
                        "PendingBooking cleanup: keep id=%s PI=%s status=%s",
                        pb.id, pi_id, st,
                    )
                    continue
                if safe_cancel_payment_intent(pi_id, reason=f'pending cleanup id={pb.id}'):
                    cancelled_pi += 1
            pb.status = 'expired'

        db.session.commit()
        current_app.logger.info(
            "PendingBooking cleanup: expired=%s kept_active_pi=%s stripe_cancelled=%s",
            len(expired) - skipped_active,
            skipped_active,
            cancelled_pi,
        )
        return len(expired) - skipped_active
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"PendingBooking cleanup failed: {e}", exc_info=True)
        return 0


def cleanup_old_rejected_testimonials(retention_days=None):
    """
    删除超过 retention_days 的 rejected Testimonials（默认 90 天）。
    每天由 APScheduler 调用。
    """
    try:
        days = retention_days
        if days is None:
            days = int(current_app.config.get("TESTIMONIAL_REJECT_RETENTION_DAYS", 90))
        cutoff = datetime.utcnow() - timedelta(days=max(int(days), 1))
        deleted = (
            Testimonial.query.filter(
                Testimonial.status == "rejected",
                Testimonial.created_at < cutoff,
            ).delete(synchronize_session=False)
        )
        db.session.commit()
        current_app.logger.info(
            "Testimonial cleanup: deleted %s rejected older than %s days",
            deleted,
            days,
        )
        return deleted
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Testimonial cleanup failed: {e}", exc_info=True)
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
    日历日按美西（America/Los_Angeles），与客户 due_date 口径一致。
    提醒时机：
    - 3 天前：首次提醒（含 Auto Pay：到期前仅此一次）
    - 1 天前：二次提醒（未开 Auto Pay）
    - 到期当天：最后提醒（未开 Auto Pay；Auto Pay 当天由扣款任务处理）
    - 逾期后：催款邮件（每 3 天一次；总提醒次数 reminder_count < 6）
    若订单经济上已结清（amount_due <= 0），跳过催款并取消未付分期。
    """
    try:
        from app.payments import (
            calculate_booking_total,
            cancel_unpaid_installments,
            booking_has_processing_ach_payment,
            installment_has_processing_ach,
        )

        today = pacific_today()
        sent_pre = 0
        sent_overdue = 0
        # booking_id → True if economically settled (skip reminders this run)
        settled_bookings = {}

        def _booking_is_settled(booking):
            if not booking:
                return False
            if booking.id in settled_bookings:
                return settled_bookings[booking.id]
            try:
                due = float(calculate_booking_total(booking).get('amount_due') or 0)
            except Exception:
                due = 1.0
            settled = due <= 0.001
            settled_bookings[booking.id] = settled
            if settled:
                cancel_unpaid_installments(booking)
                current_app.logger.info(
                    f"Skipping reminders for booking {booking.id}: amount_due<=0; "
                    f"cancelled unpaid installments"
                )
            return settled

        def _already_reminded_pacific_today(installment):
            last = to_pacific_date(installment.reminder_sent_at)
            return bool(last and last >= today)

        def _skip_ach_in_flight(installment):
            """ACH 清算中：不发提醒、不标 overdue（避免催款与二次付款）。"""
            if installment_has_processing_ach(installment):
                return True
            booking = installment.booking
            if booking and booking_has_processing_ach_payment(booking.id):
                return True
            return False

        def _auto_pay_on(booking):
            return bool(booking and getattr(booking, 'auto_pay_enabled', False))

        # 1. 3 天前提醒（Auto Pay 与手动付款均发；Auto Pay 到期前仅此一封）
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
            if _booking_is_settled(installment.booking):
                continue
            if _skip_ach_in_flight(installment):
                continue
            if send_installment_reminder_email(installment, days_until_due=3):
                installment.reminder_sent = True
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                sent_pre += 1

        # 2. 1 天前提醒（未开 Auto Pay；不要求必有 D-3，避免漏发后断档）
        one_day_later = today + timedelta(days=1)
        installments_1day = (
            _active_unpaid_installments_query()
            .filter(InstallmentPayment.due_date == one_day_later)
            .all()
        )

        for installment in installments_1day:
            if _booking_is_settled(installment.booking):
                continue
            if _skip_ach_in_flight(installment):
                continue
            if _auto_pay_on(installment.booking):
                continue
            if _already_reminded_pacific_today(installment):
                continue
            if send_installment_reminder_email(installment, days_until_due=1):
                installment.reminder_sent = True
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                sent_pre += 1

        # 3. 到期当天提醒（未开 Auto Pay；已开则由 9:15 扣款任务处理）
        installments_today = (
            _active_unpaid_installments_query()
            .filter(InstallmentPayment.due_date == today)
            .all()
        )

        for installment in installments_today:
            if _booking_is_settled(installment.booking):
                continue
            if _skip_ach_in_flight(installment):
                continue
            if _auto_pay_on(installment.booking):
                continue
            if _already_reminded_pacific_today(installment):
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
            if _booking_is_settled(installment.booking):
                continue
            if _skip_ach_in_flight(installment):
                continue
            days_overdue = (today - installment.due_date).days
            should_send = False

            last_pacific = to_pacific_date(installment.reminder_sent_at)
            if not last_pacific:
                should_send = True
            else:
                days_since_last = (today - last_pacific).days
                if days_since_last >= 3:
                    should_send = True

            if should_send and send_overdue_reminder_email(installment, days_overdue):
                installment.reminder_sent_at = datetime.utcnow()
                installment.reminder_count = (installment.reminder_count or 0) + 1
                if installment.status == 'pending':
                    installment.status = 'overdue'
                sent_overdue += 1

        # 5. 逾期 ≥3 天 → 通知管理员（所有分期单，含未开 Auto Pay；每期最多一次）
        admin_overdue_notified = notify_admins_of_overdue_installments(
            today=today,
            booking_is_settled=_booking_is_settled,
            skip_ach_in_flight=_skip_ach_in_flight,
        )

        db.session.commit()
        current_app.logger.info(
            f"Installment reminders processed: pacific_today={today} "
            f"pre_due={sent_pre} overdue={sent_overdue} "
            f"admin_overdue={admin_overdue_notified}"
        )

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error sending installment reminders: {str(e)}")
        import traceback
        traceback.print_exc()


def notify_admins_of_overdue_installments(
    *,
    today=None,
    booking_is_settled=None,
    skip_ach_in_flight=None,
    min_days=3,
):
    """
    未付分期逾期 ≥ min_days 天时邮件通知管理员。
    每期仅通知一次（写 admin_overdue_notified_at）；不 commit（由调用方 commit）。
    """
    today = today or pacific_today()
    cutoff = today - timedelta(days=int(min_days))
    notified = 0

    candidates = (
        _active_unpaid_installments_query()
        .filter(
            InstallmentPayment.due_date <= cutoff,
            InstallmentPayment.admin_overdue_notified_at.is_(None),
        )
        .all()
    )

    for installment in candidates:
        booking = installment.booking
        if booking_is_settled and booking_is_settled(booking):
            continue
        if skip_ach_in_flight and skip_ach_in_flight(installment):
            continue
        days_overdue = (today - installment.due_date).days if installment.due_date else 0
        if days_overdue < min_days:
            continue
        if installment.status == 'pending':
            installment.status = 'overdue'
        if send_admin_overdue_installment_email(installment, days_overdue):
            installment.admin_overdue_notified_at = datetime.utcnow()
            notified += 1

    return notified


def send_admin_overdue_installment_email(installment, days_overdue):
    """Send ≥3-day overdue alert to RECIPIENT_EMAIL (admin inbox)."""
    booking = installment.booking
    if not booking:
        return False

    trip_title = booking.trip.title if booking.trip else 'Trip Booking'
    order_number = booking.order_number or booking.id
    customer_name = (
        f"{(booking.buyer_first_name or '').strip()} {(booking.buyer_last_name or '').strip()}".strip()
        or booking.buyer_name
        or 'Customer'
    )
    due_date_label = (
        installment.due_date.strftime('%B %d, %Y') if installment.due_date else 'N/A'
    )
    manage_url = None
    if booking.trip_id:
        try:
            manage_url = url_for('admin.manage_trip', id=booking.trip_id, _external=True)
        except Exception:
            base = (current_app.config.get('BASE_URL') or 'https://nhtours.com').rstrip('/')
            manage_url = f'{base}/admin/trips/{booking.trip_id}/manage'

    subject = f"[NH Tours] Installment overdue {days_overdue}+ days — {order_number}"
    context = {
        'subject_line': subject,
        'brand_subtitle': 'Installment overdue',
        'order_number': order_number,
        'customer_name': customer_name,
        'customer_email': booking.buyer_email or '',
        'trip_title': trip_title,
        'installment_label': _installment_label(installment),
        'due_date_label': due_date_label,
        'amount': float(installment.amount or 0),
        'days_overdue': days_overdue,
        'manage_url': manage_url,
        'email_logo_url': _email_brand_logo_url(),
    }
    html_body = render_template('emails/installment_admin_overdue_notify.html', **context)
    text_body = render_template('emails/installment_admin_overdue_notify.txt', **context)
    recipient = current_app.config.get('RECIPIENT_EMAIL') or 'info@nhtours.com'
    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'nhtours-noreply@nhtours.com'
    )
    ok, detail = send_email_via_ses(sender, recipient, subject, html_body, text_body)
    if not ok:
        current_app.logger.error(
            'Admin overdue notify failed installment_id=%s: %s',
            installment.id,
            detail,
        )
    return ok


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
    auto_on = bool(getattr(booking, 'auto_pay_enabled', False))

    if auto_on:
        if days_until_due == 0:
            subject = f"Auto Pay: Charging today - {trip_title}"
            urgency_text = (
                f"Your next payment will be automatically charged today ({due_label}). "
                "No action is needed unless you want to pay early or change your payment method."
            )
        elif days_until_due == 1:
            subject = f"Auto Pay reminder: Charge tomorrow - {trip_title}"
            urgency_text = (
                f"Your next payment will be automatically charged tomorrow ({due_label}). "
                "No action is needed unless you want to pay early or change your payment method."
            )
        else:
            subject = f"Auto Pay reminder: Charge in {days_until_due} days - {trip_title}"
            urgency_text = (
                f"Your next payment will be automatically charged on {due_label}. "
                "No action is needed unless you want to pay early or change your payment method."
            )
        footer_note = (
            "If this payment has already been charged or you have already paid, "
            "please ignore this email. Thank you."
        )
    else:
        if days_until_due == 0:
            subject = f"URGENT: Payment Due Today - {trip_title}"
            urgency_text = "Your payment is due TODAY. Please complete it as soon as possible."
        elif days_until_due == 1:
            subject = f"Payment Reminder: Due Tomorrow - {trip_title}"
            urgency_text = f"Your payment is due TOMORROW ({due_label})."
        else:
            subject = f"Payment Reminder: Due in {days_until_due} Days - {trip_title}"
            urgency_text = f"Your payment is due in {days_until_due} days ({due_label})."
        footer_note = (
            "If you have already made this payment, please ignore this email. "
            "Thank you for your prompt attention."
        )

    ok = _send_installment_notice_email(
        installment,
        subject=subject,
        urgency_text=urgency_text,
        footer_note=footer_note,
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
    auto_on = bool(getattr(booking, 'auto_pay_enabled', False))

    subject = f"OVERDUE Payment Notice - {trip_title}"
    if auto_on:
        urgency_text = (
            f"We could not complete your Auto Pay charge. Your payment is now "
            f"{days_overdue} day(s) overdue. Please pay using the link below or "
            f"update your payment method under Manage Auto Pay."
        )
        footer_note = (
            "If you have already made this payment, please contact us so we can update "
            "your record. Failure to pay may result in cancellation of your booking."
        )
    else:
        urgency_text = (
            f"This is an overdue payment notice. Your payment is now "
            f"{days_overdue} day(s) overdue."
        )
        footer_note = (
            "If you have already made this payment, please contact us so we can update "
            "your record. Failure to pay may result in cancellation of your booking."
        )
    ok = _send_installment_notice_email(
        installment,
        subject=subject,
        urgency_text=urgency_text,
        footer_note=footer_note,
        days_overdue=days_overdue,
    )
    if ok:
        current_app.logger.info(
            f"Overdue reminder email sent for installment {installment.id} "
            f"({days_overdue} days overdue)"
        )
    return ok


def process_auto_pay_charges():
    """
    美西到期日：对已开启 Auto Pay 的订单尝试 Card 离线扣款（当期 + 以往未付）。
    ACH 默认方式暂跳过（后续版本）。失败则催客户 + 通知管理员。
    """
    from app.auto_pay import (
        charge_installment_via_auto_pay,
        find_due_auto_pay_installments,
        notify_admin_auto_pay_failure,
    )
    from app.payments import (
        booking_has_processing_ach_payment,
        installment_has_processing_ach,
    )

    today = pacific_today()
    ok_n = 0
    fail_n = 0
    skip_n = 0
    try:
        for installment in find_due_auto_pay_installments(today=today):
            booking = installment.booking
            if not booking:
                continue
            if installment_has_processing_ach(installment) or booking_has_processing_ach_payment(
                booking.id
            ):
                skip_n += 1
                continue
            # Avoid double-charge same pacific day
            last = to_pacific_date(booking.auto_pay_last_charge_at)
            if last and last >= today and not booking.auto_pay_last_error:
                skip_n += 1
                continue

            success, detail = charge_installment_via_auto_pay(installment, card_only=True)
            if success:
                ok_n += 1
                db.session.commit()
                continue

            if detail in ('ach_deferred', 'already_settled', 'zero_amount', 'ach_processing'):
                skip_n += 1
                db.session.commit()
                continue

            fail_n += 1
            db.session.commit()
            try:
                notify_admin_auto_pay_failure(booking, installment, detail)
            except Exception as e:
                current_app.logger.warning('Auto Pay admin failure email: %s', e)
            try:
                days_overdue = 0
                if installment.due_date and installment.due_date < today:
                    days_overdue = (today - installment.due_date).days
                send_payment_failed_email(
                    installment,
                    failure_reason=detail,
                    days_overdue=days_overdue or None,
                )
            except Exception as e:
                current_app.logger.warning('Auto Pay customer failure email: %s', e)

        current_app.logger.info(
            'Auto Pay charges: pacific_today=%s ok=%s fail=%s skip=%s',
            today,
            ok_n,
            fail_n,
            skip_n,
        )
        return ok_n
    except Exception as e:
        db.session.rollback()
        current_app.logger.error('process_auto_pay_charges failed: %s', e, exc_info=True)
        return 0


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


def scan_ledger_anomalies():
    """
    每日账本扫描：本地 reconcile + 抽样/近期单 Stripe 退款对比；发现异常则邮件提醒管理员。
    美西凌晨由 APScheduler 调用。
    """
    from datetime import datetime, timedelta
    from sqlalchemy import or_
    from app.models import Booking, Payment, db
    from app.payments import reconcile_booking_ledger
    from app.ledger_alerts import notify_ledger_mismatch

    if not current_app.config.get('LEDGER_ALERTS_ENABLED', True):
        current_app.logger.info('scan_ledger_anomalies skipped (LEDGER_ALERTS_ENABLED=false)')
        return {'scanned': 0, 'mismatches': 0, 'alerted': 0}

    days = int(current_app.config.get('LEDGER_SCAN_DAYS', 120))
    max_bookings = int(current_app.config.get('LEDGER_SCAN_MAX_BOOKINGS', 300))
    check_stripe = bool(current_app.config.get('LEDGER_SCAN_CHECK_STRIPE', True))
    since = datetime.utcnow() - timedelta(days=days)

    pay_q = (
        db.session.query(Payment.booking_id)
        .filter(
            Payment.status.in_(('succeeded', 'partially_refunded', 'refunded')),
            or_(
                Payment.paid_at >= since,
                Payment.created_at >= since,
                Payment.refunded_at >= since,
            ),
        )
        .distinct()
        .limit(max_bookings)
    )
    booking_ids = [row[0] for row in pay_q.all() if row[0]]
    if not booking_ids:
        current_app.logger.info('scan_ledger_anomalies: no candidate bookings')
        return {'scanned': 0, 'mismatches': 0, 'alerted': 0}

    scanned = 0
    mismatches = 0
    alerted = 0
    for bid in booking_ids:
        booking = Booking.query.get(bid)
        if not booking:
            continue
        try:
            result = reconcile_booking_ledger(booking, check_stripe=check_stripe)
            scanned += 1
            if result.get('ok'):
                continue
            mismatches += 1
            ok, status = notify_ledger_mismatch(booking, result, source='daily_scan')
            if ok or status == 'deduped':
                alerted += 1
        except Exception as e:
            current_app.logger.exception(
                'scan_ledger_anomalies failed booking_id=%s: %s', bid, e
            )

    current_app.logger.info(
        'scan_ledger_anomalies done scanned=%s mismatches=%s alerted=%s stripe=%s',
        scanned,
        mismatches,
        alerted,
        check_stripe,
    )
    return {'scanned': scanned, 'mismatches': mismatches, 'alerted': alerted}
