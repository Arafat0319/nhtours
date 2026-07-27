"""Discount apply ignores client-forged amount (needs pending + code in DB)."""
import pytest

from app.models import DiscountCode, PendingBooking, db


def test_discount_apply_ignores_client_amount(client, app):
    with app.app_context():
        pending = PendingBooking.query.filter_by(status="pending").order_by(PendingBooking.id.desc()).first()
        code = DiscountCode.query.order_by(DiscountCode.id.desc()).first()
        if not pending or not code:
            pytest.skip("need pending booking + discount code")
        pi = pending.payment_intent_id
        code_id = code.id
        # ensure gross present for calculate
        bd = dict(pending.booking_data or {})
        if not bd.get("gross_amount") and not bd.get("base_amount_cents"):
            pytest.skip("pending has no amount fields")

    r = client.post(
        "/api/discount/apply",
        json={
            "payment_intent_id": pi,
            "discount_code_id": code_id,
            "discount_amount": 999999,
        },
    )
    data = r.get_json() or {}
    if data.get("success"):
        assert float(data.get("discount_amount") or 0) < 999999
    else:
        # invalid for trip etc. is fine; must not succeed with forged amount
        assert True
