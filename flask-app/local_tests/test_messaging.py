"""Messages module smoke tests (recipients + reply-to)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from app import create_app, db
from app.messaging import (
    ALLOWED_RECIPIENT_TYPES,
    collect_message_buyers,
    forced_reply_to_email,
    get_recipients_for_trip,
    recipient_counts_for_trip,
)
from app.models import Trip


def main():
    app = create_app()
    failures = []
    with app.app_context():
        # Reply-to must be work inbox, not local SES test Gmail
        reply = forced_reply_to_email()
        print(f"REPLY_TO={reply}")
        if reply.lower() != "info@nhtours.com" and "gmail.com" in reply.lower():
            failures.append(f"Reply-to looks like personal Gmail: {reply}")
        if not reply or "@" not in reply:
            failures.append(f"Invalid reply-to: {reply}")

        expected = app.config.get("REPLY_TO_EMAIL") or "info@nhtours.com"
        if reply != expected:
            failures.append(f"forced_reply_to_email={reply} != config REPLY_TO_EMAIL={expected}")

        trip = Trip.query.order_by(Trip.id.desc()).first()
        if not trip:
            print("No trip in DB — skip recipient tests")
        else:
            print(f"Using trip id={trip.id} title={trip.title!r}")
            buyers = collect_message_buyers(trip)
            print(f"buyers={len(buyers)}")
            all_r = get_recipients_for_trip(trip, {"type": "all"})
            assert len(all_r) == len(buyers), "all recipients should match buyers"
            counts = recipient_counts_for_trip(trip)
            print("counts", counts)
            assert counts["all"] == len(buyers)
            for t in ("payment_due", "incomplete_questions", "missing_signatures", "specific"):
                assert t in ALLOWED_RECIPIENT_TYPES or t == "specific"
            # package without id -> empty
            empty_pkg = get_recipients_for_trip(trip, {"type": "package"})
            assert empty_pkg == []
            print("recipient filters ok")

    if failures:
        print("FAIL:")
        for f in failures:
            print(" -", f)
        sys.exit(1)
    print("PASS")


if __name__ == "__main__":
    main()
