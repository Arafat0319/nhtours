"""本地验证 nh-audit --all 合并轮转归档。"""

import gzip
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "deploy" / "security"))

from audit_tail import discover_log_files, tail_all  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        current = root / "audit.log"
        one = root / "audit.log.1"
        two = root / "audit.log.2.gz"

        def line(ts: str, event: str) -> str:
            return json.dumps({"ts": ts, "event": event, "username": "u", "ip": "1.1.1.1"}) + "\n"

        two.write_bytes(
            gzip.compress(
                (
                    line("2026-07-06T05:20:32Z", "admin_login_success")
                    + line("2026-07-06T05:20:34Z", "admin_logout")
                ).encode()
            )
        )
        one.write_text(line("2026-07-20T03:36:35Z", "admin_login_success"), encoding="utf-8")
        current.write_text("", encoding="utf-8")

        paths = discover_log_files(current)
        assert [p.name for p in paths] == ["audit.log.2.gz", "audit.log.1", "audit.log"]

        lines = tail_all(str(current), 10)
        assert len(lines) == 3
        assert "admin_logout" in lines[1]
        assert "2026-07-20T03:36:35Z" in lines[2]

        recent = tail_all(str(current), 1)
        assert len(recent) == 1
        assert "2026-07-20T03:36:35Z" in recent[0]

    print("PASS: nh-audit --all merges rotated archives")


if __name__ == "__main__":
    main()
