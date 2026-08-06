"""Trip lifecycle: draft / unpublished / published (+ list buckets by date)."""

from __future__ import annotations

from html import unescape
import re

from app import db


def _trip_description_text(description):
    if not description:
        return ''
    text = re.sub(r'<[^>]+>', ' ', description)
    return ' '.join(unescape(text).split())


def get_trip_publish_gaps(trip):
    """Return missing required-field keys for going live."""
    gaps = []
    if not (trip.title or '').strip():
        gaps.append('title')
    if not trip.start_date:
        gaps.append('start_date')
    if not trip.end_date:
        gaps.append('end_date')
    if not (trip.destination_text or '').strip():
        gaps.append('destination')
    if not _trip_description_text(trip.description):
        gaps.append('description')
    if trip.packages.count() == 0:
        gaps.append('packages')
    return gaps


def gap_labels(gaps):
    labels = {
        'title': 'title',
        'start_date': 'start date',
        'end_date': 'end date',
        'destination': 'destination',
        'description': 'About this Trip (Description)',
        'packages': 'at least one package',
    }
    return [labels.get(g, g) for g in gaps]


def _today():
    from app.utils import pacific_today
    return pacific_today()


def normalize_legacy_status(trip) -> bool:
    """Map legacy deactivated → unpublished/draft. Returns True if changed."""
    if getattr(trip, 'status', None) != 'deactivated':
        return False
    if get_trip_publish_gaps(trip):
        trip.status = 'draft'
        trip.is_published = False
    else:
        trip.status = 'unpublished'
        trip.is_published = False
    return True


def sync_trip_lifecycle(trip, *, commit=False):
    """
    Keep status consistent with required fields.

    - Incomplete → draft (and take offline if was published)
    - Complete + draft/deactivated/legacy → unpublished (never auto-publish)
    - Complete + unpublished/published → leave visibility as-is; sync is_published

    Returns (is_complete: bool, demoted_from_live: bool).
    """
    normalize_legacy_status(trip)
    gaps = get_trip_publish_gaps(trip)
    demoted = False

    if gaps:
        if trip.status == 'published' or trip.is_published:
            demoted = trip.status == 'published'
            trip.status = 'draft'
            trip.is_published = False
        elif trip.status not in ('draft',):
            # unpublished / unknown with gaps → draft
            trip.status = 'draft'
            trip.is_published = False
        else:
            trip.is_published = False
        if commit:
            db.session.commit()
        return False, demoted

    # Complete
    if trip.status in (None, '', 'draft', 'deactivated'):
        trip.status = 'unpublished'
        trip.is_published = False
    elif trip.status == 'unpublished':
        trip.is_published = False
    elif trip.status == 'published':
        trip.is_published = True
    else:
        # Unknown → treat as unpublished when complete
        trip.status = 'unpublished'
        trip.is_published = False

    if commit:
        db.session.commit()
    return True, False


def check_trip_completion(trip):
    """
    Compatibility wrapper used across admin saves.
    Syncs lifecycle and commits. Returns True if required fields are complete
    (status may be unpublished or published — never auto-publishes).
    """
    ok, demoted = sync_trip_lifecycle(trip, commit=True)
    if demoted:
        try:
            from flask import flash
            flash(
                'Trip was taken offline and moved to Draft because required fields are incomplete.',
                'warning',
            )
        except RuntimeError:
            pass
    return ok


def trip_list_bucket(trip, today=None):
    """One of: draft, unpublished, future, in_progress, past."""
    today = today or _today()
    normalize_legacy_status(trip)
    status = trip.status or 'draft'
    if status == 'draft':
        return 'draft'
    if status == 'unpublished':
        return 'unpublished'
    if status == 'published':
        if trip.end_date and trip.end_date < today:
            return 'past'
        if trip.start_date and trip.start_date > today:
            return 'future'
        # started (or missing start) and not ended
        return 'in_progress'
    return 'draft'


def resolve_trips_filter(raw: str | None) -> str:
    """Normalize URL filter aliases."""
    f = (raw or 'future').strip().lower()
    aliases = {
        'upcoming': 'future',  # old bookmark
        'deactivated': 'unpublished',
        'offline': 'unpublished',
        'ready': 'unpublished',
    }
    f = aliases.get(f, f)
    allowed = {'future', 'in_progress', 'past', 'draft', 'unpublished'}
    return f if f in allowed else 'future'


def get_trip_counts(today=None):
    from app.models import Trip

    today = today or _today()
    # Normalize legacy rows opportunistically (no mass commit here)
    return {
        'future': Trip.query.filter(
            Trip.status == 'published',
            Trip.start_date > today,
        ).count(),
        'in_progress': Trip.query.filter(
            Trip.status == 'published',
            Trip.start_date <= today,
            Trip.end_date >= today,
        ).count(),
        'past': Trip.query.filter(
            Trip.status == 'published',
            Trip.end_date < today,
        ).count(),
        'draft': Trip.query.filter(Trip.status == 'draft').count(),
        'unpublished': Trip.query.filter(
            Trip.status.in_(('unpublished', 'deactivated'))
        ).count(),
        # Back-compat keys for any leftover template refs
        'upcoming': Trip.query.filter(
            Trip.status == 'published',
            Trip.end_date >= today,
        ).count(),
        'deactivated': Trip.query.filter(
            Trip.status.in_(('unpublished', 'deactivated'))
        ).count(),
    }


def publish_trip(trip) -> tuple[bool, str]:
    """
    Explicit publish. Returns (ok, message).
    Only unpublished (complete) trips can go live.
    """
    normalize_legacy_status(trip)
    gaps = get_trip_publish_gaps(trip)
    if gaps:
        trip.status = 'draft'
        trip.is_published = False
        return False, (
            'Cannot publish — still needed: ' + ', '.join(gap_labels(gaps)) + '.'
        )
    if trip.status == 'published':
        trip.is_published = True
        return True, 'Trip is already live.'
    if trip.status != 'unpublished':
        return False, 'Only ready (unpublished) trips can be published.'
    trip.status = 'published'
    trip.is_published = True
    bucket = trip_list_bucket(trip)
    hints = {
        'future': 'It appears under Future Trips.',
        'in_progress': 'It appears under In Progress Trips.',
        'past': 'This trip’s dates are already past — it appears under Past Trips.',
    }
    return True, f'Trip published. {hints.get(bucket, "")}'.strip()


def unpublish_trip(trip) -> tuple[bool, str]:
    """Take a live trip offline → unpublished (or draft if incomplete)."""
    normalize_legacy_status(trip)
    if trip.status != 'published' and not trip.is_published:
        return False, 'Trip is not live.'
    gaps = get_trip_publish_gaps(trip)
    if gaps:
        trip.status = 'draft'
        trip.is_published = False
        return True, (
            'Trip taken offline and moved to Draft (required fields incomplete: '
            + ', '.join(gap_labels(gaps))
            + ').'
        )
    trip.status = 'unpublished'
    trip.is_published = False
    return True, 'Trip unpublished. It is under Unpublished Trips.'


def copy_trip_status(source) -> str:
    """Draft copies stay draft; everything else → unpublished."""
    normalize_legacy_status(source)
    if (source.status or 'draft') == 'draft':
        return 'draft'
    return 'unpublished'


def active_booking_count(trip) -> int:
    """Non-cancelled bookings (for Unpublish confirm)."""
    from app.models import Booking

    return Booking.query.filter(
        Booking.trip_id == trip.id,
        Booking.status != 'cancelled',
    ).count()


def migrate_legacy_trip_statuses(*, commit=True) -> int:
    """Repair deactivated/archived only. Does not promote drafts (Copy-as-draft must stick)."""
    from app.models import Trip

    changed = 0
    for trip in Trip.query.filter(Trip.status.in_(('deactivated', 'archived'))).all():
        before = trip.status
        if trip.status == 'archived':
            trip.status = 'deactivated'
        sync_trip_lifecycle(trip, commit=False)
        if trip.status != before:
            changed += 1
    if commit and changed:
        db.session.commit()
    return changed
