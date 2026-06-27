# AI 快速参考（优先读此）

> 本页是给 AI 助手的一页纸。**路由 / API / 字段以代码为准**；与 `07_开发日志` 历史条目冲突时，以 **`04_API参考.md`**、**`02_数据库设计.md`** 为准。

## 本地开发

| 项 | 值 |
|----|-----|
| 启动 | `cd flask-app && python run.py` |
| 端口 | **8080**（`PORT` 环境变量可改；不是 5000） |
| 后台 | `http://localhost:8080/admin/login` |
| 迁移 | `flask db upgrade`（在 flask-app 目录，激活 venv 后） |

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
POST /trips/<slug>（AJAX）  →  创建 PendingBooking + PaymentIntent
POST /api/payment/quote     →  算价
POST /api/payment/intent      →  仅更新已有 PI（卡费等），不创建 PendingBooking
Webhook                     →  /webhooks/stripe 或 /api/stripe/webhook
```

- `PendingBooking.payment_intent_id`（不是 `stripe_payment_intent_id`）
- 报名在 `/trips/<slug>` **弹窗内** 5 步；无 `/trips` 列表、无 `/trips/<slug>/book`

## 部署

| 项 | 值 |
|----|-----|
| 触发 | 用户明确同意后才 `git push origin main` |
| Workflow | 根目录 `.github/workflows/deploy.yml`（SSH → Lightsail） |
| **勿用** | `flask-app/.github/workflows/deploy.yml`（旧 EB 流程） |
| 生产示例 | `http://54.69.40.218`，目录 `/var/www/nhtours` |

## Testimonials / Feedback

| 项 | 值 |
|----|-----|
| 首页提交 | `POST /`，`form=testimonial` |
| Feedback 页 | `/feedback`（不进主导航） |
| 数据表 | `testimonials`；`source=homepage\|feedback` |
| 后台 | `/admin/customers/testimonials` |

## 协作规则（细则见专文，此处不重复）

- **push 前**：更新 context（至少 `07`）→ 用户确认本地测试 → 同一 commit 含代码+文档
- **防灾**：覆盖工作区前读 `10_防灾与备份机制.md`
- **完整检查表**：`11_推送与上下文同步.md`

## 文档地图

| 问什么 | 读什么 |
|--------|--------|
| 有哪些路由 | `04_API参考.md`（列表可能不全，grep `@bp.route` 补） |
| 表/字段 | `02_数据库设计.md` + `models.py` |
| 报名/Stripe 流程 | `03_功能模块/报名付款系统.md` |
| UI 规范 | `05_UI设计系统.md` |
| 怎么部署 | `06_部署指南.md` |
| 历史决策 | `07_开发日志.md`（旧条目可能过时） |

**最后更新**: 2026-06-18
