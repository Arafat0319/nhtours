import argparse
import os
import sys

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
APP_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, ".."))
if APP_ROOT not in sys.path:
    sys.path.insert(0, APP_ROOT)

from app import create_app, db
from app.models import Payment
from app.payments import retrieve_payment_intent


def _parse_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def reconcile_payment(payment, dry_run=False):
    if not payment.stripe_payment_intent_id:
        return False, "missing_payment_intent"

    payment_intent = retrieve_payment_intent(payment.stripe_payment_intent_id)
    if not payment_intent:
        return False, "payment_intent_not_found"

    metadata = payment_intent.get("metadata") or {}
    payment.payment_metadata = metadata

    funding = metadata.get("funding")
    brand = metadata.get("brand")
    base_amount_cents = _parse_int(metadata.get("base_amount"))
    fee_cents = _parse_int(metadata.get("fee"))
    tax_amount_cents = _parse_int(metadata.get("tax_amount"))
    final_amount_cents = _parse_int(metadata.get("final_amount"))

    if funding:
        payment.funding = funding
    if brand:
        payment.brand = brand
    if base_amount_cents is not None:
        payment.base_amount_cents = base_amount_cents
    if fee_cents is not None:
        payment.fee_cents = fee_cents
    if tax_amount_cents is not None:
        payment.tax_amount_cents = tax_amount_cents
    if final_amount_cents is not None:
        payment.final_amount_cents = final_amount_cents

    if final_amount_cents is not None:
        payment.amount = final_amount_cents / 100.0

    if dry_run:
        return True, "dry_run"

    db.session.add(payment)
    return True, "updated"


def main():
    parser = argparse.ArgumentParser(description="Reconcile Payment metadata from Stripe.")
    parser.add_argument("--limit", type=int, default=0, help="Limit number of payments processed.")
    parser.add_argument("--dry-run", action="store_true", help="Do not commit changes.")
    args = parser.parse_args()

    config_name = os.environ.get("FLASK_ENV", "development")
    app = create_app(config_name)

    with app.app_context():
        query = Payment.query.filter(Payment.stripe_payment_intent_id.isnot(None))
        if args.limit:
            query = query.limit(args.limit)

        processed = 0
        updated = 0
        skipped = 0

        for payment in query.all():
            processed += 1
            success, status = reconcile_payment(payment, dry_run=args.dry_run)
            if not success:
                skipped += 1
                app.logger.warning(
                    "reconcile skip payment_id=%s status=%s", payment.id, status
                )
                continue

            if status == "updated":
                updated += 1

            if processed % 50 == 0 and not args.dry_run:
                db.session.commit()

        if not args.dry_run:
            db.session.commit()

        app.logger.info(
            "reconcile done processed=%s updated=%s skipped=%s dry_run=%s",
            processed,
            updated,
            skipped,
            args.dry_run,
        )


if __name__ == "__main__":
    main()
