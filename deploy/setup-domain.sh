#!/bin/bash
# NH Tours — 域名接入 Lightsail（Nginx + 可选 Certbot）
# 在服务器上执行: cd /var/www/nhtours && sudo bash deploy/setup-domain.sh
# 加 --certbot 在 DNS 生效后申请 HTTPS

set -euo pipefail

DEPLOY_ROOT="${DEPLOY_ROOT:-/var/www/nhtours}"
NGINX_SITE="nhtours"
DOMAIN="nhtours.com"
WWW="www.nhtours.com"
RUN_CERTBOT=false

for arg in "$@"; do
    case "$arg" in
        --certbot) RUN_CERTBOT=true ;;
        -h|--help)
            echo "Usage: sudo bash deploy/setup-domain.sh [--certbot]"
            echo "  默认: 仅安装 HTTP Nginx 配置"
            echo "  --certbot: DNS 已指向本机后，安装 certbot 并申请证书"
            exit 0
            ;;
    esac
done

if [[ $EUID -ne 0 ]]; then
    echo "请使用 sudo 运行"
    exit 1
fi

echo "==> 检查服务"
systemctl is-active nhtours >/dev/null || { echo "nhtours 未运行"; exit 1; }
curl -sf -o /dev/null http://127.0.0.1:8000/ || { echo "Gunicorn 8000 无响应"; exit 1; }

echo "==> 备份现有 Nginx 配置"
if [[ -f "/etc/nginx/sites-available/${NGINX_SITE}" ]]; then
    cp "/etc/nginx/sites-available/${NGINX_SITE}" "/etc/nginx/sites-available/${NGINX_SITE}.bak.$(date +%Y%m%d%H%M%S)"
fi

echo "==> 安装 HTTP 配置"
cp "${DEPLOY_ROOT}/deploy/nginx/nhtours-http.conf" "/etc/nginx/sites-available/${NGINX_SITE}"
ln -sf "/etc/nginx/sites-available/${NGINX_SITE}" "/etc/nginx/sites-enabled/${NGINX_SITE}"
rm -f /etc/nginx/sites-enabled/default

nginx -t
systemctl reload nginx

echo "==> HTTP 配置已生效 (server_name: ${DOMAIN} ${WWW})"
echo "    验证: curl -I -H 'Host: ${DOMAIN}' http://127.0.0.1/"

if [[ "$RUN_CERTBOT" == true ]]; then
    echo "==> 检查 DNS 是否指向本机"
    PUBLIC_IP=$(curl -sf https://checkip.amazonaws.com || curl -sf ifconfig.me)
    RESOLVED=$(getent ahostsv4 "${DOMAIN}" | awk '{print $1; exit}')
    if [[ "$RESOLVED" != "$PUBLIC_IP" ]]; then
        echo "警告: ${DOMAIN} 解析为 ${RESOLVED:-无}，本机公网 IP 为 ${PUBLIC_IP}"
        echo "请先在 GoDaddy 改 DNS 后再运行 --certbot"
        exit 1
    fi

    echo "==> 安装 Certbot"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y certbot python3-certbot-nginx

    echo "==> 申请证书 (HTTP -> HTTPS，www 与裸域名不互跳)"
    certbot --nginx -d "${DOMAIN}" -d "${WWW}" \
        --non-interactive --agree-tos --redirect \
        -m "${CERTBOT_EMAIL:-info@nhtours.com}" || certbot --nginx -d "${DOMAIN}" -d "${WWW}"

    certbot renew --dry-run
    nginx -t && systemctl reload nginx
    echo "==> HTTPS 已配置"
fi

echo "完成。"
