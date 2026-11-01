"""Signup discount rules (packages only, except 100% full waive)."""
from __future__ import annotations


def _money(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        number = 0.0
    return round(max(0.0, number), 2)


def is_full_waive(discount_code):
    """Percent >= 100: waive packages, signup add-ons, and card fees."""
    if discount_code is None:
        return False
    kind = (getattr(discount_code, 'type', None) or '').strip().lower()
    try:
        amount = float(getattr(discount_code, 'amount', 0) or 0)
    except (TypeError, ValueError):
        amount = 0.0
    return kind == 'percent' and amount >= 100


def compute_signup_discount(discount_code, package_total, addon_total):
    """
    Return discount/due for a signup.

    - 100% percent: discount = packages + add-ons, due = 0, forces_full_pay
    - other percent / any fixed: discount against packages only; add-ons stay due;
      remaining paid in full (forces_full_pay)
    - no code: due = packages + add-ons (caller may replace with deposit due)
    """
    package_total = _money(package_total)
    addon_total = _money(addon_total)
    signup = _money(package_total + addon_total)
    base = {
        'discount_amount': 0.0,
        'due_amount': signup,
        'package_total': package_total,
        'addon_total': addon_total,
        'signup_total': signup,
        'full_waive': False,
        'forces_full_pay': False,
    }
    if discount_code is None:
        return base
    if is_full_waive(discount_code):
        base['discount_amount'] = signup
        base['due_amount'] = 0.0
        base['full_waive'] = True
        base['forces_full_pay'] = True
        return base

    kind = (getattr(discount_code, 'type', None) or '').strip().lower()
    try:
        face = float(getattr(discount_code, 'amount', 0) or 0)
    except (TypeError, ValueError):
        face = 0.0
    if kind == 'percent':
        off = _money(package_total * (face / 100.0))
    else:
        off = _money(min(max(0.0, face), package_total))
    off = min(off, package_total)
    base['discount_amount'] = _money(off)
    base['due_amount'] = _money(max(0.0, package_total - off) + addon_total)
    base['forces_full_pay'] = True
    return base


def force_packages_full_pay(packages_data):
    rewritten = []
    for row in packages_data or []:
        item = dict(row)
        item['payment_plan_type'] = 'full'
        rewritten.append(item)
    return rewritten


def signup_package_and_addon_totals(packages_data, addons_data, trip_id=None):
    """Live TripPackage / TripAddOn prices × qty (signup add-ons only)."""
    from app.models import TripAddOn, TripPackage

    want_trip = None
    if trip_id is not None:
        try:
            want_trip = int(trip_id)
        except (TypeError, ValueError):
            want_trip = None

    package_total = 0.0
    for row in packages_data or []:
        package = TripPackage.query.get(row.get('package_id'))
        if not package:
            continue
        if want_trip is not None and int(package.trip_id) != want_trip:
            continue
        try:
            qty = int(row.get('quantity') or 1)
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            continue
        package_total += float(package.price or 0) * qty

    addon_total = 0.0
    for row in addons_data or []:
        addon = TripAddOn.query.get(row.get('addon_id'))
        if not addon:
            continue
        if want_trip is not None and int(addon.trip_id) != want_trip:
            continue
        try:
            qty = int(row.get('quantity') or 1)
        except (TypeError, ValueError):
            qty = 1
        if qty <= 0:
            continue
        addon_total += float(addon.price or 0) * qty
    return _money(package_total), _money(addon_total)
