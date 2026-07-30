"""
Print JSON fixture for installment E2E:
  { installment_id, token, booking_id, status }

Uses an existing unpaid installment on the QA trip when possible;
otherwise creates a minimal unpaid InstallmentPayment row on the latest
deposit booking (or skips with exit 2 if none).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app, db
from app.models import Booking, InstallmentPayment, Trip
from app.utils import generate_installment_token


def main() -> int:
    slug = (sys.argv[1] if len(sys.argv) > 1 else "qa-payment-trip-2026").strip()
    app = create_app()
    with app.app_context():
        trip = Trip.query.filter_by(slug=slug).first()
        if not trip:
            print(json.dumps({"error": f"trip not found: {slug}"}))
            return 2

        inst = (
            InstallmentPayment.query.join(Booking)
            .filter(
                Booking.trip_id == trip.id,
                InstallmentPayment.status.in_(("pending", "overdue")),
            )
            .order_by(InstallmentPayment.id.desc())
            .first()
        )

        if not inst:
            # Attach a synthetic pending installment to newest non-cancelled booking
            booking = (
                Booking.query.filter(
                    Booking.trip_id == trip.id,
                    Booking.status != "cancelled",
                )
                .order_by(Booking.id.desc())
                .first()
            )
            if not booking:
                print(json.dumps({"error": "no booking to attach installment"}))
                return 2
            from datetime import date, timedelta

            inst = InstallmentPayment(
                booking_id=booking.id,
                installment_number=99,
                amount=50.0,
                due_date=date.today() + timedelta(days=30),
                status="pending",
            )
            db.session.add(inst)
            db.session.commit()

        token = generate_installment_token(inst.id)
        print(
            json.dumps(
                {
                    "installment_id": inst.id,
                    "booking_id": inst.booking_id,
                    "status": inst.status,
                    "token": token,
                    "amount": float(inst.amount or 0),
                }
            )
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
