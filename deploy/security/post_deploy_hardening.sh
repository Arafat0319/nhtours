#!/bin/bash
# 生产安全加固（Deploy 后运行一次；可重复执行，步骤幂等）
# 用法：
#   sudo -E bash deploy/security/post_deploy_hardening.sh
# 或 GitHub Actions → Security Hardening（需 Secrets：NEW_ADMIN_USERNAME、NEW_ADMIN_PASSWORD）
set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/var/www/nhtours}"
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

# --- 2. 轮换 admin（若提供了凭据且尚未轮换）---
cd "$DEPLOY_ROOT/flask-app"
if [ -n "${NEW_ADMIN_USERNAME:-}" ] && [ -n "${NEW_ADMIN_PASSWORD:-}" ]; then
  set -a
  # shellcheck disable=SC1090
  [ -f "$ENV_FILE" ] && source "$ENV_FILE"
  set +a
  export FLASK_ENV=production
  export OLD_ADMIN_USERNAME="${OLD_ADMIN_USERNAME:-admin}"
  ../venv/bin/python scripts/rotate_admin_credentials.py
  echo "OK: admin credentials rotated"
else
  echo "SKIP: NEW_ADMIN_USERNAME/PASSWORD not set — rotate manually if still on admin123"
fi

# --- 3. 审计日志 ---
bash "$DEPLOY_ROOT/deploy/security/setup_audit_log.sh"
cp "$DEPLOY_ROOT/deploy/security/logrotate-nhtours-audit" /etc/logrotate.d/nhtours-audit
echo "OK: audit log"

# --- 4. Nginx 安全头 ---
if [ -f "$NGINX_SITE" ]; then
  if ! grep -q 'nginx-security-headers.conf' "$NGINX_SITE"; then
    # 在第一个 listen 443 行后插入 include
    sed -i "/listen 443/a\\    $SECURITY_HEADERS" "$NGINX_SITE"
    echo "OK: nginx security headers added"
  else
    echo "OK: nginx security headers already present"
  fi
  nginx -t
  systemctl reload nginx
else
  echo "WARN: $NGINX_SITE not found — add security headers manually"
fi

# --- 5. fail2ban ---
if ! command -v fail2ban-client >/dev/null 2>&1; then
  apt-get update -qq
  DEBIAN_FRONTEND=noninteractive apt-get install -y fail2ban
fi
cp "$DEPLOY_ROOT/deploy/security/fail2ban-jail.local.example" /etc/fail2ban/jail.d/nhtours.local
systemctl enable fail2ban
systemctl restart fail2ban
fail2ban-client status sshd || true
echo "OK: fail2ban"

# --- 6. 重启应用 ---
systemctl restart nhtours
sleep 2
systemctl is-active nhtours
journalctl -u nhtours -n 15 --no-pager || true

echo "==> Done. Verify: https://nhtours.com/admin/login"
echo "    sudo tail -5 /var/log/nhtours/audit.log"
