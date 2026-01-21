import os
import sys
from pathlib import Path
from datetime import date, timedelta
import uuid

from dotenv import load_dotenv


def run():
    load_dotenv(".env")
    os.environ.setdefault("FLASK_ENV", "testing")

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from app import create_app, db
    from app.models import Trip, TripPackage, Booking, BookingPackage, Client, InstallmentPayment
    from app.routes import create_installment_payments

    app = create_app("testing")
    with app.app_context():
        # Create minimal trip + package
        slug = f"qa-installment-check-{date.today().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6]}"
        trip = Trip(
            title="QA Installment Plan Check",
            slug=slug,
            price=1000,
            start_date=date.today() + timedelta(days=10),
            end_date=date.today() + timedelta(days=15),
            status="published",
            is_published=True,
        )
        db.session.add(trip)
        db.session.flush()

        plan = {
            "enabled": True,
            "deposit": 200,
            "installments": [
                {"date": (date.today() + timedelta(days=30)).strftime("%Y-%m-%d"), "amount": 400},
                {"date": (date.today() + timedelta(days=60)).strftime("%Y-%m-%d"), "amount": 400},
            ],
            "auto_billing": False,
            "allow_partial": False,
        }
        package = TripPackage(
            trip_id=trip.id,
            name="Installment Plan Package",
            description="QA plan check package",
            price=1000,
            capacity=5,
            status="available",
            payment_plan_config=plan,
        )
        db.session.add(package)
        db.session.flush()

        client = Client(name="QA Client", email=f"qa-client-{trip.id}@example.com")
        db.session.add(client)
        db.session.flush()

        booking = Booking(
            trip_id=trip.id,
            client_id=client.id,
            status="deposit_paid",
            passenger_count=1,
            amount_paid=200.0,
            buyer_email=client.email,
        )
        db.session.add(booking)
        db.session.flush()

        booking_package = BookingPackage(
            booking_id=booking.id,
            package_id=package.id,
            quantity=1,
            payment_plan_type="deposit_installment",
            status="deposit_paid",
            amount_paid=200.0,
        )
        db.session.add(booking_package)
        db.session.flush()

        create_installment_payments(booking, booking_package, plan)
        db.session.commit()

        installments = InstallmentPayment.query.filter_by(booking_id=booking.id).order_by(InstallmentPayment.installment_number).all()
        expected_count = 1 + len(plan["installments"])
        ok = len(installments) == expected_count
        print(f"installments_expected={expected_count} actual={len(installments)}")
        for inst in installments:
            print(f"- #{inst.installment_number} amount={inst.amount} due={inst.due_date} status={inst.status}")

        # Cleanup
        for inst in installments:
            db.session.delete(inst)
        db.session.delete(booking_package)
        db.session.delete(booking)
        db.session.delete(package)
        db.session.delete(client)
        db.session.delete(trip)
        db.session.commit()

        return ok


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
