"""Payments 表头排序：默认时间从新到旧；点一次升序，再点倒序。"""

from datetime import datetime
from types import SimpleNamespace

from app.admin.payment_list_data import sort_payment_groups


def _group(*, order, buyer, created_at, amount=10, trip='Trip', status='succeeded'):
    return {
        'plan_kind': 'one_time',
        'booking': SimpleNamespace(
            order_number=order,
            buyer_name=buyer,
            trip=SimpleNamespace(title=trip),
        ),
        'deposit': None,
        'primary_payment': SimpleNamespace(
            status=status,
            amount=amount,
            paid_at=created_at,
            created_at=created_at,
        ),
        'deposit_payment': None,
    }


def _buyers(groups):
    return [group['booking'].buyer_name for group in groups]


def test_default_time_sort_is_newest_first():
    older = _group(order='A', buyer='Amy', created_at=datetime(2026, 1, 1))
    newer = _group(order='B', buyer='Zoe', created_at=datetime(2026, 6, 1))
    groups = [older, newer]
    sort_payment_groups(groups, 'time', None)
    assert _buyers(groups) == ['Zoe', 'Amy']


def test_buyer_toggles_asc_then_desc_and_keeps_blank_last():
    amy = _group(order='1', buyer='Amy', created_at=datetime(2026, 1, 1))
    zoe = _group(order='2', buyer='Zoe', created_at=datetime(2026, 1, 2))
    blank = _group(order='3', buyer='', created_at=datetime(2026, 1, 3))
    groups = [zoe, blank, amy]
    sort_payment_groups(groups, 'buyer', 'asc')
    assert _buyers(groups) == ['Amy', 'Zoe', '']
    sort_payment_groups(groups, 'buyer', 'desc')
    assert _buyers(groups) == ['Zoe', 'Amy', '']
