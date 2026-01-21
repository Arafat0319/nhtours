import os
import sys
from pathlib import Path
import uuid

from dotenv import load_dotenv


def run():
    load_dotenv(".env")
    os.environ.setdefault("FLASK_ENV", "testing")

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from app import create_app, db
    from app.models import Trip, Booking, BookingPackage, BookingAddOn, BookingParticipant, Client
    from local_tests.setup_test_trip import run as ensure_trip

    ensure_trip()

    app = create_app("testing")
    ok = True
    with app.app_context():
        trip = Trip.query.filter_by(slug="qa-payment-trip-2026").first()
        if not trip:
            print("[ERROR] Test trip not found.")
            return False

        packages = trip.packages.filter_by(status="available").all()
        addons = trip.add_ons.all()
        if not packages:
            print("[ERROR] No packages available for test trip.")
            return False

        package = packages[0]
        addon = addons[0] if addons else None

        unique_email = f"qa-booking-{uuid.uuid4().hex[:8]}@example.com"
        booking_payload = {
            "booking_data": {
                "buyer_info": {
                    "first_name": "QA",
                    "last_name": "Tester",
                    "email": unique_email,
                    "phone": "1234567890",
                    "address": "1 QA Street",
                    "city": "QA City",
                    "state": "QA State",
                    "zip_code": "00000",
                    "country": "QA Country",
                    "custom_info": {
                        "dummy": "value"
                    },
                },
                "packages": [
                    {
                        "package_id": package.id,
                        "quantity": 1,
                        "payment_plan_type": "deposit_installment",
                    }
                ],
                "addons": [
                    {
                        "addon_id": addon.id,
                        "participant_id": None,
                        "quantity": 1,
                    }
                ] if addon else [],
                "participants": [
                    {
                        "first_name": "QA",
                        "last_name": "Participant",
                        "email": unique_email,
                        "phone": "1234567890",
                    }
                ],
                "discount_code": None,
                "payment_method": "deposit_installment",
            }
        }

        client = app.test_client()
        resp = client.post(
            f"/trips/{trip.slug}",
            json=booking_payload,
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        if resp.status_code != 200:
            print(f"[ERROR] Booking API status={resp.status_code}")
            ok = False
            return ok

        data = resp.get_json()
        if not data or not data.get("success"):
            print(f"[ERROR] Booking API response={data}")
            ok = False
        booking_id = data.get("booking_id")
        if not booking_id:
            print("[ERROR] Booking ID missing in response.")
            ok = False
            return ok

        booking = Booking.query.get(booking_id)
        if not booking:
            print("[ERROR] Booking not found in DB.")
            ok = False
        else:
            pkg_count = BookingPackage.query.filter_by(booking_id=booking.id).count()
            addon_count = BookingAddOn.query.filter_by(booking_id=booking.id).count()
            participant_count = BookingParticipant.query.filter_by(booking_id=booking.id).count()
            print(f"booking_id={booking.id} packages={pkg_count} addons={addon_count} participants={participant_count}")
            if pkg_count == 0:
                ok = False
            if participant_count == 0:
                ok = False

        # Cleanup
        BookingAddOn.query.filter_by(booking_id=booking_id).delete()
        BookingParticipant.query.filter_by(booking_id=booking_id).delete()
        BookingPackage.query.filter_by(booking_id=booking_id).delete()
        Booking.query.filter_by(id=booking_id).delete()
        remaining = Booking.query.filter_by(client_id=booking.client_id).count() if booking else 0
        if booking and remaining == 0:
            Client.query.filter_by(id=booking.client_id).delete()
        db.session.commit()

    return ok


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
