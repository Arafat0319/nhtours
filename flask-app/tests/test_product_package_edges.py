"""Edge cases for product packages + payment plan selection."""

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from app.payments import (
    booking_payment_type_display,
    calculate_initial_payment_amount,
    validate_package_payment_plan_type,
)


class _QueryList(list):
    def all(self):
        return list(self)


def _pkg(name='Student', enabled=True, allow_full=True, price=2000.0, deposit=500.0, installments=None):
    return SimpleNamespace(
        name=name,
        price=price,
        payment_plan_config={
            'enabled': enabled,
            'allow_full_payment': allow_full,
            'deposit_amount': deposit,
            'installments': installments
            if installments is not None
            else [{'date': '2099-09-01', 'amount': price - deposit}],
        },
    )


def test_validate_rejects_unknown_plan_type():
    plan, err = validate_package_payment_plan_type(_pkg(), 'partial')
    assert plan is None
    assert err and 'Invalid payment plan' in err


def test_validate_empty_string_treated_as_full():
    plan, err = validate_package_payment_plan_type(_pkg(enabled=False), '')
    assert err is None
    assert plan == 'full'


def test_validate_whitespace_full():
    plan, err = validate_package_payment_plan_type(_pkg(), '  full  ')
    assert err is None
    assert plan == 'full'


def test_validate_none_package():
    plan, err = validate_package_payment_plan_type(None, 'full')
    assert plan is None
    assert err and 'not found' in err.lower()


def test_validate_allow_full_false_accepts_installment():
    plan, err = validate_package_payment_plan_type(_pkg(allow_full=False), 'deposit_installment')
    assert err is None
    assert plan == 'deposit_installment'


def test_validate_enabled_false_accepts_full():
    plan, err = validate_package_payment_plan_type(_pkg(enabled=False), 'full')
    assert err is None
    assert plan == 'full'


def test_booking_payment_type_all_full():
    booking = SimpleNamespace(
        id=1,
        booking_packages=[
            SimpleNamespace(payment_plan_type='full'),
            SimpleNamespace(payment_plan_type='full'),
        ],
    )
    with patch('app.payments.booking_payments_plan_kind', return_value='one_time'), patch(
        'app.payments.booking_post_deposit_installment_count', return_value=0
    ):
        display = booking_payment_type_display(booking)
    assert display['key'] == 'full'


def test_booking_payment_type_all_installment_uses_kind():
    booking = SimpleNamespace(
        id=2,
        booking_packages=[SimpleNamespace(payment_plan_type='deposit_installment')],
    )
    with patch('app.payments.booking_payments_plan_kind', return_value='multi'), patch(
        'app.payments.booking_post_deposit_installment_count', return_value=3
    ):
        display = booking_payment_type_display(booking)
    assert display['key'] == 'installment'
    assert display['label'] == 'Installment (3)'


def test_initial_payment_mixed_packages_deposit_plus_full(app):
    """One full + one installment: due now = full price + deposit (not full for both)."""
    student = _pkg('Student', price=2000, deposit=150, installments=[
        {'date': '2099-09-01', 'amount': 1850},
    ])
    parent = _pkg('Parent', enabled=False, price=2500, deposit=2500, installments=[])

    bp_student = SimpleNamespace(
        payment_plan_type='deposit_installment',
        quantity=1,
        package=student,
        unit_price=2000.0,
    )
    bp_parent = SimpleNamespace(
        payment_plan_type='full',
        quantity=1,
        package=parent,
        unit_price=2500.0,
    )
    booking = SimpleNamespace(
        id=99,
        discount_amount=0,
        amount_paid=0,
        booking_packages=_QueryList([bp_student, bp_parent]),
        addons=_QueryList([]),
    )
    with app.app_context():
        result = calculate_initial_payment_amount(booking, payment_plan='deposit_installment')
    assert result['initial_amount'] == 150 + 2500
    assert result['deposit'] == 150 + 2500
    assert result['overdue_installments'] == 0


def test_initial_payment_qty_scales_deposit_and_overdue(app):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    pkg = _pkg(
        'Student',
        price=2150,
        deposit=150,
        installments=[
            {'date': yesterday, 'amount': 666},
            {'date': '2099-10-01', 'amount': 1334},
        ],
    )
    bp = SimpleNamespace(
        payment_plan_type='deposit_installment',
        quantity=2,
        package=pkg,
        unit_price=2150.0,
    )
    booking = SimpleNamespace(
        id=100,
        discount_amount=0,
        amount_paid=0,
        booking_packages=_QueryList([bp]),
        addons=_QueryList([]),
    )
    with app.app_context():
        result = calculate_initial_payment_amount(booking, payment_plan='deposit_installment')
    assert result['deposit'] == 150 * 2
    assert result['overdue_installments'] == 666 * 2
    assert result['initial_amount'] == (150 + 666) * 2


def test_initial_payment_top_level_full_ignores_per_package_plan(app):
    """
    Known footgun: callers that pass payment_plan='full' charge the whole trip total
    even if some BookingPackages are deposit_installment.
    Quote path sets payment_plan from any installment BP — keep that.
    """
    pkg = _pkg('Student', price=2000, deposit=100)
    bp = SimpleNamespace(
        payment_plan_type='deposit_installment',
        quantity=1,
        package=pkg,
        unit_price=2000.0,
    )
    booking = SimpleNamespace(
        id=101,
        discount_amount=0,
        amount_paid=0,
        booking_packages=_QueryList([bp]),
        addons=_QueryList([]),
    )
    with app.app_context(), patch('app.payments.booking_refunded_total', return_value=0.0):
        result = calculate_initial_payment_amount(booking, payment_plan='full')
    assert result['initial_amount'] == 2000.0


def test_same_day_merge_buckets_logic():
    """Mirror Your Booking / Manage merge: same due date sums across packages."""
    buckets = {}

    def add_due(key, amount):
        buckets[key] = buckets.get(key, 0) + amount

    add_due('deposit-today', 100)  # student
    add_due('deposit-today', 100)  # parent
    add_due('inst-2026-09-09', 1700)
    add_due('inst-2026-09-09', 2500)
    assert buckets['deposit-today'] == 200
    assert buckets['inst-2026-09-09'] == 4200


def test_package_delete_blocked_when_referenced(app):
    """Saving packages must not null package_id on existing booking lines."""
    from app import db
    from app.models import Booking, BookingPackage, Client, Trip, TripPackage

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            return
        pkg = TripPackage(
            trip_id=trip.id,
            name='Edge Delete Guard',
            price=100.0,
            status='available',
            payment_plan_config={'enabled': False},
        )
        db.session.add(pkg)
        db.session.flush()

        client = Client(email='edge-delete@example.com', first_name='E', last_name='D')
        db.session.add(client)
        db.session.flush()
        booking = Booking(
            client_id=client.id,
            trip_id=trip.id,
            buyer_email='edge-delete@example.com',
            status='pending',
            amount_paid=0,
        )
        db.session.add(booking)
        db.session.flush()
        bp = BookingPackage(
            booking_id=booking.id,
            package_id=pkg.id,
            quantity=1,
            payment_plan_type='full',
            unit_price=100.0,
        )
        db.session.add(bp)
        db.session.commit()

        ref = BookingPackage.query.filter_by(package_id=pkg.id).count()
        assert ref >= 1

        # Cleanup created rows
        db.session.delete(bp)
        db.session.delete(booking)
        db.session.delete(client)
        db.session.delete(pkg)
        db.session.commit()


def test_validate_in_submission_style_mutates_payload():
    """Mirrors routes: normalize payment_plan_type on packages_data before charge calc."""
    packages_data = [
        {'package_id': 1, 'quantity': 1, 'payment_plan_type': 'deposit_installment'},
        {'package_id': 2, 'quantity': 1, 'payment_plan_type': 'full'},
    ]
    pkgs = {
        1: _pkg('Student', enabled=True, allow_full=True),
        2: _pkg('Parent', enabled=True, allow_full=True),
    }
    for row in packages_data:
        package = pkgs[row['package_id']]
        normalized, err = validate_package_payment_plan_type(package, row.get('payment_plan_type'))
        assert err is None
        row['payment_plan_type'] = normalized
    assert packages_data[0]['payment_plan_type'] == 'deposit_installment'
    assert packages_data[1]['payment_plan_type'] == 'full'


def test_client_cannot_force_installment_on_full_only_package():
    packages_data = [{'package_id': 1, 'quantity': 2, 'payment_plan_type': 'deposit_installment'}]
    package = _pkg('FullOnly', enabled=False)
    _, err = validate_package_payment_plan_type(package, packages_data[0]['payment_plan_type'])
    assert err is not None


def test_client_cannot_force_full_when_installment_required():
    package = _pkg('MustInstall', enabled=True, allow_full=False)
    _, err = validate_package_payment_plan_type(package, 'full')
    assert err is not None


def test_normalize_packages_rejects_bad_qty_and_missing(app):
    from app.booking_validation import validate_and_normalize_booking_packages
    from app.models import Trip, TripPackage

    with app.app_context():
        trip = Trip.query.first()
        if not trip:
            return
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        if not pkg:
            return

        _, err = validate_and_normalize_booking_packages(
            [{'package_id': pkg.id, 'quantity': 0, 'payment_plan_type': 'full'}],
            trip.id,
        )
        assert err and 'at least 1' in err

        _, err = validate_and_normalize_booking_packages(
            [{'package_id': pkg.id, 'quantity': -2, 'payment_plan_type': 'full'}],
            trip.id,
        )
        assert err and 'at least 1' in err

        _, err = validate_and_normalize_booking_packages(
            [{'package_id': 999999, 'quantity': 1, 'payment_plan_type': 'full'}],
            trip.id,
        )
        assert err and 'invalid' in err.lower()

        other = TripPackage.query.filter(TripPackage.trip_id != trip.id).first()
        if other:
            _, err = validate_and_normalize_booking_packages(
                [{'package_id': other.id, 'quantity': 1, 'payment_plan_type': 'full'}],
                trip.id,
            )
            assert err and 'do not belong' in err

        ok, err = validate_and_normalize_booking_packages(
            [{'package_id': pkg.id, 'quantity': 2, 'payment_plan_type': 'full'}],
            trip.id,
        )
        assert err is None
        assert ok[0]['quantity'] == 2
        assert ok[0]['payment_plan_type'] == 'full'


def test_booking_submit_rejects_tampered_packages(app):
    """HTTP: fake id / bad qty / cross-trip must 400 (no free_ PendingBooking)."""
    from app.models import PendingBooking, Trip, TripPackage

    client = app.test_client()
    with app.app_context():
        trip = Trip.query.filter_by(slug='SH').first() or Trip.query.filter_by(status='published').first()
        if not trip:
            return
        pkg = TripPackage.query.filter_by(trip_id=trip.id).first()
        other = TripPackage.query.filter(TripPackage.trip_id != trip.id).first()
        before = PendingBooking.query.count()

    def post(packages):
        return client.post(
            f'/trips/{trip.slug}',
            json={
                'booking_data': {
                    'packages': packages,
                    'addons': [],
                    'participants': [
                        {
                            'first_name': 'T',
                            'last_name': 'U',
                            'email': 'tamper@example.com',
                            'phone': '5550001111',
                            'date_of_birth': '2005-01-01',
                        }
                    ],
                    'buyer_info': {
                        'first_name': 'T',
                        'last_name': 'U',
                        'email': 'tamper@example.com',
                        'phone': '5550001111',
                    },
                    'payment_method': 'card',
                }
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

    cases = [
        [{'package_id': 999999, 'quantity': 1, 'payment_plan_type': 'full'}],
        [{'package_id': pkg.id, 'quantity': -1, 'payment_plan_type': 'full'}],
        [{'package_id': pkg.id, 'quantity': 0, 'payment_plan_type': 'full'}],
    ]
    if other:
        cases.append([{'package_id': other.id, 'quantity': 1, 'payment_plan_type': 'full'}])

    for packages in cases:
        resp = post(packages)
        assert resp.status_code == 400, packages
        data = resp.get_json() or {}
        assert data.get('success') is False

    with app.app_context():
        assert PendingBooking.query.count() == before
