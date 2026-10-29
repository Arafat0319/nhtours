"""ACH / payment method fee helpers (no Stripe network)."""

from app.payments import calculate_fee


def test_ach_funding_has_zero_fee():
    assert calculate_fee(10_000, 'ach', 'us_bank') == 0
    assert calculate_fee(10_000, 'ach', 'visa') == 0


def test_all_cards_pay_2_9_percent():
    assert calculate_fee(10_000, 'debit', 'visa') == 290
    assert calculate_fee(10_000, 'prepaid', 'visa') == 290
    assert calculate_fee(10_000, 'credit', 'visa') == 290
    assert calculate_fee(10_000, 'credit', 'mastercard') == 290
    assert calculate_fee(10_000, 'credit', 'amex') == 290
    assert calculate_fee(10_000, 'debit', 'mastercard') == 290
    # unknown card-like funding still 2.9% (not ACH)
    assert calculate_fee(10_000, 'unknown', 'visa') == 290
