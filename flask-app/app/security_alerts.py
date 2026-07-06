"""
安全告警：优先写审计日志；SES 可用时发邮件。未配置 SES 时不报错。
"""

import os
import time
import threading

from flask import current_app

_lock = threading.Lock()
_last_alert_at = {}

DEFAULT_DEDUP_SECONDS = 3600


def send_security_alert(subject, body, *, alert_key=None, html_body=None):
    """
    发送安全告警。始终写 audit；SES 就绪时发信。
    alert_key 用于去重（同一 key 在 dedup 窗口内只发一封）。
    """
    from app.security_audit import log_security_event

    log_security_event(
        "security_alert",
        subject=subject,
        alert_key=alert_key or "",
        body_preview=(body[:500] if body else ""),
    )

    if not current_app.config.get("SECURITY_ALERTS_ENABLED", True):
        current_app.logger.info("security alert suppressed (disabled): %s", subject)
        return False, "alerts_disabled"

    dedup = int(current_app.config.get("SECURITY_ALERT_DEDUP_SECONDS", DEFAULT_DEDUP_SECONDS))
    key = alert_key or subject
    now = time.time()
    with _lock:
        last = _last_alert_at.get(key)
        if last and now - last < dedup:
            current_app.logger.info("security alert deduped: %s", key)
            return False, "deduped"

    recipient = (
        current_app.config.get("SECURITY_ALERT_EMAIL")
        or current_app.config.get("RECIPIENT_EMAIL")
        or "info@nhtours.com"
    )
    sender = (
        current_app.config.get("SENDER_EMAIL")
        or current_app.config.get("RECIPIENT_EMAIL")
        or "noreply@nhtours.com"
    )

    region = current_app.config.get("AWS_REGION", "")
    access_key = current_app.config.get("AWS_ACCESS_KEY_ID", "")
    secret_key = current_app.config.get("AWS_SECRET_ACCESS_KEY", "")

    if not (region and access_key and secret_key):
        current_app.logger.warning(
            "security alert (SES not configured, log only): %s -> %s",
            subject,
            recipient,
        )
        return False, "ses_not_configured"

    from app.utils import send_email_via_ses

    text = body or ""
    html = html_body or f"<pre>{text}</pre>"
    ok, msg = send_email_via_ses(sender, recipient, subject, html, text)
    if ok:
        with _lock:
            _last_alert_at[key] = now
    return ok, msg


def notify_fail2ban_ban(ip, jail, failures=None):
    """供 fail2ban action 脚本调用（写文件或 HTTP 时亦可复用）。"""
    from app.security_audit import log_security_event

    log_security_event("fail2ban_ban", ip=ip, jail=jail, failures=failures)
    send_security_alert(
        subject="[NH Tours] fail2ban 已封禁 IP",
        body=f"IP: {ip}\nJail: {jail}\nFailures: {failures or 'n/a'}",
        alert_key=f"fail2ban:{ip}:{jail}",
    )
