#!/bin/bash
# 创建审计日志目录并授权 gunicorn 用户写入
set -euo pipefail
LOG_DIR=/var/log/nhtours
LOG_FILE="$LOG_DIR/audit.log"
install -d -m 755 "$LOG_DIR"
touch "$LOG_FILE"
chown www-data:www-data "$LOG_DIR" "$LOG_FILE" 2>/dev/null || chown ubuntu:ubuntu "$LOG_DIR" "$LOG_FILE" 2>/dev/null || true
chmod 640 "$LOG_FILE"
echo "OK: $LOG_FILE ready"
