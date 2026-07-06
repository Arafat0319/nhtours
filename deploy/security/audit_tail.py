#!/usr/bin/env python3
"""Pretty-print NH Tours security audit log (JSONL). Used by audit-tail.sh / nh-audit."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import deque
from typing import Any

# Column widths (aligned table)
W_TIME = 22
W_EVENT = 28
W_USER = 18
W_IP = 16

HEADER = (
    f"{'TIME (UTC)':<{W_TIME}}  "
    f"{'EVENT':<{W_EVENT}}  "
    f"{'USER':<{W_USER}}  "
    f"{'IP':<{W_IP}}"
)
SEP = "-" * len(HEADER)


def _cell(value: Any, width: int) -> str:
    text = str(value) if value not in (None, "") else "-"
    if len(text) > width:
        return text[: width - 1] + "…"
    return text


def format_entry(entry: dict) -> str:
    return (
        f"{_cell(entry.get('ts', ''), W_TIME):<{W_TIME}}  "
        f"{_cell(entry.get('event', ''), W_EVENT):<{W_EVENT}}  "
        f"{_cell(entry.get('username', ''), W_USER):<{W_USER}}  "
        f"{_cell(entry.get('ip', ''), W_IP):<{W_IP}}"
    )


def parse_line(line: str) -> dict | None:
    line = line.strip()
    if not line:
        return None
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return {"ts": "", "event": "(invalid json)", "username": "", "ip": "", "_raw": line}


def print_lines(lines: list[str], *, show_header: bool) -> None:
    if show_header and lines:
        print(HEADER)
        print(SEP)
    for line in lines:
        entry = parse_line(line)
        if entry:
            print(format_entry(entry))


def tail_file(path: str, n: int) -> list[str]:
    try:
        with open(path, encoding="utf-8") as f:
            return list(deque(f, maxlen=n))
    except FileNotFoundError:
        print(f"audit log not found: {path}", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"cannot read {path}: {e}", file=sys.stderr)
        sys.exit(1)


def follow_file(path: str) -> None:
    print(HEADER)
    print(SEP)
    try:
        with open(path, encoding="utf-8") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if not line:
                    time.sleep(0.4)
                    continue
                entry = parse_line(line)
                if entry:
                    print(format_entry(entry), flush=True)
    except KeyboardInterrupt:
        print()
    except FileNotFoundError:
        print(f"audit log not found: {path}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Pretty-print security audit log")
    parser.add_argument(
        "log",
        nargs="?",
        default="/var/log/nhtours/audit.log",
        help="Path to audit.log (default: /var/log/nhtours/audit.log)",
    )
    parser.add_argument("-n", "--lines", type=int, default=30, help="Number of lines (default: 30)")
    parser.add_argument("-f", "--follow", action="store_true", help="Follow new entries (like tail -f)")
    parser.add_argument("--no-header", action="store_true", help="Skip table header")
    args = parser.parse_args()

    if args.follow:
        follow_file(args.log)
        return

    lines = tail_file(args.log, args.lines)
    if not lines:
        print(f"(empty) {args.log}")
        return
    print_lines(lines, show_header=not args.no_header)


if __name__ == "__main__":
    main()
