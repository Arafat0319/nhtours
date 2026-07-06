#!/bin/bash
# fail2ban 封禁时追加审计日志（可选邮件由应用层登录失败告警覆盖）
# 安装：复制到 /etc/fail2ban/action.d/nhtours-audit.conf 并在 jail 中引用
IP="$1"
JAIL="${2:-unknown}"
echo "{\"ts\":\"$(date -u +%Y-%m-%dT%H:%M:%SZ)\",\"event\":\"fail2ban_ban\",\"ip\":\"$IP\",\"jail\":\"$JAIL\"}" >> /var/log/nhtours/audit.log
