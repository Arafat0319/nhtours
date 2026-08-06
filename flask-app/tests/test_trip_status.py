"""Tests for trip lifecycle: draft / unpublished / published + list buckets."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from app.trip_status import (
    copy_trip_status,
    get_trip_publish_gaps,
    publish_trip,
    resolve_trips_filter,
    sync_trip_lifecycle,
    trip_list_bucket,
    unpublish_trip,
)


class _PkgQuery:
    def __init__(self, n):
        self._n = n

    def count(self):
        return self._n


def _trip(**kwargs):
    t = SimpleNamespace(
        title='Mark Twain',
        start_date=date.today() + timedelta(days=30),
        end_date=date.today() + timedelta(days=40),
        destination_text='Hainan',
        description='<p>About this trip with real text</p>',
        packages=_PkgQuery(1),
        status='draft',
        is_published=False,
    )
    for k, v in kwargs.items():
        setattr(t, k, v)
    return t


def test_resolve_filter_aliases():
    assert resolve_trips_filter('upcoming') == 'future'
    assert resolve_trips_filter('deactivated') == 'unpublished'
    assert resolve_trips_filter('in_progress') == 'in_progress'
    assert resolve_trips_filter('nope') == 'future'


def test_gaps_detect_empty_quill():
    t = _trip(description='<p><br></p>', packages=_PkgQuery(0))
    gaps = get_trip_publish_gaps(t)
    assert 'description' in gaps
    assert 'packages' in gaps


def test_sync_complete_draft_becomes_unpublished_not_published():
    t = _trip(status='draft')
    ok, demoted = sync_trip_lifecycle(t, commit=False)
    assert ok is True
    assert demoted is False
    assert t.status == 'unpublished'
    assert t.is_published is False


def test_sync_incomplete_published_demotes_to_draft():
    t = _trip(status='published', is_published=True, packages=_PkgQuery(0))
    ok, demoted = sync_trip_lifecycle(t, commit=False)
    assert ok is False
    assert demoted is True
    assert t.status == 'draft'
    assert t.is_published is False


def test_publish_only_from_unpublished():
    t = _trip(status='draft')
    ok, msg = publish_trip(t)
    assert ok is False

    t2 = _trip(status='unpublished')
    ok, msg = publish_trip(t2)
    assert ok is True
    assert t2.status == 'published'
    assert t2.is_published is True


def test_unpublish_to_unpublished():
    t = _trip(status='published', is_published=True)
    ok, msg = unpublish_trip(t)
    assert ok is True
    assert t.status == 'unpublished'
    assert t.is_published is False


def test_copy_status_rules():
    assert copy_trip_status(_trip(status='draft')) == 'draft'
    assert copy_trip_status(_trip(status='unpublished')) == 'unpublished'
    assert copy_trip_status(_trip(status='published')) == 'unpublished'
    assert copy_trip_status(_trip(status='deactivated')) == 'unpublished'


def test_list_buckets_by_date():
    today = date(2026, 8, 6)
    assert trip_list_bucket(_trip(status='draft'), today) == 'draft'
    assert trip_list_bucket(_trip(status='unpublished'), today) == 'unpublished'
    assert trip_list_bucket(
        _trip(status='published', start_date=date(2026, 9, 1), end_date=date(2026, 9, 10)),
        today,
    ) == 'future'
    assert trip_list_bucket(
        _trip(status='published', start_date=date(2026, 8, 1), end_date=date(2026, 8, 20)),
        today,
    ) == 'in_progress'
    assert trip_list_bucket(
        _trip(status='published', start_date=date(2026, 7, 1), end_date=date(2026, 7, 20)),
        today,
    ) == 'past'


def test_legacy_deactivated_normalize(app):
    with app.app_context():
        from app import db
        from app.models import Trip

        trip = Trip.query.filter_by(id=3).first()
        if not trip:
            pytest.skip('no trip 3')
        original = trip.status
        trip.status = 'deactivated'
        db.session.commit()
        sync_trip_lifecycle(trip, commit=True)
        assert trip.status in ('unpublished', 'draft')
        assert trip.is_published is False
        # restore
        trip.status = original if original in ('draft', 'unpublished', 'published') else 'unpublished'
        if original == 'published':
            trip.is_published = True
        db.session.commit()
