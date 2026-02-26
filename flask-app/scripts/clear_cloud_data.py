"""
一次性脚本：清空云端数据库所有业务数据，保留表结构和迁移版本。

用法（在服务器上）：
  cd /var/www/nhtours/flask-app
  source venv/bin/activate
  export FLASK_APP=wsgi.py
  python scripts/clear_cloud_data.py

注意：会清空所有行程、订单、客户、支付等数据；users 表也会清空，需重新创建管理员。
"""

import os
import sys

# 确保能导入 app
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text


def main():
    confirm = input("This will DELETE ALL data (trips, bookings, users, etc.) on this DB. Type 'yes' to continue: ")
    if confirm.strip().lower() != "yes":
        print("Aborted.")
        return
    from app import create_app, db

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        # 按依赖顺序清空（子表先于父表），避免外键报错
        # 若使用 MySQL，可先关闭外键检查再批量 TRUNCATE
        dialect = db.session.get_bind().dialect.name
        tables = [
            "pending_bookings",
            "installment_payments",
            "payments",
            "booking_addons",
            "booking_packages",
            "booking_participants",
            "bookings",
            "leads",
            "messages",
            "custom_questions",
            "buyer_info_fields",
            "discount_codes",
            "trip_addons",
            "trip_packages",
            "itinerary_items",
            "trip_cities",
            "trips",
            "cities",
            "users",
        ]
        if dialect == "mysql":
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0"))
            for t in tables:
                try:
                    db.session.execute(text(f"TRUNCATE TABLE `{t}`"))
                    print(f"  Truncated: {t}")
                except Exception as e:
                    print(f"  Skip {t}: {e}")
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1"))
        else:
            for t in tables:
                try:
                    db.session.execute(text(f"DELETE FROM {t}"))
                    print(f"  Deleted from: {t}")
                except Exception as e:
                    print(f"  Skip {t}: {e}")
        db.session.commit()
        print("Done. All application data cleared. alembic_version kept.")
        print("Reminder: users table is empty. Recreate admin with: python seed_admin.py")


if __name__ == "__main__":
    main()
