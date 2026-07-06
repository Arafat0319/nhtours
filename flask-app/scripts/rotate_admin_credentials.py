#!/usr/bin/env python3
"""
轮换管理员用户名与密码（在服务器上运行，勿将密码写入 Git）。

环境变量：
  NEW_ADMIN_USERNAME  （必填）新用户名
  NEW_ADMIN_PASSWORD  （必填）新密码
  OLD_ADMIN_USERNAME  （可选，默认 admin）要更新的旧用户名

生产注意：须与 Gunicorn 使用同一 DATABASE_URL（优先 /var/www/nhtours/.env）。
"""

import os
import sys
from pathlib import Path

# 保证 flask-app 在 path
_FLASK_APP = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_FLASK_APP))

from dotenv import load_dotenv

# 与 systemd 一致：仓库根 .env 为主，flask-app/.env 仅补充（如 SECURITY_*）
load_dotenv(_FLASK_APP.parent / ".env")
load_dotenv(_FLASK_APP / ".env", override=False)

from app import create_app, db
from app.models import User


def _mask_db_uri(uri: str) -> str:
    if not uri:
        return "(empty — DATABASE_URL 未设置)"
    if "@" in uri:
        return uri.split("@", 1)[-1]
    return uri[:40] + ("..." if len(uri) > 40 else "")


def main():
    new_user = os.environ.get("NEW_ADMIN_USERNAME", "").strip()
    new_pass = os.environ.get("NEW_ADMIN_PASSWORD", "")
    old_user = os.environ.get("OLD_ADMIN_USERNAME", "admin").strip()
    flask_env = os.environ.get("FLASK_ENV", "production")

    if not new_user or not new_pass:
        print("ERROR: set NEW_ADMIN_USERNAME and NEW_ADMIN_PASSWORD", file=sys.stderr)
        sys.exit(1)
    if len(new_pass) < 12:
        print("ERROR: password must be at least 12 characters", file=sys.stderr)
        sys.exit(1)

    app = create_app(flask_env)
    db_uri = app.config.get("SQLALCHEMY_DATABASE_URI") or ""
    print(f"Using database: {_mask_db_uri(db_uri)}")

    if flask_env == "production":
        if not db_uri:
            print("ERROR: DATABASE_URL missing in production", file=sys.stderr)
            sys.exit(1)
        if "sqlite" in db_uri.lower():
            print(
                "ERROR: production rotate must use MySQL, not SQLite. "
                "Check /var/www/nhtours/.env DATABASE_URL.",
                file=sys.stderr,
            )
            sys.exit(1)

    with app.app_context():
        target = User.query.filter_by(username=old_user).first()
        existing_new = User.query.filter_by(username=new_user).first()

        if target and existing_new and target.id != existing_new.id:
            print(f"NOTE: removing duplicate user '{old_user}' (id={target.id})")
            db.session.delete(target)
            db.session.flush()
            target = existing_new
        elif not target:
            target = existing_new or User.query.first()

        if not target:
            target = User(username=new_user)
            db.session.add(target)
        elif new_user != target.username:
            conflict = User.query.filter_by(username=new_user).first()
            if conflict and conflict.id != target.id:
                print(f"ERROR: username {new_user} already exists", file=sys.stderr)
                sys.exit(1)
            target.username = new_user

        target.set_password(new_pass)
        db.session.commit()

        # 删除仍名为 admin 的其他账号（避免旧口令仍可登录）
        for extra in User.query.filter_by(username=old_user).all():
            if extra.id != target.id:
                print(f"NOTE: deleting leftover user '{old_user}' (id={extra.id})")
                db.session.delete(extra)
        db.session.commit()

        # 写后校验
        db.session.expire_all()
        updated = User.query.filter_by(username=new_user).first()
        if not updated or not updated.check_password(new_pass):
            print("ERROR: new credentials verification failed after commit", file=sys.stderr)
            sys.exit(1)

        legacy = User.query.filter_by(username=old_user).first()
        if legacy and legacy.check_password("admin123"):
            print(f"ERROR: '{old_user}' / admin123 still valid — wrong database?", file=sys.stderr)
            sys.exit(1)

        print(f"OK: admin credentials updated for user '{new_user}' on {_mask_db_uri(db_uri)}")


if __name__ == "__main__":
    main()
