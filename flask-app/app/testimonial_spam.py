"""Testimonial / post-trip feedback spam filtering (no new DB status)."""

from __future__ import annotations

import hashlib
import re
import threading
import time
from collections import defaultdict
from enum import Enum

from flask import current_app

from app.security_audit import get_client_ip, log_security_event

_lock = threading.Lock()
_submissions_by_ip: dict[str, list[float]] = defaultdict(list)
_recent_quote_hashes: dict[str, float] = {}

RATE_LIMIT_WINDOW_SECONDS = 900
RATE_LIMIT_MAX_SUBMISSIONS = 3
DUPLICATE_WINDOW_SECONDS = 86400

URL_PAT = re.compile(r"https?://|www\.|<\s*a\s+|<\s*/|<\s*[a-z]+[\s>/]", re.I)
SPAM_WORDS = re.compile(
    r"viagra|cialis|casino|crypto|bitcoin|forex|\bxrumer\b|\bgsa search engine ranker\b|"
    r"backlink|porn|xxx|payday loan|telegram\.me|t\.me/|2captcha|omocaptcha|"
    r"накрутк|казино|online casino|playcroco",
    re.I,
)
GIBBERISH_NAME = re.compile(
    r"^[A-Za-z]{12,}$|^\d{4,}$|[A-Za-z]{8,}[0-9]{2,}[A-Za-z]*$",
)


class SpamAction(str, Enum):
    ALLOW = "allow"
    REJECT_SILENT = "reject_silent"
    DROP_SILENT = "drop_silent"


def is_spam_filter_enabled() -> bool:
    raw = current_app.config.get("TESTIMONIAL_SPAM_FILTER", "1")
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def _thresholds(source: str) -> tuple[int, int]:
    if source == "feedback":
        return 4, 6
    return 3, 5


def _normalize_quote(quote: str) -> str:
    return " ".join((quote or "").split()).lower()


def _quote_hash(quote: str) -> str:
    return hashlib.sha256(_normalize_quote(quote).encode("utf-8")).hexdigest()


def _prune_timestamps(entries: list[float], now: float, window: float) -> list[float]:
    return [t for t in entries if now - t < window]


def _is_rate_limited(ip: str, now: float) -> bool:
    with _lock:
        entries = _prune_timestamps(_submissions_by_ip.get(ip, []), now, RATE_LIMIT_WINDOW_SECONDS)
        _submissions_by_ip[ip] = entries
        return len(entries) >= RATE_LIMIT_MAX_SUBMISSIONS


def _is_duplicate_quote(quote: str, now: float) -> bool:
    if not quote:
        return False
    key = _quote_hash(quote)
    with _lock:
        seen_at = _recent_quote_hashes.get(key)
        if seen_at and now - seen_at < DUPLICATE_WINDOW_SECONDS:
            return True
        return False


def record_submission_attempt(ip: str | None = None, quote: str | None = None) -> None:
    ip = ip or get_client_ip()
    now = time.time()
    with _lock:
        entries = _prune_timestamps(_submissions_by_ip.get(ip, []), now, RATE_LIMIT_WINDOW_SECONDS)
        entries.append(now)
        _submissions_by_ip[ip] = entries
        if quote:
            _recent_quote_hashes[_quote_hash(quote)] = now
        cutoff = now - DUPLICATE_WINDOW_SECONDS
        stale = [k for k, ts in _recent_quote_hashes.items() if ts < cutoff]
        for k in stale:
            del _recent_quote_hashes[k]


def score_testimonial_submission(
    *,
    quote: str,
    author_name: str,
    organization: str | None,
    source: str = "homepage",
) -> tuple[int, list[str]]:
    score = 0
    reasons: list[str] = []
    quote = quote or ""
    author_name = (author_name or "").strip()
    organization = (organization or "").strip()

    if URL_PAT.search(quote):
        score += 3
        reasons.append("url_or_html")
    if len(re.findall(r"https?://", quote, flags=re.I)) >= 2:
        score += 2
        reasons.append("multi_url")

    if SPAM_WORDS.search(quote) or SPAM_WORDS.search(author_name):
        score += 5
        reasons.append("spam_keyword")

    if organization and author_name.lower() == organization.lower():
        score += 2
        reasons.append("name_eq_org")

    if GIBBERISH_NAME.match(author_name):
        score += 2
        reasons.append("suspicious_name")

    if "nhtours.com" in quote.lower() and len(quote) < 120:
        score += 2
        reasons.append("domain_stuffing")

    if source == "homepage" and not organization:
        score += 1
        reasons.append("no_org_homepage")

    return score, reasons


def evaluate_testimonial_spam(
    data: dict,
    *,
    source: str = "homepage",
    ip: str | None = None,
) -> tuple[SpamAction, int, list[str]]:
    if not is_spam_filter_enabled():
        return SpamAction.ALLOW, 0, []

    ip = ip or get_client_ip()
    now = time.time()
    honeypot = (data.get("website") or data.get("company_url") or "").strip()
    if honeypot:
        return SpamAction.DROP_SILENT, 99, ["honeypot"]

    quote = (data.get("quote") or data.get("comments") or "").strip()
    author_name = (data.get("author_name") or "").strip()
    if not author_name:
        first = (data.get("firstName") or data.get("first_name") or "").strip()
        last = (data.get("lastName") or data.get("last_name") or "").strip()
        author_name = f"{first} {last}".strip()
    organization = (data.get("organization") or "").strip() or None

    if _is_rate_limited(ip, now):
        return SpamAction.DROP_SILENT, 99, ["rate_limit"]
    if _is_duplicate_quote(quote, now):
        return SpamAction.DROP_SILENT, 99, ["duplicate_quote"]

    score, reasons = score_testimonial_submission(
        quote=quote,
        author_name=author_name,
        organization=organization,
        source=source,
    )
    reject_at, drop_at = _thresholds(source)
    if score >= drop_at:
        record_submission_attempt(ip=ip, quote=quote)
        return SpamAction.DROP_SILENT, score, reasons
    if score >= reject_at:
        record_submission_attempt(ip=ip, quote=quote)
        return SpamAction.REJECT_SILENT, score, reasons
    record_submission_attempt(ip=ip, quote=quote)
    return SpamAction.ALLOW, score, reasons


def log_spam_decision(action: SpamAction, *, source: str, score: int, reasons: list[str]) -> None:
    event = {
        SpamAction.DROP_SILENT: "testimonial_spam_dropped",
        SpamAction.REJECT_SILENT: "testimonial_spam_rejected",
    }.get(action)
    if not event:
        return
    log_security_event(
        event,
        ip=get_client_ip(),
        source=source,
        score=score,
        reasons=reasons,
    )


def reset_spam_state_for_tests() -> None:
    """Clear in-memory rate-limit / dedupe state (tests only)."""
    with _lock:
        _submissions_by_ip.clear()
        _recent_quote_hashes.clear()
