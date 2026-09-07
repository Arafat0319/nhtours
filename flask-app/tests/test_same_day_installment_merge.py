"""Same-day installment merge for customer-facing schedules/emails."""
from datetime import date
from types import SimpleNamespace

from app.payments import (
    group_installments_by_due_date,
    catch_up_summary_items,
    catch_up_metadata_fields,
)


def _inst(**kwargs):
    defaults = {
        'id': 1,
        'booking_id': 1,
        'installment_number': 1,
        'amount': 100.0,
        'due_date': date(2026, 10, 2),
        'status': 'pending',
        'paid_at': None,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_group_installments_merges_same_due_date():
    a = _inst(id=15, amount=580.0, due_date=date(2026, 9, 4))
    b = _inst(id=20, amount=690.0, due_date=date(2026, 9, 4))
    c = _inst(id=16, amount=580.0, due_date=date(2026, 10, 2))
    d = _inst(id=14, amount=100.0, installment_number=0, due_date=date(2026, 8, 30))
    e = _inst(id=19, amount=100.0, installment_number=0, due_date=date(2026, 8, 30))
    groups = group_installments_by_due_date([d, e, a, b, c])
    assert len(groups) == 3
    assert groups[0]['is_deposit'] and groups[0]['amount'] == 200.0
    assert groups[1]['due_date'] == date(2026, 9, 4) and groups[1]['amount'] == 1270.0
    assert groups[1]['anchor_id'] == 15
    assert groups[2]['due_date'] == date(2026, 10, 2) and groups[2]['amount'] == 580.0


def test_catch_up_summary_merges_same_day(monkeypatch):
    a = _inst(id=15, amount=580.0, due_date=date(2026, 9, 4), installment_number=1)
    b = _inst(id=20, amount=690.0, due_date=date(2026, 9, 4), installment_number=1)

    monkeypatch.setattr(
        'app.payments.unpaid_installments_through',
        lambda installment: [a, b],
    )
    monkeypatch.setattr(
        'app.payments.booking_post_deposit_installment_count',
        lambda booking_id: 4,
    )
    items = catch_up_summary_items(a)
    assert len(items) == 1
    assert items[0]['amount'] == 1270.0
    assert set(items[0]['installment_ids']) == {15, 20}
    meta = catch_up_metadata_fields(a, summary_items=items)
    assert meta['payment_step'] == 'catch_up'
    assert '15' in meta['catch_up_ids'] and '20' in meta['catch_up_ids']
