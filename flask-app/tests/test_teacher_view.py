"""Teacher read-only roster: slug auth, reset invalidates old link."""

import pytest

from app import db
from app.models import Trip
from app.trip_roster import ensure_teacher_view_slug, reset_teacher_view_slug


def test_invalid_teacher_slug_404(client):
    rv = client.get('/teacher/trips/not-a-real-slug-zzzz')
    assert rv.status_code == 404


def test_teacher_roster_ok_and_reset_invalidates(app, client):
    with app.app_context():
        trip = Trip.query.filter(Trip.title.isnot(None)).order_by(Trip.id.asc()).first()
        if not trip:
            pytest.skip('no trip fixture')
        old = ensure_teacher_view_slug(trip)
        db.session.commit()
        trip_id = trip.id

    rv = client.get(f'/teacher/trips/{old}')
    assert rv.status_code == 200
    body = rv.get_data(as_text=True)
    assert 'Bookings' in body
    assert 'Participants' in body
    assert 'Manual Booking' not in body
    assert 'Download Excel' not in body
    assert 'Gross amount' not in body

    with app.app_context():
        trip = db.session.get(Trip, trip_id)
        new = reset_teacher_view_slug(trip)
        db.session.commit()
        assert new != old

    assert client.get(f'/teacher/trips/{old}').status_code == 404
    assert client.get(f'/teacher/trips/{new}').status_code == 200
