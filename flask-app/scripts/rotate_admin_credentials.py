#!/usr/bin/env python3
"""
轮换管理员用户名与密码（在服务器上运行，勿将密码写入 Git）。

环境变量：
  NEW_ADMIN_USERNAME  （必填）新用户名
  NEW_ADMIN_PASSWORD  （必填）新密码
  OLD_ADMIN_USERNAME  （可选，默认 admin）要更新的旧用户名

示例（Lightsail SSH）：
  cd /var/www/nhtours/flask-app
  set -a && source .env && set +a
  export NEW_ADMIN_USERNAME='nh_ops_xxxxx'
  export NEW_ADMIN_PASSWORD='your-long-password'
  ../venv/bin/python scripts/rotate_admin_credentials.py
"""

import os
import sys

# 保证 flask-app 在 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import User


def main():
    new_user = os.environ.get("NEW_ADMIN_USERNAME", "").strip()
    new_pass = os.environ.get("NEW_ADMIN_PASSWORD", "")
    old_user = os.environ.get("OLD_ADMIN_USERNAME", "admin").strip()

    if not new_user or not new_pass:
        print("ERROR: set NEW_ADMIN_USERNAME and NEW_ADMIN_PASSWORD", file=sys.stderr)
        sys.exit(1)
    if len(new_pass) < 12:
        print("ERROR: password must be at least 12 characters", file=sys.stderr)
        sys.exit(1)

    app = create_app(os.environ.get("FLASK_ENV", "production"))
    with app.app_context():
        user = User.query.filter_by(username=old_user).first()
        if not user:
            user = User.query.first()
        if not user:
            user = User(username=new_user)
            db.session.add(user)
        else:
            if new_user != old_user:
                conflict = User.query.filter_by(username=new_user).first()
                if conflict and conflict.id != user.id:
                    print(f"ERROR: username {new_user} already exists", file=sys.stderr)
                    sys.exit(1)
                user.username = new_user
        user.set_password(new_pass)
        db.session.commit()
        print(f"OK: admin credentials updated for user '{new_user}'")


if __name__ == "__main__":
    main()
