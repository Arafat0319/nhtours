import os
import sys
from pathlib import Path
import uuid

from dotenv import load_dotenv


def run():
    """
    冒烟：报名 API 在应付 >0 时创建 PendingBooking + Stripe PI（正式 Booking 在支付成功后才生成）。
    """
    load_dotenv(".env")
    os.environ.setdefault("FLASK_ENV", "testing")

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from app import create_app, db
    from app.models import Trip, PendingBooking
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
                        "dob": "1990-01-15",
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
            return False

        data = resp.get_json() or {}
        if not data.get("success"):
            print(f"[ERROR] Booking API response={data}")
            return False

        if not data.get("payment_required"):
            print(f"[ERROR] Expected payment_required=true for deposit path, got={data}")
            return False

        pi = data.get("payment_intent_id")
        if not pi or not str(pi).startswith("pi_"):
            print(f"[ERROR] Missing Stripe payment_intent_id: {data}")
            return False

        if not data.get("client_secret"):
            print(f"[ERROR] Missing client_secret: {data}")
            return False

        pending = PendingBooking.query.filter_by(payment_intent_id=pi).first()
        if not pending:
            print(f"[ERROR] PendingBooking not found for {pi}")
            return False

        print(
            f"pending_booking_id={pending.id} pi={pi} "
            f"base_cents={data.get('base_amount_cents')} status={pending.status}"
        )

        # Cleanup draft (cancel PI best-effort, delete pending)
        try:
            from app.payments import safe_cancel_payment_intent
            safe_cancel_payment_intent(pi, reason="qa booking_flow_check cleanup")
        except Exception as e:
            print(f"[WARN] cancel PI: {e}")
        db.session.delete(pending)
        db.session.commit()

    return ok


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
