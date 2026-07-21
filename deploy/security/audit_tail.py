#!/usr/bin/env python3
"""Pretty-print NH Tours security audit log (JSONL). Used by audit-tail.sh / nh-audit."""

from __future__ import annotations

import argparse
import gzip
import json
import re
import sys
import time
from collections import deque
from pathlib import Path
from typing import Any, Iterable, TextIO

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


def open_log(path: Path) -> TextIO:
    if path.suffix == ".gz" or path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open(encoding="utf-8", errors="replace")


def rotate_index(path: Path, base_name: str) -> int:
    """logrotate index: audit.log -> 0, audit.log.1 -> 1, audit.log.2.gz -> 2."""
    if path.name == base_name:
        return 0
    m = re.match(rf"^{re.escape(base_name)}\.(\d+)(?:\.gz)?$", path.name)
    return int(m.group(1)) if m else -1


def discover_log_files(primary: Path) -> list[Path]:
    """Oldest → newest (… .2.gz, .1, current)."""
    if not primary.parent.is_dir():
        return [primary] if primary.exists() else []

    base = primary.name
    found: list[Path] = []
    for path in primary.parent.iterdir():
        if not path.is_file():
            continue
        idx = rotate_index(path, base)
        if idx >= 0:
            found.append(path)
    if primary.exists() and primary not in found:
        found.append(primary)
    # Higher rotate number = older → read first
    return sorted(found, key=lambda p: rotate_index(p, base), reverse=True)


def iter_lines(paths: Iterable[Path]) -> Iterable[str]:
    for path in paths:
        try:
            with open_log(path) as f:
                yield from f
        except OSError as e:
            print(f"cannot read {path}: {e}", file=sys.stderr)


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


def tail_all(primary: str, n: int) -> list[str]:
    paths = discover_log_files(Path(primary))
    if not paths:
        print(f"audit log not found: {primary}", file=sys.stderr)
        sys.exit(1)
    return list(deque(iter_lines(paths), maxlen=n))


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
    except OSError as e:
        print(f"cannot read {path}: {e}", file=sys.stderr)
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
    parser.add_argument(
        "--all",
        action="store_true",
        help="Include rotated archives (.1, .2.gz, …); take last -n across all",
    )
    parser.add_argument("--no-header", action="store_true", help="Skip table header")
    args = parser.parse_args()

    if args.follow and args.all:
        print("note: --all ignored with -f (only follows current log)", file=sys.stderr)

    if args.follow:
        follow_file(args.log)
        return

    if args.all:
        lines = tail_all(args.log, args.lines)
    else:
        lines = tail_file(args.log, args.lines)

    if not lines:
        hint = " (try: nh-audit --all)" if not args.all else ""
        print(f"(empty) {args.log}{hint}")
        return
    print_lines(lines, show_header=not args.no_header)


if __name__ == "__main__":
    main()
