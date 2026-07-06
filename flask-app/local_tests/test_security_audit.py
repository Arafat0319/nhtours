"""本地快速验证 security_audit（在 flask-app 目录：python local_tests/test_security_audit.py）"""
import re
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app

app = create_app("development")

with app.test_client() as client:
    r = client.get("/admin/login")
    html = r.data.decode()
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', html)
    csrf = m.group(1) if m else ""
    client.post(
        "/admin/login",
        data={
            "username": "nh_ops_947d43",
            "password": "wrong-password",
            "csrf_token": csrf,
            "submit": "Sign In",
        },
        follow_redirects=True,
    )
    r2 = client.get("/admin/login")
    csrf2 = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', r2.data.decode()).group(1)
    client.post(
        "/admin/login",
        data={
            "username": "nh_ops_947d43",
            "password": os.environ.get("TEST_ADMIN_PASSWORD", "!0JjrRBtjyVm2RgZt*aN"),
            "csrf_token": csrf2,
            "submit": "Sign In",
        },
        follow_redirects=True,
    )

path = app.config.get("SECURITY_AUDIT_LOG", "instance/audit.log")
print(f"Audit log: {path}")
if os.path.exists(path):
    with open(path, encoding="utf-8") as f:
        lines = f.readlines()[-5:]
    for line in lines:
        print(line.rstrip())
else:
    print("(file not created yet)")
