#!/usr/bin/env python3
"""
修复订单 2603SH-001（bookings.id=1）Payment #1 脏退款字段。

默认 dry-run。确认 Stripe Dashboard 实退金额后再执行：

  # 若 Stripe 无退款：
  python scripts/fix_booking_2603SH_001_ledger.py --refund-amount 0 --apply

  # 若 Stripe 实退基础约 $45：
  python scripts/fix_booking_2603SH_001_ledger.py --refund-amount 45 --apply

生产执行前请先在 Lightsail 打手动快照。
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


ORDER_NUMBER = "2603SH-001"
PAYMENT_ID = 1


def main():
    parser = argparse.ArgumentParser(description="Fix dirty refund ledger on 2603SH-001")
    parser.add_argument(
        "--refund-amount",
        type=float,
        required=True,
        help="Stripe 实际退回的基础美元（0 = 无退款；如 45）",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="真正写库；默认只打印计划",
    )
    parser.add_argument(
        "--order",
        default=ORDER_NUMBER,
        help="订单号（默认 2603SH-001）",
    )
    parser.add_argument(
        "--payment-id",
        type=int,
        default=PAYMENT_ID,
        help="Payment 主键（默认 1）",
    )
    args = parser.parse_args()

    from app import create_app, db
    from app.models import Booking, Payment
    from app.payments import (
        calculate_booking_total,
        clamp_refunded_amount,
        payment_base_amount,
        reconcile_booking_ledger,
    )

    app = create_app()
    with app.app_context():
        booking = Booking.query.filter_by(order_number=args.order).first()
        if not booking:
            print(f"Booking {args.order} not found")
            return 1
        payment = Payment.query.filter_by(id=args.payment_id, booking_id=booking.id).first()
        if not payment:
            print(f"Payment #{args.payment_id} not found on booking {booking.id}")
            return 1

        base = payment_base_amount(payment)
        target = clamp_refunded_amount(args.refund_amount, base)
        old_refunded = round(float(payment.refunded_amount or 0.0), 2)
        old_paid = round(float(booking.amount_paid or 0.0), 2)
        old_status = payment.status

        # 脏字段若从未从 amount_paid 扣过，则只钳制 Payment，不改 amount_paid；
        # 若目标退款 > 0 且本地原先像没扣过（old_refunded 异常大），按目标扣一次。
        dirty_overshoot = old_refunded > base + 0.01
        paid_delta = 0.0
        if target > 0.001 and dirty_overshoot:
            # 假设脏写未扣 amount_paid：按目标退款扣减
            paid_delta = -target
        elif target > 0.001 and not dirty_overshoot:
            already_applied = min(old_refunded, base)
            paid_delta = -(target - already_applied)

        new_paid = max(0.0, round(old_paid + paid_delta, 2))
        if target <= 0.001:
            new_payment_status = "succeeded"
            new_refunded_at = None
        elif target >= base - 0.001:
            new_payment_status = "refunded"
            new_refunded_at = payment.refunded_at or datetime.utcnow()
        else:
            new_payment_status = "partially_refunded"
            new_refunded_at = payment.refunded_at or datetime.utcnow()

        totals = calculate_booking_total(booking)
        expected = float(totals.get("total") or 0)
        if new_paid + 0.015 >= expected and expected > 0:
            new_booking_status = "fully_paid"
        elif new_paid > 0.001:
            new_booking_status = "deposit_paid"
        else:
            new_booking_status = booking.status

        print("=== Dry-run plan ===" if not args.apply else "=== APPLYING ===")
        print(f"booking={booking.id} {booking.order_number} status={booking.status}")
        print(f"payment={payment.id} base={base} status={old_status} refunded={old_refunded}")
        print(f"target refunded_amount={target}")
        print(f"amount_paid {old_paid} -> {new_paid} (delta {paid_delta})")
        print(f"payment.status {old_status} -> {new_payment_status}")
        print(f"booking.status {booking.status} -> {new_booking_status}")
        print("reconcile BEFORE:", reconcile_booking_ledger(booking))

        if not args.apply:
            print("No changes written. Re-run with --apply after Stripe confirmation + snapshot.")
            return 0

        payment.refunded_amount = target
        payment.status = new_payment_status
        payment.refunded_at = new_refunded_at
        if target <= 0.001:
            payment.refund_reason = None

        meta = dict(payment.payment_metadata or {})
        history = list(meta.get("refund_history") or [])
        history.append({
            "amount": target,
            "reason": "manual_fix_2603SH_001_ledger",
            "stripe_refund_id": None,
            "manual_only": True,
            "excludes_fee": True,
            "previous_refunded_amount": old_refunded,
            "at": datetime.utcnow().isoformat() + "Z",
        })
        meta["refund_history"] = history
        payment.payment_metadata = meta

        booking.amount_paid = new_paid
        booking.status = new_booking_status
        db.session.commit()

        db.session.refresh(booking)
        db.session.refresh(payment)
        print("reconcile AFTER:", reconcile_booking_ledger(booking))
        print("Done.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
