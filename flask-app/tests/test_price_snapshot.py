"""Package/addon price snapshots: old bookings ignore live price changes."""

from types import SimpleNamespace

from app.payments import (
    booking_addon_unit_price,
    booking_package_unit_price,
    calculate_booking_total,
)


class _QueryList(list):
    def all(self):
        return list(self)


def test_package_unit_price_prefers_snapshot():
    bp = SimpleNamespace(
        unit_price=2000.0,
        package=SimpleNamespace(price=2500.0),
    )
    assert booking_package_unit_price(bp) == 2000.0


def test_package_unit_price_falls_back_to_live():
    bp = SimpleNamespace(unit_price=None, package=SimpleNamespace(price=1800.0))
    assert booking_package_unit_price(bp) == 1800.0


def test_addon_unit_price_prefers_snapshot():
    ba = SimpleNamespace(price_at_booking=100.0, addon=SimpleNamespace(price=150.0))
    assert booking_addon_unit_price(ba) == 100.0


def test_calculate_booking_total_uses_snapshots_not_live():
    bp = SimpleNamespace(
        unit_price=2000.0,
        quantity=1,
        package=SimpleNamespace(price=9999.0),
    )
    ba = SimpleNamespace(
        price_at_booking=200.0,
        quantity=1,
        source='booking',
        addon=SimpleNamespace(price=999.0),
    )
    booking = SimpleNamespace(
        booking_packages=_QueryList([bp]),
        addons=_QueryList([ba]),
        discount_amount=0.0,
        amount_paid=0.0,
    )
    # booking_refunded_total needs payments; patch via empty ledger
    import app.payments as pay

    original = pay.booking_refunded_total
    pay.booking_refunded_total = lambda b: 0.0
    try:
        totals = calculate_booking_total(booking)
    finally:
        pay.booking_refunded_total = original

    assert totals['subtotal'] == 2200.0
    assert totals['total'] == 2200.0
    assert totals['amount_due'] == 2200.0


def test_manual_addon_not_covered_by_signup_discount():
    """免费结账折扣盖满报名结构后，后加 Manual 仍全额进入 Expected。"""
    import app.payments as pay

    bp = SimpleNamespace(unit_price=2490.0, quantity=1, package=SimpleNamespace(price=2490.0))
    airfare = SimpleNamespace(
        price_at_booking=1600.0, quantity=1, source='booking', addon=SimpleNamespace(price=1600.0)
    )
    single = SimpleNamespace(
        price_at_booking=465.0, quantity=1, source='booking', addon=SimpleNamespace(price=465.0)
    )
    manual_visa = SimpleNamespace(
        price_at_booking=285.0, quantity=1, source='admin_manual', addon=SimpleNamespace(price=285.0)
    )
    # 折扣按「报名含签证」存成 4840，但报名签证已删、只剩 Manual：
    # 旧逻辑会把 Manual 也吃进折扣 → Expected=0；新逻辑 Expected 必须仍是 285。
    booking = SimpleNamespace(
        booking_packages=_QueryList([bp]),
        addons=_QueryList([airfare, single, manual_visa]),
        discount_amount=4840.0,
        amount_paid=285.0,
    )
    original = pay.booking_refunded_total
    pay.booking_refunded_total = lambda b: 0.0
    try:
        totals = calculate_booking_total(booking)
    finally:
        pay.booking_refunded_total = original

    assert totals['signup_subtotal'] == 4555.0
    assert totals['manual_subtotal'] == 285.0
    assert totals['discount_applied'] == 4555.0
    assert totals['total'] == 285.0
    assert totals['amount_due'] == 0.0
