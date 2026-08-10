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
