"""Product package: validate full vs installment against payment_plan_config."""

from types import SimpleNamespace

from app.payments import booking_payment_type_display, validate_package_payment_plan_type


def _pkg(name='Student', enabled=True, allow_full=True):
    return SimpleNamespace(
        name=name,
        payment_plan_config={
            'enabled': enabled,
            'allow_full_payment': allow_full,
            'deposit_amount': 500,
            'installments': [{'date': '2026-09-01', 'amount': 1500}],
        },
    )


def test_validate_full_when_plan_offers_both():
    plan, err = validate_package_payment_plan_type(_pkg(), 'full')
    assert err is None
    assert plan == 'full'


def test_validate_installment_when_enabled():
    plan, err = validate_package_payment_plan_type(_pkg(), 'deposit_installment')
    assert err is None
    assert plan == 'deposit_installment'


def test_validate_rejects_installment_when_disabled():
    plan, err = validate_package_payment_plan_type(_pkg(enabled=False), 'deposit_installment')
    assert plan is None
    assert err and 'does not offer installment' in err


def test_validate_rejects_full_when_allow_full_false():
    plan, err = validate_package_payment_plan_type(_pkg(allow_full=False), 'full')
    assert plan is None
    assert err and 'requires installment' in err


def test_validate_legacy_missing_allow_full_defaults_true():
    pkg = SimpleNamespace(
        name='Legacy',
        payment_plan_config={'enabled': True, 'deposit_amount': 100, 'installments': []},
    )
    plan, err = validate_package_payment_plan_type(pkg, 'full')
    assert err is None
    assert plan == 'full'


def test_booking_payment_type_display_mixed():
    booking = SimpleNamespace(
        id=1,
        booking_packages=[
            SimpleNamespace(payment_plan_type='full'),
            SimpleNamespace(payment_plan_type='deposit_installment'),
        ],
    )
    # Avoid DB lookups in booking_payments_plan_kind by short-circuiting mixed first
    display = booking_payment_type_display(booking)
    assert display['key'] == 'mixed'
    assert display['label'] == 'Mixed'
