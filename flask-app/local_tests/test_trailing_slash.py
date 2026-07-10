"""验证所有 GET/HEAD 页面统一移除尾部斜杠。"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app


def main():
    app = create_app("development")
    client = app.test_client()

    cases = [
        ("/asia/educational/", 308, "/asia/educational"),
        ("/asia/family/?source=safari", 308, "/asia/family?source=safari"),
        ("/admin/login/", 308, "/admin/login"),
    ]

    for path, expected_status, expected_location in cases:
        response = client.get(path)
        assert response.status_code == expected_status, (
            f"{path}: expected {expected_status}, got {response.status_code}"
        )
        assert response.headers["Location"].endswith(expected_location), (
            f"{path}: unexpected Location {response.headers['Location']}"
        )

    head_response = client.head("/north-america/")
    assert head_response.status_code == 308
    assert head_response.headers["Location"].endswith("/north-america")

    # 写操作不应由规范化逻辑重定向，避免改变请求语义。
    assert client.post("/contact/").status_code != 308

    assert client.get("/").status_code == 200
    assert client.get("/asia/educational").status_code == 200

    # /admin/ 是显式定义的目录式规范路由，不应被改写成 /admin。
    admin_root = client.get("/admin/")
    assert not (
        admin_root.status_code == 308
        and admin_root.headers.get("Location", "").endswith("/admin")
    )

    not_found = client.get("/this-page-does-not-exist")
    assert not_found.status_code == 404
    assert "no-store" in not_found.headers.get("Cache-Control", "")

    print("PASS: trailing slash redirects and 404 cache headers")


if __name__ == "__main__":
    main()
