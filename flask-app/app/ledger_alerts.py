"""
账本 / Stripe 对账告警：发现不一致时邮件提醒管理员（去重，避免刷屏）。
"""

import time
import threading

from flask import current_app, render_template, url_for

_lock = threading.Lock()
_last_alert_at = {}

DEFAULT_DEDUP_SECONDS = 24 * 3600  # 同一 booking+指纹 24h 内只提醒一次


def send_ledger_alert(subject, body, *, alert_key=None, headline=None, manage_url=None):
    """
    发送账本告警到 RECIPIENT_EMAIL（可被 LEDGER_ALERT_EMAIL 覆盖）。
    始终写日志；SES 未配置时只记日志不抛错。
    """
    current_app.logger.warning(
        'ledger_alert key=%s subject=%s body_preview=%s',
        alert_key or '',
        subject,
        (body or '')[:400],
    )

    if not current_app.config.get('LEDGER_ALERTS_ENABLED', True):
        return False, 'alerts_disabled'

    dedup = int(current_app.config.get('LEDGER_ALERT_DEDUP_SECONDS', DEFAULT_DEDUP_SECONDS))
    key = alert_key or subject
    now = time.time()
    with _lock:
        last = _last_alert_at.get(key)
        if last and now - last < dedup:
            current_app.logger.info('ledger alert deduped: %s', key)
            return False, 'deduped'

    recipient = (
        current_app.config.get('LEDGER_ALERT_EMAIL')
        or current_app.config.get('RECIPIENT_EMAIL')
        or 'info@nhtours.com'
    )
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
            'ledger alert (SES not configured, log only): %s -> %s',
            subject,
            recipient,
        )
        return False, 'ses_not_configured'

    from app.utils import send_email_via_ses, _email_brand_logo_url

    html = render_template(
        'emails/ledger_alert_notify.html',
        subject_line=subject,
        brand_subtitle='Ledger alert',
        headline=headline or 'Payment ledger mismatch',
        intro=(
            'An automated ledger check found a mismatch. '
            'Review the booking before issuing further refunds.'
        ),
        alert_subject=subject,
        alert_body=body or '',
        manage_url=manage_url,
        email_logo_url=_email_brand_logo_url(),
    )
    ok, msg = send_email_via_ses(sender, recipient, subject, html, body or '')
    if ok:
        with _lock:
            _last_alert_at[key] = now
    return ok, msg


def _anomaly_fingerprint(result):
    parts = []
    if abs(float(result.get('delta') or 0)) >= 0.015:
        parts.append(f"delta:{result.get('delta')}")
    for a in result.get('anomalies') or []:
        parts.append(f"{a.get('issue')}:{a.get('payment_id')}")
    return '|'.join(parts) or 'unknown'


def notify_ledger_mismatch(booking, result, *, source='scan'):
    """
    若 reconcile 结果 ok=False，发管理员提醒。
    source: scan | reconcile_api | refund_open
    忽略仅「缺 refund_history」的软告警，避免历史数据刷屏。
    """
    if not result or result.get('ok'):
        return False, 'ok'

    anomalies = list(result.get('anomalies') or [])
    hard = [
        a for a in anomalies
        if a.get('issue') not in ('missing_refund_history',)
    ]
    delta_bad = abs(float(result.get('delta') or 0)) >= 0.015
    if not hard and not delta_bad:
        return False, 'soft_only'

    # 邮件里只展示 hard + delta
    result_for_mail = dict(result)
    result_for_mail['anomalies'] = hard if hard else anomalies

    order = (
        getattr(booking, 'order_number', None)
        or result.get('order_number')
        or f"#{getattr(booking, 'id', '?')}"
    )
    trip = booking.trip if booking else None
    trip_id = trip.id if trip else getattr(booking, 'trip_id', None)
    trip_title = trip.title if trip else 'Trip'

    lines = [
        f'Source: {source}',
        f'Order: {order}',
        f'Trip: {trip_title} (id={trip_id})',
        f'Booking id: {getattr(booking, "id", None)}',
        f'Stored amount_paid: ${float(result.get("stored_amount_paid") or 0):.2f}',
        f'Computed amount_paid: ${float(result.get("computed_amount_paid") or 0):.2f}',
        f'Delta (stored − computed): ${float(result.get("delta") or 0):.2f}',
        '',
        'Anomalies:',
    ]
    if not hard and delta_bad:
        lines.append('- amount_paid_mismatch (no per-payment anomaly listed)')
    for a in hard:
        issue = a.get('issue')
        pid = a.get('payment_id')
        extra = []
        for k in (
            'refunded_amount', 'base', 'clamped',
            'local_refunded', 'stripe_refunded_base', 'stripe_refunded_charged',
            'severity', 'error',
        ):
            if a.get(k) is not None and a.get(k) != '':
                extra.append(f'{k}={a.get(k)}')
        lines.append(f'- payment #{pid}: {issue}' + (f' ({", ".join(extra)})' if extra else ''))

    lines.append('')
    lines.append('Do not auto-fix local_ahead vs Stripe without checking Dashboard.')
    lines.append('local_behind can usually be synced from Stripe / charge.refunded webhook.')

    manage_url = None
    try:
        if trip_id:
            manage_url = url_for('admin.manage_trip', id=trip_id, _external=True)
    except Exception:
        manage_url = None

    subject = f'[NH Tours] Ledger mismatch — {order}'
    return send_ledger_alert(
        subject,
        '\n'.join(lines),
        alert_key=f'ledger:{getattr(booking, "id", 0)}:{_anomaly_fingerprint(result_for_mail)}',
        headline=f'Ledger mismatch on {order}',
        manage_url=manage_url,
    )
