# AI 快速参考（优先读此）

> 人工文档在 **`手册/`**。路由/API/字段以代码及 **`04`**、**`02`** 为准；`07` 历史可能过时。

## 本地开发

| 项 | 值 |
|----|-----|
| 启动 | `cd flask-app && python run.py` |
| 端口 | **8080**（`PORT` 环境变量可改；不是 5000） |
| 后台 | `http://localhost:8080/admin/login` |
| 迁移 | `flask db upgrade`（在 flask-app 目录，激活 venv 后） |
| 开发 DB | 本机 **MySQL 8** 推荐（`nhtours_dev`）；轻量 UI 可用 SQLite；测支付用 MySQL |

## 代码入口

| 用途 | 文件 |
|------|------|
| 前台路由 | `flask-app/app/routes.py`（蓝图 `main`） |
| 后台路由 + 登录 | `flask-app/app/admin/routes.py` |
| 模型 | `flask-app/app/models.py` |
| 支付逻辑 | `flask-app/app/payments.py` |
| App 工厂 | `flask-app/app/__init__.py` |
| 生产 WSGI | `flask-app/wsgi.py` |

**不存在** `app/auth/`、`app/main/` 目录。

## 支付 / 报名（易错）

```
POST /trips/<slug>（AJAX）
  → 算 Due（定金+逾期+addons − 折扣）
  → >0：PendingBooking + PaymentIntent + client_secret
  → =0：PendingBooking(free_…) + payment_required=false（不调 Stripe）→ create-free
POST /api/payment/quote     →  算价
POST /api/payment/intent      →  仅更新已有 PI（卡费等），不创建 PendingBooking
Webhook                     →  /webhooks/stripe 或 /api/stripe/webhook
```

- `PendingBooking.payment_intent_id`（可以是 `pi_…` 或 `free_…`）
- 折扣抵「现在应付」；`$0` 勿建 Stripe PI
- 未支付草稿：`expires_at=+24h`；03:00 cleanup → `expired` + `safe_cancel_payment_intent`
- 报名在 `/trips/<slug>` **弹窗内** 5 步；File Upload：`POST /api/booking/upload`

## 部署

| 项 | 值 |
|----|-----|
| 正式站 | **https://nhtours.com** 、https://www.nhtours.com |
| 后台 | https://nhtours.com/admin/login |
| 服务器 IP | `54.69.40.218`（Lightsail 静态 IP，备用） |
| 目录 | `/var/www/nhtours` |
| 环境变量 | **`/var/www/nhtours/flask-app/.env`**（非仓库根 `.env`） |
| Gunicorn | Unix socket `flask-app/nhtours.sock`（非 8000 端口） |
| Nginx | `/etc/nginx/sites-enabled/nhtours` |
| 触发部署 | 用户同意后才 `git push origin main` |
| Workflow | 根目录 `.github/workflows/deploy.yml` |
| 域名脚本 | `deploy/setup-domain.sh`；DNS 验证 `deploy/verify-dns.ps1` |
| Stripe Webhook | `https://nhtours.com/webhooks/stripe`（**仅沙盒** Test mode；Live 延后） |
| 邮件 SES | **生产已配置**（`nhtours.com` / `us-west-2`，已出沙箱）；详见 `06` / `08` |
| 安全审计 | `/var/log/nhtours/audit.log`；`nh-audit` / `nh-audit --all` / `nh-audit -f` |
| 安全加固 | ✅ **生产已完成**（2026-07-06）；凭据轮换、审计、限流；详见 `06` / [手册/安全手册.md](../手册/安全手册.md) |
| 生产 DB | **现网** VM 本机 MySQL → **目标** Lightsail 托管 MySQL（**方案 B 待迁移**；见 `08`） |

## Testimonials / Feedback

| 项 | 值 |
|----|-----|
| 首页提交 | `POST /`，`form=testimonial` |
| Feedback 页 | `/feedback`（不进主导航） |
| 数据表 | `testimonials`；`source=homepage\|feedback` |
| 后台 | `/admin/customers/testimonials` |

## 协作规则

push 前更新 context（至少 `07`）→ 用户确认 → 同一 commit push。细则：**`11`**、**`10`**、**`.cursorrules`**。

## 文档索引

| 问什么 | 读什么 |
|--------|--------|
| 路由 | `04`（不全则 grep `@bp.route`） |
| 表/字段 | `02` + `models.py` |
| 支付 | `03/报名付款系统.md` |
| UI | `05` |
| 部署 | `06` |

**最后更新**: 2026-07-06（安全加固 + nh-audit 生产验证完成）
