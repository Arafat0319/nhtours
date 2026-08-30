#!/usr/bin/env python3
"""
Seed one booking that has BOTH:
  - signup (customer) add-on: source=booking, paid — no Manual badge
  - Manage post-add: source=admin_manual, unpaid — Manual + Unpaid + Actions

Order: 2608QA-MIX  (does not wipe other bookings)
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    from app import create_app, db
    from app.addon_admin import (
        create_manual_booking_addon,
        serialize_booking_addon,
        send_addon_payment_email,
    )
    from app.models import (
        Booking,
        BookingAddOn,
        BookingPackage,
        BookingParticipant,
        Client,
        InstallmentPayment,
        Payment,
        Trip,
        TripAddOn,
        TripPackage,
    )
    from app.payments import (
        booking_payoff_due,
        calculate_booking_total,
        unpaid_manual_addons_total,
    )
    import app.utils as utils

    app = create_app("development")
    with app.app_context():
        trip = Trip.query.get(1) or Trip.query.first()
        if not trip:
            raise SystemExit("No trip")
        pkg = (
            TripPackage.query.filter_by(trip_id=trip.id)
            .order_by(TripPackage.id.asc())
            .first()
        )
        addons = (
            TripAddOn.query.filter_by(trip_id=trip.id).order_by(TripAddOn.id).all()
        )
        if not pkg or not addons:
            raise SystemExit("Need package + add-ons on trip")

        a_signup = addons[0]
        a_manual = addons[1] if len(addons) > 1 else addons[0]

        client = Client.query.filter_by(email="arafathayrat@gmail.com").first()
        if not client:
            client = Client(
                name="Arafat QA",
                email="arafathayrat@gmail.com",
                phone="555-0100",
            )
            db.session.add(client)
            db.session.flush()

        old = Booking.query.filter_by(order_number="2608QA-MIX").first()
        if old:
            Payment.query.filter_by(booking_id=old.id).delete()
            InstallmentPayment.query.filter_by(booking_id=old.id).delete()
            BookingAddOn.query.filter_by(booking_id=old.id).delete()
            BookingPackage.query.filter_by(booking_id=old.id).delete()
            BookingParticipant.query.filter_by(booking_id=old.id).delete()
            db.session.delete(old)
            db.session.commit()

        unit = float(pkg.price or 1000)
        signup_price = float(a_signup.price or 0)
        # 定金已付口径：定金 + 报名时附加项（已入账）
        amount_paid = round(200.0 + signup_price, 2)

        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            order_number="2608QA-MIX",
            status="deposit_paid",
            amount_paid=amount_paid,
            buyer_first_name="Mix",
            buyer_last_name="Compare",
            buyer_email="arafathayrat@gmail.com",
            buyer_phone="555-0199",
            passenger_count=2,
            created_at=datetime.utcnow(),
        )
        db.session.add(booking)
        db.session.flush()
        db.session.add(
            BookingPackage(
                booking_id=booking.id,
                package_id=pkg.id,
                quantity=1,
                payment_plan_type="deposit_installment",
                amount_paid=200.0,
                status="deposit_paid",
                unit_price=unit,
            )
        )
        p1 = BookingParticipant(
            booking_id=booking.id,
            name="Mix First",
            first_name="Mix",
            last_name="First",
            email="arafathayrat@gmail.com",
            status="active",
        )
        p2 = BookingParticipant(
            booking_id=booking.id,
            name="Mix Second",
            first_name="Mix",
            last_name="Second",
            email="second@example.com",
            status="active",
        )
        db.session.add_all([p1, p2])
        db.session.flush()

        # 客人报名时自己加的 — 无 Manual 徽标
        db.session.add(
            BookingAddOn(
                booking_id=booking.id,
                addon_id=a_signup.id,
                participant_id=p1.id,
                quantity=1,
                price_at_booking=signup_price,
                source="booking",
                payment_status="paid",
            )
        )

        today = date.today()
        db.session.add_all(
            [
                InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=0,
                    amount=200.0,
                    due_date=today - timedelta(days=20),
                    status="paid",
                    paid_at=datetime.utcnow() - timedelta(days=20),
                ),
                InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=1,
                    amount=400.0,
                    due_date=today + timedelta(days=10),
                    status="pending",
                ),
                InstallmentPayment(
                    booking_id=booking.id,
                    installment_number=2,
                    amount=max(0.0, unit - 600.0),
                    due_date=today + timedelta(days=40),
                    status="pending",
                ),
            ]
        )
        db.session.add(
            Payment(
                booking_id=booking.id,
                client_id=client.id,
                trip_id=trip.id,
                amount=amount_paid,
                status="succeeded",
                currency="usd",
                base_amount_cents=int(round(amount_paid * 100)),
                final_amount_cents=int(round(amount_paid * 100)),
                paid_at=datetime.utcnow() - timedelta(days=20),
                payment_metadata={
                    "payment_step": "initial",
                    "payment_plan": "deposit",
                    "note": f"Deposit + signup add-on {a_signup.name}",
                },
            )
        )
        db.session.commit()

        ba_manual, err = create_manual_booking_addon(
            booking, a_manual.id, participant_id=p2.id
        )
        if err:
            raise SystemExit(err)
        db.session.commit()

        # 不刷邮件；Manage 里可再点 Send
        real = utils.send_email_via_ses
        utils.send_email_via_ses = lambda *a, **k: (True, "muted")
        send_addon_payment_email(ba_manual)
        utils.send_email_via_ses = real

        calc = calculate_booking_total(booking)
        print(f"ORDER {booking.order_number} id={booking.id} trip={trip.id}")
        print(f"  amount_paid={booking.amount_paid}")
        print(f"  total={calc['total']} due={calc['amount_due']}")
        print(
            f"  unpaid_manual={unpaid_manual_addons_total(booking)} "
            f"payoff={booking_payoff_due(booking)}"
        )
        print("  Add-ons:")
        for ba in (
            BookingAddOn.query.filter_by(booking_id=booking.id)
            .order_by(BookingAddOn.id)
            .all()
        ):
            row = serialize_booking_addon(ba)
            print(
                f"    - {row['name']}: source={row['source']} "
                f"is_manual={row['is_manual']} status={row['payment_status']} "
                f"passenger={row['participant_name']} ${row['subtotal']}"
            )
        print(
            f"\nOpen Manage trip {trip.id} → order {booking.order_number} → Add-ons"
        )


if __name__ == "__main__":
    main()
