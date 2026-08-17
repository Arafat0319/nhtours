"""
套餐名额：已确认订单 + 有效 PendingBooking 占位 + 提交时行锁，防止并发超售。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, or_

from app import db
from app.models import BookingPackage, PendingBooking, TripPackage

# 已占名额的 BookingPackage（含 ACH processing；不含未付款 pending 壳）
OCCUPIED_BOOKING_PACKAGE_STATUSES = (
    'processing',
    'deposit_paid',
    'fully_paid',
)


def _pending_quantity_for_package(package_id, *, exclude_pending_id=None, now=None):
    """有效 PendingBooking（未过期）中该套餐的 quantity 之和。"""
    now = now or datetime.utcnow()
    q = PendingBooking.query.filter(
        PendingBooking.status == 'pending',
        or_(
            PendingBooking.expires_at.is_(None),
            PendingBooking.expires_at > now,
        ),
    )
    if exclude_pending_id is not None:
        q = q.filter(PendingBooking.id != exclude_pending_id)

    total = 0
    for pb in q.all():
        for row in (pb.booking_data or {}).get('packages') or []:
            if not isinstance(row, dict):
                continue
            try:
                pid = int(row.get('package_id'))
            except (TypeError, ValueError):
                continue
            if pid != int(package_id):
                continue
            try:
                qty = int(row.get('quantity', 1) or 1)
            except (TypeError, ValueError):
                qty = 1
            if qty > 0:
                total += qty
    return total


def committed_quantity_for_package(package_id):
    """已建单并占用名额的数量（按 quantity 求和）。"""
    return (
        BookingPackage.query.filter(
            BookingPackage.package_id == package_id,
            BookingPackage.status.in_(OCCUPIED_BOOKING_PACKAGE_STATUSES),
        )
        .with_entities(func.coalesce(func.sum(BookingPackage.quantity), 0))
        .scalar()
        or 0
    )


def package_capacity_usage(package_id, *, exclude_pending_id=None):
    """
    返回 (committed, reserved, capacity)。
    capacity 为 None 表示不限名额。
    """
    package = TripPackage.query.get(package_id)
    if not package:
        return 0, 0, 0
    committed = committed_quantity_for_package(package.id)
    reserved = _pending_quantity_for_package(
        package.id, exclude_pending_id=exclude_pending_id
    )
    return committed, reserved, package.capacity


def package_spots_available(package_id, *, exclude_pending_id=None):
    """剩余可订名额；None 表示不限。"""
    committed, reserved, capacity = package_capacity_usage(
        package_id, exclude_pending_id=exclude_pending_id
    )
    if capacity is None:
        return None
    return max(0, int(capacity) - committed - reserved)


def _requested_quantities(packages_data):
    out = {}
    for row in packages_data or []:
        if not isinstance(row, dict):
            continue
        try:
            pid = int(row.get('package_id'))
            qty = int(row.get('quantity', 1) or 1)
        except (TypeError, ValueError):
            continue
        if qty < 1:
            continue
        out[pid] = out.get(pid, 0) + qty
    return out


def validate_packages_capacity(
    packages_data,
    *,
    exclude_pending_id=None,
    lock=False,
):
    """
    校验各套餐是否还有足够名额。
    lock=True 时对涉及 TripPackage 行 SELECT FOR UPDATE（须在事务内调用）。
    成功返回 None，失败返回英文错误信息（与前台一致）。
    """
    requested = _requested_quantities(packages_data)
    if not requested:
        return 'Please select at least one package'

    package_ids = sorted(requested.keys())
    if lock:
        TripPackage.query.filter(TripPackage.id.in_(package_ids)).with_for_update().all()

    for pid, qty in requested.items():
        package = TripPackage.query.get(pid)
        if not package:
            return 'One or more selected packages are invalid'
        if package.capacity is None:
            continue
        available = package_spots_available(pid, exclude_pending_id=exclude_pending_id)
        if available is None:
            continue
        if qty > available:
            return f'Package "{package.name}" is sold out'
    return None


def package_is_over_capacity_after_payment(
    package_id,
    quantity,
    *,
    exclude_pending_id=None,
):
    """支付已成功后复查：是否仍超售（用于日志；不阻止建单）。"""
    package = TripPackage.query.get(package_id)
    if not package or package.capacity is None:
        return False
    committed, reserved, capacity = package_capacity_usage(
        package_id, exclude_pending_id=exclude_pending_id
    )
    return (committed + reserved + int(quantity or 1)) > int(capacity)
