"""ACH / payment method fee helpers (no Stripe network)."""

from app.payments import calculate_fee


def test_ach_funding_has_zero_fee():
    assert calculate_fee(10_000, 'ach', 'us_bank') == 0
    assert calculate_fee(10_000, 'debit', 'visa') == 0
    assert calculate_fee(10_000, 'credit', 'visa') == 290
    # float ceil: 10000*0.035 may be slightly over 350
    assert calculate_fee(10_000, 'credit', 'amex') in (350, 351)
