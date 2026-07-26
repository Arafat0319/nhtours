"""Add trip_abbr / next_order_seq and booking order_number; backfill existing rows.

Revision ID: add_booking_order_numbers
Revises: add_testimonial_feedback_fields
Create Date: 2026-07-26 00:00:00.000000

"""
import re
from datetime import datetime

import sqlalchemy as sa
from alembic import op

revision = "add_booking_order_numbers"
down_revision = "add_testimonial_feedback_fields"
branch_labels = None
depends_on = None

_STOP_WORDS = frozenset({
    'a', 'an', 'the', 'of', 'for', 'to', 'in', 'on', 'at', 'by', 'and', 'or',
    'with', 'from', 'into', 'onto', 'over', 'under', 'vs', 'vs.', 'via',
    'our', 'your', 'its', 'this', 'that', 'these', 'those',
})
_CJK_RE = re.compile(r'[\u4e00-\u9fff]')
_WORD_RE = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+", re.UNICODE)


def _pinyin_initial(char):
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


def _word_initial(word):
    if not word or word.isdigit():
        return None
    if word.lower() in _STOP_WORDS:
        return None
    if _CJK_RE.search(word):
        for ch in word:
            if _CJK_RE.match(ch):
                init = _pinyin_initial(ch)
                if init:
                    return init
        return None
    for ch in word:
        if ch.isalpha():
            return ch.upper()
    return None


def _suggest_base_abbr(title):
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


def _unique_abbr(base, used):
    base = re.sub(r'[^A-Za-z0-9]', '', base or '').upper() or 'XX'
    if len(base) < 2:
        base = (base + 'XX')[:2]
    candidate = base
    n = 2
    while candidate in used:
        suffix = str(n)
        max_base_len = max(1, 4 - len(suffix))
        candidate = f"{base[:max_base_len]}{suffix}"
        n += 1
        if n > 9999:
            raise RuntimeError('abbr collision overflow')
    used.add(candidate)
    return candidate


def upgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    trip_cols = {c["name"] for c in inspector.get_columns("trips")}
    booking_cols = {c["name"] for c in inspector.get_columns("bookings")}

    if "trip_abbr" not in trip_cols:
        op.add_column("trips", sa.Column("trip_abbr", sa.String(length=8), nullable=True))
        op.create_index(op.f("ix_trips_trip_abbr"), "trips", ["trip_abbr"], unique=False)
    if "next_order_seq" not in trip_cols:
        op.add_column(
            "trips",
            sa.Column("next_order_seq", sa.Integer(), nullable=False, server_default="1"),
        )

    if "order_number" not in booking_cols:
        op.add_column("bookings", sa.Column("order_number", sa.String(length=32), nullable=True))
    if "order_seq" not in booking_cols:
        op.add_column("bookings", sa.Column("order_seq", sa.Integer(), nullable=True))

    # --- data backfill ---
    trips = conn.execute(
        sa.text("SELECT id, title, start_date, trip_abbr FROM trips")
    ).fetchall()
    used_abbrs = set()
    for row in trips:
        abbr = row.trip_abbr
        if abbr:
            used_abbrs.add(abbr.upper())

    trip_abbr_map = {}
    for row in trips:
        tid, title, start_date, existing = row.id, row.title, row.start_date, row.trip_abbr
        if existing:
            abbr = existing.upper()
        else:
            abbr = _unique_abbr(_suggest_base_abbr(title), used_abbrs)
            conn.execute(
                sa.text("UPDATE trips SET trip_abbr = :abbr WHERE id = :id"),
                {"abbr": abbr, "id": tid},
            )
        trip_abbr_map[tid] = (abbr, start_date)

    bookings = conn.execute(
        sa.text(
            "SELECT id, trip_id, created_at, order_number FROM bookings "
            "ORDER BY trip_id ASC, created_at ASC, id ASC"
        )
    ).fetchall()

    # Group by trip
    by_trip = {}
    for b in bookings:
        by_trip.setdefault(b.trip_id, []).append(b)

    for trip_id, blist in by_trip.items():
        abbr, start_date = trip_abbr_map.get(trip_id, ('XX', None))
        if start_date:
            if hasattr(start_date, 'strftime'):
                yymm = start_date.strftime('%y%m')
            else:
                # string fallback
                yymm = str(start_date).replace('-', '')[2:6]
        else:
            yymm = datetime.utcnow().strftime('%y%m')

        seq = 0
        for b in blist:
            if b.order_number:
                # Keep existing; advance seq past parsed trailing number if possible
                m = re.search(r'-(\d+)$', b.order_number)
                if m:
                    seq = max(seq, int(m.group(1)))
                continue
            seq += 1
            order_number = f"{yymm}{abbr}-{seq:03d}"
            # Extremely defensive uniqueness if collision
            while True:
                exists = conn.execute(
                    sa.text("SELECT 1 FROM bookings WHERE order_number = :on LIMIT 1"),
                    {"on": order_number},
                ).fetchone()
                if not exists:
                    break
                seq += 1
                order_number = f"{yymm}{abbr}-{seq:03d}"
            conn.execute(
                sa.text(
                    "UPDATE bookings SET order_number = :on, order_seq = :seq WHERE id = :id"
                ),
                {"on": order_number, "seq": seq, "id": b.id},
            )

        next_seq = seq + 1
        conn.execute(
            sa.text("UPDATE trips SET next_order_seq = :ns WHERE id = :id"),
            {"ns": next_seq, "id": trip_id},
        )

    # Trips with no bookings still need next_order_seq = 1 (default already)
    for tid, (abbr, _) in trip_abbr_map.items():
        if tid not in by_trip:
            conn.execute(
                sa.text("UPDATE trips SET next_order_seq = 1 WHERE id = :id AND (next_order_seq IS NULL OR next_order_seq < 1)"),
                {"id": tid},
            )

    # Unique index on order_number (nullable unique: multiple NULLs ok in MySQL)
    booking_indexes = {ix["name"] for ix in inspector.get_indexes("bookings")}
    # Re-inspect after column add
    inspector = sa.inspect(conn)
    booking_indexes = {ix["name"] for ix in inspector.get_indexes("bookings")}
    if "ix_bookings_order_number" not in booking_indexes and "order_number" in {
        c["name"] for c in inspector.get_columns("bookings")
    }:
        op.create_index(
            op.f("ix_bookings_order_number"),
            "bookings",
            ["order_number"],
            unique=True,
        )


def downgrade():
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    booking_indexes = {ix["name"] for ix in inspector.get_indexes("bookings")}
    booking_cols = {c["name"] for c in inspector.get_columns("bookings")}
    trip_cols = {c["name"] for c in inspector.get_columns("trips")}
    trip_indexes = {ix["name"] for ix in inspector.get_indexes("trips")}

    if "ix_bookings_order_number" in booking_indexes:
        op.drop_index(op.f("ix_bookings_order_number"), table_name="bookings")
    if "order_seq" in booking_cols:
        op.drop_column("bookings", "order_seq")
    if "order_number" in booking_cols:
        op.drop_column("bookings", "order_number")
    if "ix_trips_trip_abbr" in trip_indexes:
        op.drop_index(op.f("ix_trips_trip_abbr"), table_name="trips")
    if "next_order_seq" in trip_cols:
        op.drop_column("trips", "next_order_seq")
    if "trip_abbr" in trip_cols:
        op.drop_column("trips", "trip_abbr")
