"""
客户敏感操作留痕 + 异常告警。

原则：发客户邮件 / 改账本级记录前先复核；做过的操作独立落库
（不受调用方 rollback / SIGTERM 影响）；业务异常通知管理员，
技术异常通知 TECH_ALERT_EMAIL（未配置则回落安全/团队邮箱）。
"""

from __future__ import annotations

import time
import threading
from datetime import datetime

from flask import current_app, has_request_context

_lock = threading.Lock()
_last_alert_at = {}

DEFAULT_DEDUP_SECONDS = 24 * 3600

# 拦截后需要通知的原因（误催 / 账本不一致 / 守卫失败）
_ANOMALY_REASON_PREFIXES = (
    'paid',
    'payment_covers',
    'display_not_overdue',
    'empty_unpaid_group',
    'guard_error',
)


def current_ops_actor():
    """后台已登录用户记 admin:用户名；否则视为 cron/system。"""
    try:
        from flask_login import current_user

        if has_request_context() and getattr(current_user, 'is_authenticated', False):
            name = (
                getattr(current_user, 'username', None)
                or getattr(current_user, 'email', None)
                or getattr(current_user, 'id', None)
            )
            return f'admin:{name}'
    except Exception:
        pass
    return 'system'


def record_operation(
    *,
    category,
    action,
    result,
    reason=None,
    actor=None,
    booking_id=None,
    order_number=None,
    related_id=None,
    related_type=None,
    recipient=None,
    subject=None,
    message_id=None,
    extra=None,
):
    """
    独立 session commit，避免被业务事务 rollback，也避免污染调用方 session。
    TESTING 默认不写库（避免污染开发库）；OPS_LOG_IN_TESTS=1 可打开。
    """
    try:
        if current_app.config.get('TESTING') and not current_app.config.get('OPS_LOG_IN_TESTS'):
            current_app.logger.info(
                'operation_log skip(testing) %s/%s %s %s',
                category,
                action,
                result,
                reason or '',
            )
            return None
    except Exception:
        pass

    try:
        from sqlalchemy.orm import sessionmaker

        from app import db
        from app.models import OperationLog

        row = OperationLog(
            created_at=datetime.utcnow(),
            category=(category or 'ops')[:40],
            action=(action or 'unknown')[:80],
            result=(result or 'ok')[:40],
            actor=(actor or current_ops_actor() or 'system')[:80],
            booking_id=booking_id,
            order_number=(str(order_number)[:64] if order_number else None),
            related_id=str(related_id)[:64] if related_id is not None else None,
            related_type=(related_type or None) and str(related_type)[:40],
            recipient=(recipient or None) and str(recipient)[:190],
            subject=(subject or None) and str(subject)[:255],
            message_id=(message_id or None) and str(message_id)[:128],
            reason=(reason or None) and str(reason)[:255],
            extra=extra if isinstance(extra, dict) else None,
        )
        SessionLocal = sessionmaker(bind=db.engine)
        session = SessionLocal()
        try:
            session.add(row)
            session.commit()
            return row.id
        except Exception:
            session.rollback()
            current_app.logger.exception('operation_log write failed action=%s', action)
            return None
        finally:
            session.close()
    except Exception:
        try:
            current_app.logger.exception('operation_log unavailable action=%s', action)
        except Exception:
            pass
        return None


def record_email_send(
    *,
    success,
    recipient,
    subject,
    message_id=None,
    error=None,
    action=None,
    category=None,
    booking_id=None,
    order_number=None,
    related_id=None,
    related_type=None,
    actor=None,
):
    return record_operation(
        category=category or ('email_customer' if booking_id else 'email'),
        action=action or 'ses_send',
        result='sent' if success else 'failed',
        reason=None if success else (error or 'send_failed'),
        actor=actor,
        booking_id=booking_id,
        order_number=order_number,
        related_id=related_id,
        related_type=related_type,
        recipient=recipient,
        subject=subject,
        message_id=message_id if success else None,
        extra={'error': error} if (not success and error) else None,
    )


def notify_ops_issue(
    subject,
    body,
    *,
    audience='admin',
    alert_key=None,
    headline=None,
    order_number=None,
):
    """
    audience=admin → 团队/账本邮箱；audience=tech → TECH_ALERT_EMAIL。
    去重 24h；TESTING 不发信。
    """
    current_app.logger.warning(
        'ops_issue audience=%s key=%s subject=%s preview=%s',
        audience,
        alert_key or '',
        subject,
        (body or '')[:400],
    )
    record_operation(
        category='alert',
        action=f'ops_alert_{audience}',
        result='queued',
        reason=alert_key,
        order_number=order_number,
        subject=subject,
        extra={'audience': audience, 'body_preview': (body or '')[:500]},
    )

    if current_app.config.get('TESTING'):
        return False, 'testing'
    if not current_app.config.get('OPS_ALERTS_ENABLED', True):
        return False, 'alerts_disabled'

    dedup = int(current_app.config.get('OPS_ALERT_DEDUP_SECONDS', DEFAULT_DEDUP_SECONDS))
    key = alert_key or subject
    now = time.time()
    with _lock:
        last = _last_alert_at.get(key)
        if last and now - last < dedup:
            current_app.logger.info('ops alert deduped: %s', key)
            return False, 'deduped'

    if audience == 'tech':
        recipient = (
            current_app.config.get('TECH_ALERT_EMAIL')
            or current_app.config.get('SECURITY_ALERT_EMAIL')
            or current_app.config.get('RECIPIENT_EMAIL')
            or 'info@nhtours.com'
        )
        brand_subtitle = 'Technical alert'
        intro = (
            'An automated technical check failed or caught a code-path anomaly. '
            'Customer mail was blocked or a job aborted. Please inspect logs.'
        )
        footer = 'Technical ops alert. Same key is deduped for 24 hours.'
    else:
        recipient = (
            current_app.config.get('LEDGER_ALERT_EMAIL')
            or current_app.config.get('RECIPIENT_EMAIL')
            or 'info@nhtours.com'
        )
        brand_subtitle = 'Operations alert'
        intro = (
            'A customer-facing action was blocked after a double-check, '
            'or a payment/notice mismatch was found. Review the booking.'
        )
        footer = 'Operations alert. Same key is deduped for 24 hours.'

    sender = (
        current_app.config.get('SENDER_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'nhtours-noreply@nhtours.com'
    )
    region = current_app.config.get('AWS_REGION', '')
    access_key = current_app.config.get('AWS_ACCESS_KEY_ID', '')
    secret_key = current_app.config.get('AWS_SECRET_ACCESS_KEY', '')
    if not (region and access_key and secret_key):
        current_app.logger.warning(
            'ops alert (SES not configured, log only): %s -> %s',
            subject,
            recipient,
        )
        return False, 'ses_not_configured'

    from flask import render_template

    from app.utils import _email_brand_logo_url, send_email_via_ses

    html = render_template(
        'emails/ops_alert_notify.html',
        subject_line=subject,
        brand_subtitle=brand_subtitle,
        headline=headline or subject,
        intro=intro,
        alert_subject=subject,
        alert_body=body or '',
        email_logo_url=_email_brand_logo_url(),
        footer_note=footer,
    )
    ok, msg = send_email_via_ses(
        sender,
        recipient,
        subject,
        html,
        body or '',
        op_action=f'ops_alert_{audience}',
        op_category='email_admin',
        order_number=order_number,
        actor='system',
    )
    if ok:
        with _lock:
            _last_alert_at[key] = now
    return ok, msg


def is_anomaly_block_reason(reason):
    if not reason:
        return False
    return any(str(reason).startswith(p) for p in _ANOMALY_REASON_PREFIXES)


def record_and_alert_blocked_customer_notice(
    *,
    action,
    reason,
    installment=None,
    extra=None,
):
    """催款被双重校验拦住：一律留痕；账本/误催类再通知管理员或技术。"""
    booking = getattr(installment, 'booking', None) if installment else None
    order_number = getattr(booking, 'order_number', None)
    record_operation(
        category='email_blocked',
        action=action,
        result='blocked',
        reason=reason,
        booking_id=getattr(booking, 'id', None),
        order_number=order_number,
        related_id=getattr(installment, 'id', None),
        related_type='installment',
        recipient=getattr(booking, 'buyer_email', None),
        extra=extra,
    )
    if not is_anomaly_block_reason(reason):
        return
    audience = 'tech' if str(reason).startswith('guard_error') else 'admin'
    inst_id = getattr(installment, 'id', None)
    status = getattr(installment, 'status', None)
    due = getattr(installment, 'due_date', None)
    body = (
        f"Order: {order_number or '-'}\n"
        f"Action: {action}\n"
        f"Block reason: {reason}\n"
        f"Installment id: {inst_id}  status: {status}  due: {due}\n"
        f"Customer email: {getattr(booking, 'buyer_email', None) or '-'}\n"
        "Customer email was NOT sent.\n"
    )
    notify_ops_issue(
        subject=f"[NH Tours] Blocked customer {action} — {order_number or inst_id}",
        body=body,
        audience=audience,
        alert_key=f"blocked:{action}:{inst_id}:{reason}",
        headline='Customer notice blocked by double-check',
        order_number=order_number,
    )
