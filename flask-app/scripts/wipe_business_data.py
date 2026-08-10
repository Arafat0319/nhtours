"""
清空业务数据，保留 Testimonials / Leads / users / cities（及 alembic_version）。

默认 dry-run，只打印将删除的行数，不写库。
确认后加 --apply。可选 --clear-uploads 清理报名上传文件。

用法（在 flask-app 目录）：
  python scripts/wipe_business_data.py
  python scripts/wipe_business_data.py --apply
  python scripts/wipe_business_data.py --apply --clear-uploads
  python scripts/wipe_business_data.py --apply --also-cities   # 连 Cities 一并清
  python scripts/wipe_business_data.py --apply --also-leads    # 连 Leads 一并清（默认保留）
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

# flask-app 根目录
APP_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_ROOT))

# 按依赖顺序（子表 → 父表）；TRUNCATE 时会关外键检查
CLEAR_TABLES = [
    "pending_bookings",
    "installment_payments",
    "payments",
    "booking_addons",
    "booking_packages",
    "booking_participants",
    "bookings",
    "messages",
    "custom_questions",
    "buyer_info_fields",
    "discount_codes",
    "trip_addons",
    "trip_packages",
    "itinerary_items",
    "trip_cities",
    "trips",
    "clients",
]

KEEP_TABLES = ("users", "testimonials", "leads", "cities", "alembic_version")


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
    """简易 SQL 备份（无 mysqldump 时可用）。含全部表数据。"""
    from sqlalchemy import inspect

    insp = inspect(db.engine)
    tables = insp.get_table_names()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        f"-- NH Tours backup {datetime.now(timezone.utc).isoformat()}",
        "SET FOREIGN_KEY_CHECKS=0;",
        "",
    ]
    with db.engine.connect() as conn:
        for table in tables:
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
    """删除 static/uploads/booking 下内容，保留目录。"""
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
    parser = argparse.ArgumentParser(
        description="Wipe business data; keep testimonials/leads/users/cities"
    )
    parser.add_argument("--apply", action="store_true", help="Actually delete (default is dry-run)")
    parser.add_argument("--clear-uploads", action="store_true", help="Also clear booking upload files")
    parser.add_argument("--also-cities", action="store_true", help="Also truncate cities")
    parser.add_argument("--also-leads", action="store_true", help="Also truncate leads (kept by default)")
    parser.add_argument("--skip-backup", action="store_true", help="Skip SQL backup before --apply")
    parser.add_argument(
        "--backup-dir",
        default=str(APP_ROOT / "instance" / "db_backups"),
        help="Directory for SQL backups",
    )
    args = parser.parse_args()

    from app import create_app, db

    env = os.environ.get("FLASK_ENV") or os.environ.get("FLASK_CONFIG") or "development"
    app = create_app(env)
    tables = list(CLEAR_TABLES)
    if args.also_cities:
        tables.append("cities")
    if args.also_leads:
        tables.append("leads")

    with app.app_context():
        url = str(db.engine.url)
        print(f"Target DB: {_mask_db_url(url)}")
        print(f"Mode: {'APPLY' if args.apply else 'DRY-RUN'}")
        print()

        print("KEEP (unchanged):")
        for t in KEEP_TABLES:
            if t == "cities" and args.also_cities:
                continue
            if t == "leads" and args.also_leads:
                continue
            try:
                print(f"  {t}: {_count(db, t)}")
            except Exception as e:
                print(f"  {t}: (skip) {e}")

        print()
        print("CLEAR:")
        counts = {}
        total = 0
        for t in tables:
            try:
                n = _count(db, t)
            except Exception as e:
                print(f"  {t}: ERROR {e}")
                continue
            counts[t] = n
            total += n
            print(f"  {t}: {n}")
        print(f"  TOTAL rows: {total}")

        if not args.apply:
            print()
            print("Dry-run only. Re-run with --apply to delete.")
            if args.clear_uploads:
                root = APP_ROOT / "app" / "static" / "uploads" / "booking"
                print(f"Would also clear uploads under: {root}")
            return 0

        if not args.skip_backup:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            backup_path = Path(args.backup_dir) / f"pre_wipe_{stamp}.sql"
            print()
            print(f"Backing up to {backup_path} ...")
            backup_sql(db, backup_path)
            print(f"Backup OK ({backup_path.stat().st_size} bytes)")

        dialect = db.session.get_bind().dialect.name
        print()
        print("Wiping...")
        if dialect == "mysql":
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for t in tables:
                db.session.execute(text(f"TRUNCATE TABLE `{t}`"))
                print(f"  Truncated: {t} (was {counts.get(t, '?')})")
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        else:
            for t in tables:
                db.session.execute(text(f"DELETE FROM {t}"))
                print(f"  Deleted: {t} (was {counts.get(t, '?')})")
        db.session.commit()

        if args.clear_uploads:
            removed = clear_booking_uploads()
            print(f"Cleared {len(removed)} upload path(s) under static/uploads/booking/")

        print()
        print("After wipe:")
        for t in KEEP_TABLES:
            if t == "cities" and args.also_cities:
                print("  cities: 0 (cleared)")
                continue
            if t == "leads" and args.also_leads:
                print("  leads: 0 (cleared)")
                continue
            print(f"  {t}: {_count(db, t)}")
        for t in ("trips", "bookings", "payments", "clients", "pending_bookings"):
            print(f"  {t}: {_count(db, t)}")
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
