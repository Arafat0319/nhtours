"""Business order numbers: YYMM{ABBR}-{SEQ} e.g. 2607MT-001."""

from __future__ import annotations

import re
from datetime import datetime

from flask import current_app

# English stop / filler words ignored when building abbreviation
_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'of', 'for', 'to', 'in', 'on', 'at', 'by', 'and', 'or',
    'with', 'from', 'into', 'onto', 'over', 'under', 'vs', 'vs.', 'via',
    'our', 'your', 'its', 'this', 'that', 'these', 'those',
})

_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_WORD_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+", re.UNICODE)


def _pinyin_initial(char: str) -> str | None:
    """First letter of pinyin for a CJK character; None if unavailable."""
    try:
        from pypinyin import Style, lazy_pinyin
    except ImportError:
        return None
    parts = lazy_pinyin(char, style=Style.FIRST_LETTER, errors='ignore')
    if parts and parts[0]:
        letter = parts[0][0].upper()
        if 'A' <= letter <= 'Z':
            return letter
    return None


def _word_initial(word: str) -> str | None:
    """Initial letter for one token (English or Chinese)."""
    if not word:
        return None
    if word.isdigit():
        return None
    lower = word.lower()
    if lower in _STOP_WORDS:
        return None

    if _CJK_RE.search(word):
        for ch in word:
            if _CJK_RE.match(ch):
                init = _pinyin_initial(ch)
                if init:
                    return init
        # Fallback without pypinyin: skip CJK token
        return None

    for ch in word:
        if ch.isalpha():
            return ch.upper()
    return None


def suggest_base_abbr(title: str) -> str:
    """
    Suggest 2-letter base abbreviation from trip title
    (first two content-word initials). Falls back to 'XX'.
    """
    if not title or not str(title).strip():
        return 'XX'

    initials = []
    for match in _WORD_RE.finditer(str(title)):
        init = _word_initial(match.group(0))
        if init:
            initials.append(init)
        if len(initials) >= 2:
            break

    if len(initials) >= 2:
        return ''.join(initials[:2])
    if len(initials) == 1:
        return (initials[0] + 'X')[:2]
    return 'XX'


def normalize_trip_abbr(raw: str | None) -> str:
    """Normalize user/admin abbr to 2–4 alphanumeric uppercase chars."""
    if not raw:
        return ''
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(raw)).upper()
    return cleaned[:4]


def parse_trip_abbr_input(raw: str | None) -> str:
    """
    Accept letter-only abbr (SS) or display form with start YYMM (2609SS).
    Returns the 2–4 char letter/digit code stored on Trip.trip_abbr.
    """
    if not raw:
        return ''
    cleaned = re.sub(r'[^A-Za-z0-9]', '', str(raw)).upper()
    # YYMM + abbr (e.g. 2609SS / 2609SS2)
    m = re.match(r'^(\d{4})([A-Z0-9]{2,4})$', cleaned)
    if m:
        return m.group(2)
    # Digits prefix then letters (partial typing)
    m2 = re.match(r'^\d{4}([A-Z0-9]+)$', cleaned)
    if m2:
        return m2.group(1)[:4]
    return cleaned[:4]


def ensure_unique_trip_abbr(base: str, exclude_trip_id: int | None = None) -> str:
    """
    Make abbr unique across trips: MT → MT2 → MT3 …
    Base should already be normalized (letters/digits).
    """
    from app.models import Trip

    base = normalize_trip_abbr(base) or 'XX'
    if len(base) < 2:
        base = (base + 'XX')[:2]

    candidate = base
    n = 2
    while True:
        q = Trip.query.filter(Trip.trip_abbr == candidate)
        if exclude_trip_id is not None:
            q = q.filter(Trip.id != exclude_trip_id)
        if q.first() is None:
            return candidate
        # Append / bump numeric suffix while staying within 4 chars
        suffix = str(n)
        max_base_len = 4 - len(suffix)
        if max_base_len < 1:
            # Extremely unlikely collision storm
            candidate = f"X{n}"[-4:]
        else:
            candidate = f"{base[:max_base_len]}{suffix}"
        n += 1
        if n > 9999:
            raise RuntimeError(f'Unable to allocate unique trip_abbr from base={base!r}')


def suggest_trip_abbr(title: str, exclude_trip_id: int | None = None) -> str:
    """Suggest a globally unique trip abbreviation from title."""
    return ensure_unique_trip_abbr(suggest_base_abbr(title), exclude_trip_id=exclude_trip_id)


def ensure_trip_abbr(trip) -> str:
    """Ensure trip.trip_abbr is set (does not commit)."""
    if trip.trip_abbr:
        return trip.trip_abbr
    trip.trip_abbr = suggest_trip_abbr(trip.title or '', exclude_trip_id=trip.id)
    return trip.trip_abbr


def allocate_order_number(trip) -> tuple[str, int]:
    """
    Allocate next order number for a trip inside the current transaction.
    Locks the trip row (SELECT … FOR UPDATE). Returns (order_number, seq).
    """
    from app.models import Trip

    locked = (
        Trip.query.filter_by(id=trip.id)
        .with_for_update()
        .one()
    )
    ensure_trip_abbr(locked)

    seq = locked.next_order_seq if locked.next_order_seq is not None else 1
    if seq < 1:
        seq = 1
    locked.next_order_seq = seq + 1

    if locked.start_date:
        yymm = locked.start_date.strftime('%y%m')
    else:
        yymm = datetime.utcnow().strftime('%y%m')
        try:
            current_app.logger.warning(
                'Trip %s has no start_date; using current month %s for order_number',
                locked.id,
                yymm,
            )
        except RuntimeError:
            pass

    order_number = f"{yymm}{locked.trip_abbr}-{seq:03d}"
    # Keep caller's in-memory object in sync when it's a different instance
    if trip is not locked:
        trip.trip_abbr = locked.trip_abbr
        trip.next_order_seq = locked.next_order_seq

    return order_number, seq


def assign_order_number(booking, trip=None) -> str | None:
    """
    Assign order_number/order_seq to a Booking once. Idempotent if already set.
    Call after booking is flushed into the same transaction (trip_id required).
    """
    if getattr(booking, 'order_number', None):
        return booking.order_number

    from app.models import Trip

    trip = trip or getattr(booking, 'trip', None)
    if trip is None and booking.trip_id:
        trip = Trip.query.get(booking.trip_id)
    if trip is None:
        try:
            current_app.logger.error(
                'Cannot assign order_number: booking %s has no trip',
                getattr(booking, 'id', None),
            )
        except RuntimeError:
            pass
        return None

    order_number, seq = allocate_order_number(trip)
    booking.order_number = order_number
    booking.order_seq = seq
    return order_number


def display_order_number(booking) -> str:
    """Public-facing order number; falls back to internal id if missing."""
    return getattr(booking, 'order_number', None) or str(booking.id)
