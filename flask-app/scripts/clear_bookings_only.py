"""
清空所有下单/支付数据，保留 trips 及 Builder 配置（packages/addons/questions/discounts 等）。

默认 dry-run。确认后：python scripts/clear_bookings_only.py --apply

可选：--clear-uploads  删除 static/uploads/booking/
      --skip-backup    跳过 SQL 备份（不推荐生产）
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import text

APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

BOOKING_TABLES = [
    "pending_bookings",
    "payments",
    "installment_payments",
    "booking_addons",
    "booking_packages",
    "booking_participants",
    "bookings",
    "clients",
]


def _mask_db_url(url: str) -> str:
    try:
        p = urlparse(url)
        host = p.hostname or "?"
        db = (p.path or "/").lstrip("/").split("?")[0]
        return f"{p.scheme.split('+')[0]}://{host}/{db}"
    except Exception:
        return "(unparseable)"


def _count(db, table: str) -> int:
    return int(db.session.execute(text(f"SELECT COUNT(*) FROM `{table}`")).scalar() or 0)


def backup_sql(db, out_path: Path) -> Path:
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    tables = insp.get_table_names()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"-- booking-only backup {datetime.now(timezone.utc).isoformat()}",
        "SET FOREIGN_KEY_CHECKS=0;",
        "",
    ]
    with db.engine.connect() as conn:
        for table in tables:
            if table not in BOOKING_TABLES and table != "trips":
                continue
            rows = conn.execute(text(f"SELECT * FROM `{table}`")).mappings().all()
            lines.append(f"-- {table}: {len(rows)} rows")
            if not rows:
                lines.append("")
                continue
            cols = list(rows[0].keys())
            col_list = ", ".join(f"`{c}`" for c in cols)
            for row in rows:
                vals = []
                for c in cols:
                    v = row[c]
                    if v is None:
                        vals.append("NULL")
                    elif isinstance(v, (int, float)) and not isinstance(v, bool):
                        vals.append(str(v))
                    elif isinstance(v, (bytes, bytearray)):
                        vals.append("0x" + bytes(v).hex())
                    else:
                        s = str(v).replace("\\", "\\\\").replace("'", "\\'")
                        vals.append(f"'{s}'")
                lines.append(f"INSERT INTO `{table}` ({col_list}) VALUES ({', '.join(vals)});")
            lines.append("")
    lines.append("SET FOREIGN_KEY_CHECKS=1;")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path


def clear_booking_uploads() -> list[str]:
    root = APP_ROOT / "app" / "static" / "uploads" / "booking"
    removed: list[str] = []
    if not root.exists():
        return removed
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
            removed.append(str(child.relative_to(APP_ROOT)))
        elif child.is_file():
            child.unlink()
            removed.append(str(child.relative_to(APP_ROOT)))
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Clear bookings; keep trips and trip config")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default dry-run)")
    parser.add_argument("--clear-uploads", action="store_true", help="Remove static/uploads/booking/")
    parser.add_argument("--skip-backup", action="store_true", help="Skip backup before --apply")
    parser.add_argument(
        "--backup-dir",
        default=str(APP_ROOT / "instance" / "db_backups"),
        help="Backup directory",
    )
    args = parser.parse_args()

    from app import create_app, db

    env = os.environ.get("FLASK_ENV") or os.environ.get("FLASK_CONFIG") or "development"
    app = create_app(env)

    with app.app_context():
        url = str(db.engine.url)
        print(f"Target DB: {_mask_db_url(url)}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print()

        counts = {}
        print("CLEAR tables:")
        for t in BOOKING_TABLES:
            try:
                n = _count(db, t)
            except Exception as e:
                print(f"  {t}: ERROR {e}")
                return 1
            counts[t] = n
            print(f"  {t}: {n}")

        trips_n = _count(db, "trips")
        pkg_n = _count(db, "trip_packages")
        print()
        print(f"KEEP: trips={trips_n}, trip_packages={pkg_n} (+ addons/questions/discounts unchanged)")

        if not args.apply:
            print()
            print("Dry-run only. Re-run with --apply to delete.")
            return 0

        if not args.skip_backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = Path(args.backup_dir) / f"pre_clear_bookings_{stamp}.sql"
            print()
            print(f"Backing up booking-related rows to {backup_path} ...")
            backup_sql(db, backup_path)
            print(f"Backup OK ({backup_path.stat().st_size} bytes)")

        dialect = db.session.get_bind().dialect.name
        print()
        print("Truncating booking tables...")
        if dialect == "mysql":
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for t in BOOKING_TABLES:
                db.session.execute(text(f"TRUNCATE TABLE `{t}`"))
                print(f"  truncated {t} (was {counts.get(t, '?')})")
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        else:
            for t in BOOKING_TABLES:
                db.session.execute(text(f"DELETE FROM {t}"))
                print(f"  deleted {t} (was {counts.get(t, '?')})")

        reset = db.session.execute(
            text("UPDATE trips SET next_order_seq = 1, spots_sold = 0")
        )
        db.session.commit()
        print(f"  reset trips.next_order_seq=1, spots_sold=0 (rows={reset.rowcount})")

        if args.clear_uploads:
            removed = clear_booking_uploads()
            print(f"Cleared {len(removed)} path(s) under uploads/booking/")

        print()
        print("After clear:")
        for t in BOOKING_TABLES:
            print(f"  {t}: {_count(db, t)}")
        print(f"  trips: {_count(db, 'trips')}")
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
