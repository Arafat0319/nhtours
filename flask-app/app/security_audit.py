"""
安全审计与告警：结构化日志 + 登录暴力破解检测 + SES 告警接口（未配 SES 时仅写日志）。
"""

import json
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from flask import current_app, request

_lock = threading.Lock()
_failed_attempts = defaultdict(list)  # ip -> [unix_ts, ...]
_alert_sent_at = {}  # alert_key -> unix_ts

DEFAULT_AUDIT_LOG = "/var/log/nhtours/audit.log"
FAILURE_WINDOW_SECONDS = 600
FAILURE_THRESHOLD = 5
RATE_LIMIT_BLOCK_SECONDS = 900
ALERT_DEDUP_SECONDS = 3600


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_client_ip():
    if request:
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.remote_addr or "unknown"
    return "unknown"


def audit_log_path():
    return current_app.config.get("SECURITY_AUDIT_LOG", DEFAULT_AUDIT_LOG)


def log_security_event(event_type, **fields):
    """追加一条 JSONL 到审计日志；失败时回退到 app logger。"""
    entry = {
        "ts": _utc_now_iso(),
        "event": event_type,
        **fields,
    }
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    path = audit_log_path()
    try:
        log_dir = os.path.dirname(path)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except OSError as e:
        current_app.logger.warning("security_audit write failed (%s): %s", path, e)
        current_app.logger.info("security_event %s", entry)


def _prune_attempts(ip, now, window):
    attempts = _failed_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < window]
    _failed_attempts[ip] = attempts
    return attempts


def is_login_rate_limited(ip=None):
    """同一 IP 在封锁期内或失败次数超阈值时拒绝登录尝试。"""
    ip = ip or get_client_ip()
    now = time.time()
    with _lock:
        block_key = f"block:{ip}"
        blocked_until = _alert_sent_at.get(block_key)
        if blocked_until and now < blocked_until:
            return True
        attempts = _prune_attempts(ip, now, FAILURE_WINDOW_SECONDS)
        return len(attempts) >= FAILURE_THRESHOLD


def record_login_failure(username, ip=None):
    ip = ip or get_client_ip()
    log_security_event(
        "admin_login_failure",
        username=username or "",
        ip=ip,
        user_agent=(request.user_agent.string[:200] if request and request.user_agent else ""),
    )
    now = time.time()
    with _lock:
        _failed_attempts[ip].append(now)
        attempts = _prune_attempts(ip, now, FAILURE_WINDOW_SECONDS)
        if len(attempts) >= FAILURE_THRESHOLD:
            _alert_sent_at[f"block:{ip}"] = now + RATE_LIMIT_BLOCK_SECONDS
            from app.security_alerts import send_security_alert

            send_security_alert(
                subject="[NH Tours] 疑似后台暴力破解",
                body=(
                    f"IP: {ip}\n"
                    f"最近 {FAILURE_WINDOW_SECONDS // 60} 分钟内登录失败 {len(attempts)} 次。\n"
                    f"该 IP 已临时封锁登录 {RATE_LIMIT_BLOCK_SECONDS // 60} 分钟。\n"
                    f"时间: {_utc_now_iso()}"
                ),
                alert_key=f"login_brute_force:{ip}",
            )
            log_security_event("admin_login_rate_limited", ip=ip, failures=len(attempts))


def record_login_success(username, ip=None):
    ip = ip or get_client_ip()
    log_security_event(
        "admin_login_success",
        username=username,
        ip=ip,
        user_agent=(request.user_agent.string[:200] if request and request.user_agent else ""),
    )
    with _lock:
        _failed_attempts.pop(ip, None)
        _alert_sent_at.pop(f"block:{ip}", None)


def record_logout(username, ip=None):
    ip = ip or get_client_ip()
    log_security_event("admin_logout", username=username, ip=ip)
