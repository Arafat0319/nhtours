"""
Export trip bundles (trip + child rows + image refs) to JSON.

Usage (flask-app):
  python scripts/export_trips_bundle.py --slugs SH mark-twain
  python scripts/export_trips_bundle.py --slugs SH mark-twain -o _prod_sync/trips_bundle.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

CHILD_RELATIONS = (
    ("packages", "trip_packages"),
    ("add_ons", "trip_addons"),
    ("questions", "custom_questions"),
    ("buyer_info_fields", "buyer_info_fields"),
    ("discount_codes", "discount_codes"),
    ("itinerary_items", "itinerary_items"),
)


def _jsonable(v):
    if v is None:
        return None
    if isinstance(v, (datetime, date)):
        return v.isoformat()
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (bytes, bytearray)):
        return v.hex()
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return v


def _row_dict(obj):
    from sqlalchemy import inspect as sa_inspect

    mapper = sa_inspect(obj.__class__)
    data = {}
    for col in mapper.columns:
        data[col.key] = _jsonable(getattr(obj, col.key))
    return data


def _collect_image_names(trip_row: dict, children: dict) -> list[str]:
    names = set()
    for key in ("hero_image", "highlight_image"):
        val = trip_row.get(key)
        if val:
            names.add(Path(str(val)).name)
    for item in children.get("itinerary_items") or []:
        url = item.get("image_url")
        if url:
            names.add(Path(str(url)).name)
    return sorted(names)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export trips + children to JSON bundle")
    parser.add_argument("--slugs", nargs="+", required=True)
    parser.add_argument(
        "-o",
        "--output",
        default=str(APP_ROOT / "_prod_sync" / "trips_bundle.json"),
    )
    args = parser.parse_args()

    from app import create_app
    from app.models import Trip

    env = os.environ.get("FLASK_ENV") or os.environ.get("FLASK_CONFIG") or "development"
    app = create_app(env)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)

    with app.app_context():
        trips_out = []
        all_images = set()
        for slug in args.slugs:
            trip = Trip.query.filter_by(slug=slug).first()
            if not trip:
                print(f"ERROR: trip slug={slug!r} not found")
                return 1
            trip_row = _row_dict(trip)
            children = {}
            for rel_name, _table in CHILD_RELATIONS:
                rel = getattr(trip, rel_name)
                rows = rel.all() if hasattr(rel, "all") else list(rel)
                children[rel_name] = [_row_dict(r) for r in rows]
            city_ids = [c.id for c in (trip.cities or [])]
            images = _collect_image_names(trip_row, children)
            all_images.update(images)
            trips_out.append(
                {
                    "trip": trip_row,
                    "children": children,
                    "city_ids": city_ids,
                    "images": images,
                }
            )
            print(
                f"Exported {slug}: packages={len(children['packages'])} "
                f"addons={len(children['add_ons'])} questions={len(children['questions'])} "
                f"buyer_fields={len(children['buyer_info_fields'])} "
                f"discounts={len(children['discount_codes'])} images={images}"
            )

        bundle = {
            "version": 1,
            "source": "local",
            "trips": trips_out,
            "images": sorted(all_images),
        }
        out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Wrote {out} ({out.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
