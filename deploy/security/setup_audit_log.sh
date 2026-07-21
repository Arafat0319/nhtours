#!/bin/bash
# 创建审计日志目录、授权 Gunicorn 用户写入、安装 nh-audit 命令
set -euo pipefail

LOG_DIR=/var/log/nhtours
LOG_FILE="$LOG_DIR/audit.log"
DEPLOY_ROOT="${DEPLOY_ROOT:-/var/www/nhtours}"
SCRIPT_DIR="$DEPLOY_ROOT/deploy/security"

# 与 systemd nhtours 一致（Lightsail 默认 ubuntu）
APP_USER="${APP_USER:-ubuntu}"
APP_GROUP="${APP_GROUP:-www-data}"
if [ -f /etc/systemd/system/nhtours.service ]; then
  u="$(grep -E '^User=' /etc/systemd/system/nhtours.service | cut -d= -f2 || true)"
  g="$(grep -E '^Group=' /etc/systemd/system/nhtours.service | cut -d= -f2 || true)"
  [ -n "$u" ] && APP_USER="$u"
  [ -n "$g" ] && APP_GROUP="$g"
fi

install -d -m 775 "$LOG_DIR"
touch "$LOG_FILE"
chown "$APP_USER:$APP_GROUP" "$LOG_DIR" "$LOG_FILE"
chmod 775 "$LOG_DIR"
chmod 664 "$LOG_FILE"

# 短命令：nh-audit / nh-audit -f
if [ -f "$SCRIPT_DIR/audit-tail.sh" ]; then
  chmod +x "$SCRIPT_DIR/audit-tail.sh" "$SCRIPT_DIR/audit_tail.py"
  ln -sf "$SCRIPT_DIR/audit-tail.sh" /usr/local/bin/nh-audit
  echo "OK: nh-audit -> $SCRIPT_DIR/audit-tail.sh"
fi

# logrotate：轮转后仍保持 APP_USER 可读可写（旧配置曾 create 640 www-data）
if [ -f "$SCRIPT_DIR/logrotate-nhtours-audit" ]; then
  # 用当前 APP_USER/APP_GROUP 生成，避免硬编码与 systemd 不一致
  cat > /etc/logrotate.d/nhtours-audit <<EOF
/var/log/nhtours/audit.log {
    daily
    rotate 90
    compress
    delaycompress
    missingok
    notifempty
    create 664 $APP_USER $APP_GROUP
    sharedscripts
    postrotate
        /bin/chown $APP_USER:$APP_GROUP /var/log/nhtours/audit.log 2>/dev/null || true
        /bin/chmod 664 /var/log/nhtours/audit.log 2>/dev/null || true
    endscript
}
EOF
  echo "OK: /etc/logrotate.d/nhtours-audit (create 664 $APP_USER:$APP_GROUP)"
fi

echo "OK: $LOG_FILE ready (owner $APP_USER:$APP_GROUP)"
