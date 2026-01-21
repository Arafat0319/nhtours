import os
import sys
from pathlib import Path
from dotenv import load_dotenv


ALLOWED_FIELD_TYPES = {
    "text",
    "email",
    "phone",
    "address",
    "date",
    "select",
    "textarea",
    "emergency_contact",
}


def run():
    load_dotenv(".env")
    os.environ.setdefault("FLASK_ENV", "testing")

    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    from app import create_app
    from app.models import Trip, BuyerInfoField

    app = create_app("testing")
    ok = True
    with app.app_context():
        trips = Trip.query.all()
        if not trips:
            print("No trips found.")
            return True

        for trip in trips:
            fields = BuyerInfoField.query.filter_by(trip_id=trip.id).all()
            if not fields:
                print(f"[WARN] Trip {trip.id} has no buyer_info_fields.")
                continue

            for field in fields:
                if field.field_type not in ALLOWED_FIELD_TYPES:
                    print(
                        f"[ERROR] Trip {trip.id} field {field.id} "
                        f"has unsupported type: {field.field_type}"
                    )
                    ok = False

                if field.field_type == "select" and field.options is not None:
                    if not isinstance(field.options, (list, tuple)):
                        print(
                            f"[WARN] Trip {trip.id} field {field.id} "
                            f"options not list; got {type(field.options).__name__}"
                        )

    return ok


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
