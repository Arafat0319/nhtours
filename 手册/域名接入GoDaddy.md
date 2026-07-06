# 域名接入 GoDaddy → Lightsail

将 **nhtours.com** / **www.nhtours.com** 从旧 CloudFront 切到 Lightsail **`54.69.40.218`**。

## 当前状态（2026-06-30）✅ 已完成

| 域名 | 状态 |
|------|------|
| `https://nhtours.com` | ✅ A → `54.69.40.218`；HTTPS（Let's Encrypt 至 2026-09-28） |
| `https://www.nhtours.com` | ✅ CNAME → `nhtours.com` |
| `http://54.69.40.218` | ✅ 仍可直接访问（备用） |

**Stripe 沙盒 Webhook**：`https://nhtours.com/webhooks/stripe`（Test mode）

> 以下为迁移时的操作记录，供日后参考或新环境复现。

---

## 历史：迁移前现状

| 域名 | 原状 | 目标 |
|------|------|------|
| `nhtours.com` | A 记录 → CloudFront (`18.244.x.x`) | A → `54.69.40.218` |
| `www.nhtours.com` | CNAME → `*.cloudfront.net` | CNAME → `nhtours.com` |

---

## 步骤 1：GoDaddy DNS

1. 登录 [GoDaddy](https://www.godaddy.com/) → **My Products** → `nhtours.com` → **DNS**
2. **关闭**「域名转发 / Forwarding」
3. **删除或修改**以下旧记录：
   - 所有指向 `18.244.x.x` 的 **A** 记录（CloudFront）
   - **CNAME** `www` → `d16o1yrb47rv53.cloudfront.net`（或任何 cloudfront.net）
4. **添加**：

| 类型 | 名称 | 值 | TTL |
|------|------|-----|-----|
| A | `@` | `54.69.40.218` | 600 |
| CNAME | `www` | `nhtours.com` | 600 |

5. 保存

## 步骤 2：验证 DNS（本地 PowerShell）

```powershell
cd "项目根目录"
powershell -File deploy/verify-dns.ps1
```

或：

```powershell
nslookup nhtours.com
nslookup www.nhtours.com
```

两者应返回 **`54.69.40.218`**（生效可能 5 分钟～48 小时）。

## 步骤 3：服务器 Nginx

**方式 A — GitHub Actions（推荐，无需本机 SSH）**

1. 先 **push** 含 `deploy/` 的代码到 `main`
2. GitHub → **Actions** → **Setup Domain** → Run workflow（先不勾选 certbot）
3. DNS 生效后再 Run 一次，勾选 **run_certbot**

**方式 B — Lightsail 浏览器 SSH**

Lightsail 控制台 → **Connect using SSH**：

```bash
cd /var/www/nhtours
git pull origin main
sudo bash deploy/setup-domain.sh
```

验证（在服务器上）：

```bash
curl -I -H "Host: nhtours.com" http://127.0.0.1/
```

浏览器访问 `http://nhtours.com`（DNS 生效后）。

## 步骤 4：HTTPS

DNS 验证通过后，Actions **Setup Domain** 勾选 certbot，或 SSH 执行：

```bash
sudo bash deploy/setup-domain.sh --certbot
```

浏览器访问 `https://nhtours.com` 与 `https://www.nhtours.com`。

## 步骤 5：第三方

见 [deploy/post-domain-checklist.md](../deploy/post-domain-checklist.md)（Stripe Webhook、SES 等）。

---

**最后更新**: 2026-06-30
