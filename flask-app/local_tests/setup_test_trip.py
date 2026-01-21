import os
import sys
from pathlib import Path
from datetime import date, timedelta

from dotenv import load_dotenv


def run():
    load_dotenv(".env")
    os.environ.setdefault("FLASK_ENV", "testing")

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from app import create_app, db
    from app.models import Trip, TripPackage, TripAddOn, BuyerInfoField, CustomQuestion, City

    app = create_app("testing")
    with app.app_context():
        slug = "qa-payment-trip-2026"
        trip = Trip.query.filter_by(slug=slug).first()
        if not trip:
            city = City.query.first()
            if not city:
                city = City(name="QA City", country="QA Country")
                db.session.add(city)
                db.session.commit()

            trip = Trip(
                title="QA Payment Trip (Installments)",
                slug=slug,
                price=1200,
                start_date=date.today() + timedelta(days=30),
                end_date=date.today() + timedelta(days=37),
                description="QA trip for payment flow testing.",
                capacity=20,
                status="published",
                is_published=True,
            )
            trip.cities.append(city)
            db.session.add(trip)
            db.session.commit()

        buyer_fields = BuyerInfoField.query.filter_by(trip_id=trip.id).all()
        if not buyer_fields:
            defaults = [
                ("First Name", "text", True, 0),
                ("Last Name", "text", True, 1),
                ("Email", "email", True, 2),
                ("Phone", "phone", True, 3),
                ("Billing Address", "address", True, 4),
                ("Emergency Contact", "emergency_contact", False, 5),
                ("Meal Preference", "select", False, 6),
                ("Special Notes", "textarea", False, 7),
            ]
            for name, field_type, required, order in defaults:
                field = BuyerInfoField(
                    trip_id=trip.id,
                    field_name=name,
                    field_type=field_type,
                    is_required=required,
                    display_order=order,
                    options=["Vegetarian", "Vegan", "Standard"] if field_type == "select" else None,
                )
                db.session.add(field)
            db.session.commit()

        packages = TripPackage.query.filter_by(trip_id=trip.id).all()
        if not packages:
            installment_plan = {
                "enabled": True,
                "deposit": 300,
                "installments": [
                    {
                        "date": (date.today() + timedelta(days=45)).strftime("%Y-%m-%d"),
                        "amount": 450,
                    },
                    {
                        "date": (date.today() + timedelta(days=75)).strftime("%Y-%m-%d"),
                        "amount": 450,
                    },
                ],
                "auto_billing": False,
                "allow_partial": False,
            }
            full_plan = {"enabled": False}

            pkg_installment = TripPackage(
                trip_id=trip.id,
                name="Standard Room (Installment)",
                description="QA package with deposit + installments",
                price=1200,
                capacity=10,
                status="available",
                payment_plan_config=installment_plan,
            )
            pkg_full = TripPackage(
                trip_id=trip.id,
                name="Single Room (Full Pay)",
                description="QA package full payment",
                price=1500,
                capacity=10,
                status="available",
                payment_plan_config=full_plan,
            )
            db.session.add(pkg_installment)
            db.session.add(pkg_full)
            db.session.commit()

        addons = TripAddOn.query.filter_by(trip_id=trip.id).all()
        if not addons:
            db.session.add(
                TripAddOn(
                    trip_id=trip.id,
                    name="Airport Pickup",
                    description="One-way pickup",
                    price=80,
                )
            )
            db.session.add(
                TripAddOn(
                    trip_id=trip.id,
                    name="Travel Insurance",
                    description="Basic coverage",
                    price=120,
                )
            )
            db.session.commit()

        questions = CustomQuestion.query.filter_by(trip_id=trip.id).all()
        if not questions:
            db.session.add(
                CustomQuestion(
                    trip_id=trip.id,
                    label="Passport Number",
                    type="text",
                    required=True,
                    options=None,
                )
            )
            db.session.add(
                CustomQuestion(
                    trip_id=trip.id,
                    label="T-Shirt Size",
                    type="select",
                    required=False,
                    options=["S", "M", "L", "XL"],
                )
            )
            db.session.commit()

        print("Test trip ready:")
        print(f"- trip_id={trip.id}")
        print(f"- slug={trip.slug}")
        print("Use /trips/qa-payment-trip-2026 to test booking flow.")

    return True


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
