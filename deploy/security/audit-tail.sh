#!/bin/bash
# Pretty-print security audit log. Install: setup_audit_log.sh → nh-audit
# Usage: nh-audit | nh-audit -f | nh-audit -n 50
# Local: AUDIT_LOG=flask-app/instance/audit.log nh-audit
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG="${AUDIT_LOG:-/var/log/nhtours/audit.log}"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

exec "$PYTHON" "$SCRIPT_DIR/audit_tail.py" "$LOG" "$@"
