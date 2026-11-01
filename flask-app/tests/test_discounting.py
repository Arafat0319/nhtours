"""Signup discount: 100% full waive vs package-only + force full pay."""
from types import SimpleNamespace

from app.discounting import (
    compute_signup_discount,
    force_packages_full_pay,
    is_full_waive,
)


def _code(kind, amount):
    return SimpleNamespace(type=kind, amount=amount)


def test_is_full_waive_only_percent_100():
    assert is_full_waive(_code('percent', 100)) is True
    assert is_full_waive(_code('percent', 99)) is False
    assert is_full_waive(_code('fixed', 100)) is False
    assert is_full_waive(None) is False


def test_percent_100_covers_packages_and_addons():
    priced = compute_signup_discount(_code('percent', 100), 4490, 285)
    assert priced['full_waive'] is True
    assert priced['forces_full_pay'] is True
    assert priced['discount_amount'] == 4775
    assert priced['due_amount'] == 0


def test_percent_40_packages_only_addons_remain():
    priced = compute_signup_discount(_code('percent', 40), 4490, 285)
    assert priced['full_waive'] is False
    assert priced['forces_full_pay'] is True
    assert priced['discount_amount'] == 1796
    assert priced['due_amount'] == 2979


def test_fixed_covers_packages_only_like_2703re_004():
    priced = compute_signup_discount(_code('fixed', 2694), 4490, 285)
    assert priced['discount_amount'] == 2694
    assert priced['due_amount'] == 2081
    assert priced['forces_full_pay'] is True
    assert priced['full_waive'] is False


def test_fixed_full_package_leaves_addon_like_2703re_002():
    priced = compute_signup_discount(_code('fixed', 4490), 4490, 285)
    assert priced['discount_amount'] == 4490
    assert priced['due_amount'] == 285
    assert priced['forces_full_pay'] is True


def test_fixed_cannot_eat_addons_when_larger_than_packages():
    priced = compute_signup_discount(_code('fixed', 99999), 4490, 285)
    assert priced['discount_amount'] == 4490
    assert priced['due_amount'] == 285


def test_no_code_due_is_packages_plus_addons():
    priced = compute_signup_discount(None, 4490, 285)
    assert priced['discount_amount'] == 0
    assert priced['due_amount'] == 4775
    assert priced['forces_full_pay'] is False


def test_force_packages_full_pay_rewrites_plan():
    rows = force_packages_full_pay([
        {'package_id': 1, 'quantity': 2, 'payment_plan_type': 'deposit_installment'},
        {'package_id': 2, 'quantity': 1, 'payment_plan_type': 'full'},
    ])
    assert all(r['payment_plan_type'] == 'full' for r in rows)
    assert rows[0]['quantity'] == 2
