"""
Import trip bundles exported by export_trips_bundle.py.

Inserts trips with NEW ids (maps children trip_id). Resets spots_sold=0, next_order_seq=1.
Skips if slug already exists (unless --replace).

Usage (flask-app):
  python scripts/import_trips_bundle.py _prod_sync/trips_bundle.json
  python scripts/import_trips_bundle.py _prod_sync/trips_bundle.json --replace
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

CHILD_MODELS = (
    ("packages", "TripPackage"),
    ("add_ons", "TripAddOn"),
    ("questions", "CustomQuestion"),
    ("buyer_info_fields", "BuyerInfoField"),
    ("discount_codes", "DiscountCode"),
    ("itinerary_items", "ItineraryItem"),
)


def _parse_dt(val, is_date=False):
    if val is None or val == "":
        return None
    if isinstance(val, (datetime, date)):
        return val
    s = str(val)
    if is_date:
        return date.fromisoformat(s[:10])
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s[:19], "%Y-%m-%d %H:%M:%S")


def _coerce(model_cls, data: dict) -> dict:
    from sqlalchemy import Date, DateTime, Integer, Boolean, Float, String, Text, JSON
    from sqlalchemy.dialects.mysql import LONGTEXT

    out = {}
    for col in model_cls.__table__.columns:
        if col.name == "id":
            continue
        if col.name not in data and col.name != "trip_id":
            continue
        raw = data.get(col.name)
        if raw is None:
            out[col.name] = None
            continue
        col_type = col.type
        if isinstance(col_type, Date):
            out[col.name] = _parse_dt(raw, is_date=True)
        elif isinstance(col_type, DateTime):
            out[col.name] = _parse_dt(raw, is_date=False)
        elif isinstance(col_type, Boolean):
            out[col.name] = bool(raw)
        elif isinstance(col_type, Integer):
            out[col.name] = int(raw) if raw is not None else None
        elif isinstance(col_type, Float):
            out[col.name] = float(raw) if raw is not None else None
        elif isinstance(col_type, (JSON,)):
            out[col.name] = raw
        else:
            out[col.name] = raw
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Import trips bundle JSON")
    parser.add_argument("bundle", help="Path to trips_bundle.json")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Delete existing trip with same slug (and children via cascade) before import",
    )
    args = parser.parse_args()

    from app import create_app, db
    from app.models import (
        Trip,
        TripPackage,
        TripAddOn,
        CustomQuestion,
        BuyerInfoField,
        DiscountCode,
        ItineraryItem,
        City,
        trip_cities,
    )

    model_map = {
        "TripPackage": TripPackage,
        "TripAddOn": TripAddOn,
        "CustomQuestion": CustomQuestion,
        "BuyerInfoField": BuyerInfoField,
        "DiscountCode": DiscountCode,
        "ItineraryItem": ItineraryItem,
    }

    env = os.environ.get("FLASK_ENV") or os.environ.get("FLASK_CONFIG") or "development"
    app = create_app(env)
    path = Path(args.bundle)
    bundle = json.loads(path.read_text(encoding="utf-8"))

    with app.app_context():
        for entry in bundle.get("trips") or []:
            trip_data = dict(entry["trip"])
            slug = trip_data.get("slug")
            existing = Trip.query.filter_by(slug=slug).first()
            if existing:
                if not args.replace:
                    print(f"SKIP {slug}: already exists (id={existing.id})")
                    continue
                print(f"REPLACE {slug}: deleting id={existing.id}")
                db.session.delete(existing)
                db.session.flush()

            trip_data.pop("id", None)
            coerced = _coerce(Trip, trip_data)
            coerced["spots_sold"] = 0
            coerced["next_order_seq"] = 1
            trip = Trip(**coerced)
            db.session.add(trip)
            db.session.flush()
            print(f"Inserted trip slug={slug} new_id={trip.id}")

            for rel_name, model_name in CHILD_MODELS:
                cls = model_map[model_name]
                for child in entry.get("children", {}).get(rel_name) or []:
                    row = dict(child)
                    row.pop("id", None)
                    row["trip_id"] = trip.id
                    if model_name == "DiscountCode":
                        row["used_count"] = 0
                    obj = cls(**_coerce(cls, row))
                    db.session.add(obj)

            # Cities M2M (only if city ids still exist on target)
            for cid in entry.get("city_ids") or []:
                city = City.query.get(cid)
                if city:
                    trip.cities.append(city)
                else:
                    print(f"  warn: city id={cid} missing on target, skip")

            db.session.flush()
            print(
                f"  children: packages={trip.packages.count()} addons={trip.add_ons.count()} "
                f"questions={trip.questions.count()} buyer={trip.buyer_info_fields.count()} "
                f"discounts={trip.discount_codes.count()}"
            )

        db.session.commit()
        print("Import committed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
