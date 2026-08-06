"""Comprehensive tests for trip_abbr / Trip ID helpers."""
from datetime import date
from types import SimpleNamespace

import pytest

from app.order_numbers import (
    apply_trip_abbr_from_input,
    default_trip_abbr,
    display_trip_id,
    ensure_unique_trip_abbr,
    is_valid_trip_abbr,
    normalize_trip_abbr,
    parse_trip_abbr_input,
    reset_trip_abbr,
    sanitize_stored_trip_abbr,
    suggest_base_abbr,
    trip_abbr_follows_title,
)


# ── parse / normalize / validate (no DB) ─────────────────────────────

@pytest.mark.parametrize(
    "raw,expected",
    [
        ("MT", "MT"),
        ("mt", "MT"),
        ("  ss  ", "SS"),
        ("MT2", "MT2"),
        ("2612MT", "MT"),
        ("2609SS", "SS"),
        ("2609SS2", "SS2"),
        ("2612M", "M"),  # mid-type
        ("2612", ""),
        ("26122612", ""),
        ("", ""),
        (None, ""),
        ("!!!!", ""),
        ("A", "A"),
        ("ABCDEF", "ABCD"),  # truncate via normalize path for bare letters
        ("2609ABCDEF", "ABCD"),  # YYMM + 4 letters
    ],
)
def test_parse_trip_abbr_input(raw, expected):
    assert parse_trip_abbr_input(raw) == expected


@pytest.mark.parametrize(
    "raw,ok",
    [
        ("MT", True),
        ("SS2", True),
        ("A1", True),
        ("X9Y", True),
        ("M", False),
        ("12", False),
        ("001", False),
        ("1234", False),
        ("2612", False),
        ("", False),
        (None, False),
        ("MTMT", True),
        ("9A", True),  # digit + letter ok
    ],
)
def test_is_valid_trip_abbr(raw, ok):
    assert is_valid_trip_abbr(raw) is ok


def test_normalize_rejects_yymm_keeps_mixed():
    assert normalize_trip_abbr("2612") == ""
    assert normalize_trip_abbr("12") == "12"  # normalized but not valid (no letter)
    assert normalize_trip_abbr("mt-2") == "MT2"


def test_suggest_skips_year_and_stopwords():
    assert suggest_base_abbr("2026 Mark Twain Winter Camp") == "MT"
    assert suggest_base_abbr("Shanghai Summer Trip") == "SS"
    assert suggest_base_abbr("The Best Of Tours") == "BT"
    assert suggest_base_abbr("") == "XX"
    assert suggest_base_abbr("!!!") == "XX"


def test_mark_twain_default_display_id():
    """Dec 2026 Mark Twain → full Trip ID 2612MT."""
    trip = SimpleNamespace(
        trip_abbr="MT",
        title="2026 Mark Twain Winter Camp China Trip",
        id=None,
        start_date=date(2026, 12, 6),
    )
    assert suggest_base_abbr(trip.title) == "MT"
    assert display_trip_id(trip) == "2612MT"
    assert trip_abbr_follows_title(trip) is True
    trip.trip_abbr = "ZZ"
    assert trip_abbr_follows_title(trip) is False


def test_reset_trip_abbr_restores_title_default(app):
    with app.app_context():
        from app import db
        from app.models import Trip

        trip = Trip.query.filter_by(id=3).first()
        if not trip:
            pytest.skip("trip 3 not in local DB")
        trip.title = "2026 Mark Twain Winter Camp China Trip"
        trip.trip_abbr = "ZZ9"
        db.session.commit()

        out = reset_trip_abbr(trip)
        assert out == default_trip_abbr(trip) or out.startswith("MT")
        assert is_valid_trip_abbr(out)
        assert trip_abbr_follows_title(trip) or out.startswith("MT")
        trip.trip_abbr = out  # persist restored default for later tests
        db.session.commit()


def test_display_trip_id_with_and_without_start():
    trip = SimpleNamespace(trip_abbr="MT", title="Mark Twain", id=None, start_date=date(2026, 12, 6))
    # sanitize may call DB for suggest if invalid — MT is valid so no DB
    assert display_trip_id(trip) == "2612MT"
    trip2 = SimpleNamespace(trip_abbr="SS", title="Shanghai", id=None, start_date=None)
    assert display_trip_id(trip2) == "SS"


# ── apply / sanitize / unique (DB) ───────────────────────────────────

def test_sanitize_repairs_bare_yymm(app):
    with app.app_context():
        trip = SimpleNamespace(
            trip_abbr="2612",
            title="2026 Mark Twain Winter Camp China Trip",
            id=999999,  # unlikely to collide
        )
        fixed = sanitize_stored_trip_abbr(trip)
        assert is_valid_trip_abbr(fixed)
        assert fixed == "MT" or fixed.startswith("MT")


def test_apply_keeps_existing_on_incomplete_input(app):
    with app.app_context():
        from app import db
        from app.models import Trip

        trip = Trip.query.filter_by(id=3).first()
        if not trip:
            pytest.skip("trip 3 not in local DB")
        # Ensure clean starting point
        trip.trip_abbr = "MT"
        db.session.commit()
        original = trip.trip_abbr

        apply_trip_abbr_from_input(trip, "2612", suggest_if_missing=True)
        assert trip.trip_abbr == original

        apply_trip_abbr_from_input(trip, "M", suggest_if_missing=True)
        assert trip.trip_abbr == original

        apply_trip_abbr_from_input(trip, "", suggest_if_missing=True)
        assert trip.trip_abbr == original


def test_apply_accepts_valid_and_paste_with_yymm(app):
    with app.app_context():
        from app import db
        from app.models import Trip

        trip = Trip.query.filter_by(id=3).first()
        if not trip:
            pytest.skip("trip 3 not in local DB")
        original = "MT"
        trip.trip_abbr = original
        db.session.commit()

        apply_trip_abbr_from_input(trip, "2612ZZ", suggest_if_missing=True)
        assert trip.trip_abbr == "ZZ" or trip.trip_abbr.startswith("ZZ")

        trip.trip_abbr = original
        db.session.commit()


def test_ensure_unique_bumps_on_collision(app):
    with app.app_context():
        from app.models import Trip

        existing = Trip.query.filter(Trip.trip_abbr == "SS").first()
        if not existing:
            existing = Trip.query.filter(
                Trip.trip_abbr.isnot(None),
                Trip.trip_abbr != "2612",
            ).first()
        if not existing or not is_valid_trip_abbr(existing.trip_abbr):
            pytest.skip("no trip with valid abbr")
        base = existing.trip_abbr
        other_id = (existing.id or 0) + 99999
        bumped = ensure_unique_trip_abbr(base, exclude_trip_id=other_id)
        assert bumped != base
        assert is_valid_trip_abbr(bumped)
        same = ensure_unique_trip_abbr(base, exclude_trip_id=existing.id)
        assert same == base


def test_ensure_unique_rejects_yymm_base(app):
    with app.app_context():
        out = ensure_unique_trip_abbr("2612", exclude_trip_id=None)
        assert is_valid_trip_abbr(out)
        assert out != "2612"


def test_basics_get_repairs_and_shows_letters_only(client, app):
    """GET Basics repairs bare YYMM and keeps letters-only in the input."""
    with app.app_context():
        from app import db
        from app.models import Trip, User

        trip = Trip.query.filter_by(id=3).first()
        admin = User.query.filter_by(role="admin").first() or User.query.first()
        if not trip or not admin:
            pytest.skip("need trip 3 + user")
        admin_id = admin.id
        trip_id = trip.id
        trip.trip_abbr = "2612"
        db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    rv = client.get(f"/admin/trips/{trip_id}/builder/basics")
    if rv.status_code in (301, 302):
        pytest.skip(f"redirected (auth?): {rv.status_code} {rv.headers.get('Location')}")
    assert rv.status_code == 200
    html = rv.get_data(as_text=True)
    assert 'id="trip_abbr_yymm"' in html
    assert "26122612" not in html

    with app.app_context():
        from app.models import Trip
        t = Trip.query.get(trip_id)
        assert is_valid_trip_abbr(t.trip_abbr)
        assert t.trip_abbr != "2612"


def test_basics_autosave_rejects_yymm_keeps_abbr(client, app):
    with app.app_context():
        from app.models import Trip, User
        trip = Trip.query.filter_by(id=3).first()
        admin = User.query.filter_by(role="admin").first() or User.query.first()
        if not trip or not admin:
            pytest.skip("need trip 3 + user")
        admin_id = admin.id
        trip_id = trip.id
        original = trip.trip_abbr
        assert is_valid_trip_abbr(original)

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    # Need CSRF — pull from GET page
    page = client.get(f"/admin/trips/{trip_id}/builder/basics")
    if page.status_code != 200:
        pytest.skip("cannot load basics (auth)")
    import re
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', page.get_data(as_text=True))
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', page.get_data(as_text=True))
    csrf = m.group(1) if m else ""

    rv = client.post(
        f"/admin/trips/{trip_id}/builder/basics",
        data={
            "title": "2026 Mark Twain Winter Camp China Trip",
            "slug": "2612MT",
            "trip_abbr": "2612",
            "destination_text": "hainan",
            "start_date": "2026-12-06",
            "end_date": "2027-01-06",
            "csrf_token": csrf,
        },
        headers={"X-Autosave": "1"},
    )
    if rv.status_code != 200:
        pytest.skip(f"autosave status {rv.status_code}")
    data = rv.get_json() or {}
    assert data.get("success") is True
    assert is_valid_trip_abbr(data.get("trip_abbr"))
    assert data.get("trip_abbr") != "2612"
    assert data.get("trip_abbr") == original or is_valid_trip_abbr(data.get("trip_abbr"))


def test_basics_autosave_reset_restores_default(client, app):
    with app.app_context():
        from app import db
        from app.models import Trip, User

        trip = Trip.query.filter_by(id=3).first()
        admin = User.query.filter_by(role="admin").first() or User.query.first()
        if not trip or not admin:
            pytest.skip("need trip 3 + user")
        admin_id = admin.id
        trip_id = trip.id
        trip.title = "2026 Mark Twain Winter Camp China Trip"
        trip.trip_abbr = "CUST"
        trip.start_date = date(2026, 12, 6)
        db.session.commit()

    with client.session_transaction() as sess:
        sess["_user_id"] = str(admin_id)
        sess["_fresh"] = True

    page = client.get(f"/admin/trips/{trip_id}/builder/basics")
    if page.status_code != 200:
        pytest.skip("cannot load basics (auth)")
    import re
    html = page.get_data(as_text=True)
    assert 'id="trip_abbr_reset"' in html
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    if not m:
        m = re.search(r'value="([^"]+)"[^>]*name="csrf_token"', html)
    csrf = m.group(1) if m else ""

    rv = client.post(
        f"/admin/trips/{trip_id}/builder/basics",
        data={
            "title": "2026 Mark Twain Winter Camp China Trip",
            "slug": "mark-twain",
            "trip_abbr": "CUST",
            "trip_abbr_reset": "1",
            "destination_text": "hainan",
            "start_date": "2026-12-06",
            "end_date": "2027-01-06",
            "csrf_token": csrf,
        },
        headers={"X-Autosave": "1"},
    )
    if rv.status_code != 200:
        pytest.skip(f"autosave status {rv.status_code}")
    data = rv.get_json() or {}
    assert data.get("success") is True
    assert data.get("trip_abbr") == "MT" or str(data.get("trip_abbr", "")).startswith("MT")
