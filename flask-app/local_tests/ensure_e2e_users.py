"""
确保本地 E2E / pytest 用的 admin、staff 账号存在（可重复执行）。
默认密码仅用于本机测试，勿用于生产。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


ROOT = Path(__file__).resolve().parents[1]


def run() -> bool:
    load_dotenv(ROOT / ".env")
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    from app import create_app, db
    from app.models import User

    admin_user = os.environ.get("E2E_ADMIN_USERNAME", "_e2e_admin")
    admin_pass = os.environ.get("E2E_ADMIN_PASSWORD", "e2e-admin-temp")
    staff_user = os.environ.get("E2E_STAFF_USERNAME", "_pytest_staff")
    staff_pass = os.environ.get("E2E_STAFF_PASSWORD", "pytest-staff-temp")

    app = create_app()
    with app.app_context():
        for username, password, role in (
            (admin_user, admin_pass, "admin"),
            (staff_user, staff_pass, "staff"),
        ):
            user = User.query.filter_by(username=username).first()
            if not user:
                user = User(username=username, role=role)
                db.session.add(user)
            else:
                user.role = role
            user.set_password(password)
            print(f"[OK] ensured user={username} role={role}")
        db.session.commit()
    return True


if __name__ == "__main__":
    sys.exit(0 if run() else 1)
