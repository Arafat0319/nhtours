import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text


REQUIRED_COLUMNS = {
    "payments": {
        "stripe_payment_intent_id",
        "payment_metadata",
        "base_amount_cents",
        "fee_cents",
        "tax_amount_cents",
        "final_amount_cents",
        "funding",
        "brand",
        "payment_method_id",
    },
    "installment_payments": {
        "payment_intent_id",
        "installment_number",
        "amount",
        "due_date",
        "status",
    },
    "bookings": {
        "status",
        "amount_paid",
        "buyer_email",
    },
}


def _get_columns(conn, dbname, table_name):
    rows = conn.execute(
        text(
            "select column_name from information_schema.columns "
            "where table_schema=:db and table_name=:table"
        ),
        {"db": dbname, "table": table_name},
    ).fetchall()
    return {row[0] for row in rows}


def run():
    load_dotenv(".env")
    url = os.getenv("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set.")
        return False

    engine = create_engine(url)
    ok = True
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        dbname = conn.execute(text("select database()")).scalar()
        print(f"db={dbname}")
        for table, required in REQUIRED_COLUMNS.items():
            cols = _get_columns(conn, dbname, table)
            missing = sorted(required - cols)
            print(f"{table}_missing={missing}")
            if missing:
                ok = False
    return ok


if __name__ == "__main__":
    success = run()
    sys.exit(0 if success else 1)
