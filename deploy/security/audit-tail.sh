#!/bin/bash
# Pretty-print security audit log. Install: setup_audit_log.sh → nh-audit
# Usage: nh-audit | nh-audit -f | nh-audit -n 50
# Local: AUDIT_LOG=flask-app/instance/audit.log nh-audit
set -euo pipefail

# nh-audit is a symlink in /usr/local/bin; resolve to deploy/security/
_script="${BASH_SOURCE[0]}"
if command -v readlink >/dev/null 2>&1; then
  _resolved="$(readlink -f "$_script" 2>/dev/null || true)"
  [ -n "$_resolved" ] && _script="$_resolved"
fi
SCRIPT_DIR="$(cd "$(dirname "$_script")" && pwd)"
LOG="${AUDIT_LOG:-/var/log/nhtours/audit.log}"
PYTHON="${PYTHON:-python3}"

if ! command -v "$PYTHON" >/dev/null 2>&1; then
  PYTHON=python
fi

exec "$PYTHON" "$SCRIPT_DIR/audit_tail.py" "$LOG" "$@"
