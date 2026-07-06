#!/bin/bash
# 生产安全加固（Deploy 后运行一次；可重复执行，步骤幂等）
# 以 ubuntu 用户运行（勿整脚本 sudo，否则 GitHub Secrets 环境变量会丢失）
# 用法：bash deploy/security/post_deploy_hardening.sh
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/var/www/nhtours}"
ROOT_ENV="$DEPLOY_ROOT/.env"
ENV_FILE="$DEPLOY_ROOT/flask-app/.env"
NGINX_SITE="${NGINX_SITE:-/etc/nginx/sites-enabled/nhtours}"
SECURITY_HEADERS="include /var/www/nhtours/deploy/security/nginx-security-headers.conf;"

echo "==> NH Tours post-deploy hardening"

# --- 1. .env 安全变量 ---
if [ -f "$ENV_FILE" ]; then
  grep -q '^SECURITY_AUDIT_LOG=' "$ENV_FILE" || echo 'SECURITY_AUDIT_LOG=/var/log/nhtours/audit.log' >> "$ENV_FILE"
  grep -q '^SECURITY_ALERTS_ENABLED=' "$ENV_FILE" || echo 'SECURITY_ALERTS_ENABLED=false' >> "$ENV_FILE"
  echo "OK: .env security vars"
else
  echo "WARN: $ENV_FILE not found"
fi

# --- 2. 轮换 admin（须与 Gunicorn 同一 DATABASE_URL：先 source 仓库根 .env）---
cd "$DEPLOY_ROOT/flask-app"
if [ -n "${NEW_ADMIN_USERNAME:-}" ] && [ -n "${NEW_ADMIN_PASSWORD:-}" ]; then
  set -a
  # shellcheck disable=SC1090
  if [ -f "$ROOT_ENV" ]; then
    source "$ROOT_ENV"
    echo "OK: loaded $ROOT_ENV"
  elif [ -f "$ENV_FILE" ]; then
    source "$ENV_FILE"
    echo "OK: loaded $ENV_FILE (no root .env)"
  else
    echo "ERROR: no .env at $ROOT_ENV or $ENV_FILE" >&2
    exit 1
  fi
  # flask-app/.env 仅补充 SECURITY_* 等，不覆盖 DATABASE_URL
  if [ -f "$ENV_FILE" ] && [ -f "$ROOT_ENV" ]; then
    source "$ENV_FILE"
  fi
  set +a
  export FLASK_ENV=production
  export OLD_ADMIN_USERNAME="${OLD_ADMIN_USERNAME:-admin}"
  "$DEPLOY_ROOT/venv/bin/python" scripts/rotate_admin_credentials.py
  echo "OK: admin credentials rotated"
else
  echo "SKIP: NEW_ADMIN_USERNAME/PASSWORD not set — rotate manually if still on admin123"
fi

# --- 3. 审计日志（需 root）---
sudo bash "$DEPLOY_ROOT/deploy/security/setup_audit_log.sh"
sudo cp "$DEPLOY_ROOT/deploy/security/logrotate-nhtours-audit" /etc/logrotate.d/nhtours-audit
echo "OK: audit log"

# --- 4. Nginx 安全头 ---
if sudo test -f "$NGINX_SITE"; then
  if ! sudo grep -q 'nginx-security-headers.conf' "$NGINX_SITE"; then
    sudo sed -i "/listen 443/a\\    $SECURITY_HEADERS" "$NGINX_SITE"
    echo "OK: nginx security headers added"
  else
    echo "OK: nginx security headers already present"
  fi
  sudo nginx -t
  sudo systemctl reload nginx
else
  echo "WARN: $NGINX_SITE not found — add security headers manually"
fi

# --- 5. fail2ban ---
if ! command -v fail2ban-client >/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban
fi
sudo cp "$DEPLOY_ROOT/deploy/security/fail2ban-jail.local.example" /etc/fail2ban/jail.d/nhtours.local
sudo systemctl enable fail2ban
sudo systemctl restart fail2ban
sudo fail2ban-client status sshd || true
echo "OK: fail2ban"

# --- 6. 重启应用 ---
sudo systemctl restart nhtours
sleep 2
sudo systemctl is-active nhtours
sudo journalctl -u nhtours -n 15 --no-pager || true

echo "==> Done. Verify: https://nhtours.com/admin/login"
echo "    sudo tail -5 /var/log/nhtours/audit.log"
