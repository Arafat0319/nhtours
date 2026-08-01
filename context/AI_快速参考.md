# AI 快速参考（优先读此）

> 人工文档在 **`手册/`**。路由/API/字段以代码及 **`04`**、**`02`** 为准；`07` 历史可能过时。

## 硬性准则（必须遵守）

| 项 | 要求 |
|----|------|
| 生产 push | 未经用户明确同意，不得 `git push origin main` |
| **每次 push 前同步 context** | **必须**按 `context/11` 更新适用文档；**至少**写 `07` 一条；与代码**同一 commit**。仅改 UI 也要更新 `05`/`07`（及必要时 `手册/`） |
| **前端视觉** | 测试 / 优化 / 排查 / 执行任务时，**未经用户允许不得改页面视觉**（布局、文案呈现、颜色、间距、样式、模板观感等）。需要改必须先说明并征得同意 |

## 本地开发

| 项 | 值 |
|----|-----|
| 启动 | `cd flask-app && python run.py` |
| 端口 | **8080**（`PORT` 环境变量可改；不是 5000） |
| 后台 | `http://localhost:8080/admin/login` |
| 迁移 | `flask db upgrade`（在 flask-app 目录，激活 venv 后） |
| 开发 DB | 本机 **MySQL 8**；当前常用库名 **`nhtours`**（可从生产整库复制；见下） |
| SSH 生产 | 本机 `ssh nhtours`（`~/.ssh/config` → `54.69.40.218`，见 `手册/安全手册.md`） |

### 从生产复制数据到本地（按需）

用于按客户测试数据改功能，避免反复 push 看效果。生产库已在 **Lightsail 托管 MySQL**（私有）；须 **SSH 到网站 VM** 再 dump（不要开 Public mode）：

1. `ssh nhtours` → 用生产 `.env` 的 `DATABASE_URL`（已指向托管 endpoint）做 `mysqldump` → `/tmp/nhtours_prod_dump.sql`
2. 拉到本机：`flask-app/_prod_sync/`（已 gitignore）
3. 本机：`DROP/CREATE` 本地库后导入（Windows：`MySQL Server 8.0\bin\mysql.exe`）
4. 同步静态文件：`app/static/uploads/`、`app/static/trip_images/`（含护照等）
5. 本地后台登录用**与生产相同**的 admin 账号

**禁止**把 dump、`.env`、客户护照文件 commit 进仓库。

## 代码入口

| 用途 | 文件 |
|------|------|
| 前台路由 | `flask-app/app/routes.py`（蓝图 `main`） |
| 后台路由 + 登录 | `flask-app/app/admin/routes.py` |
| 模型 | `flask-app/app/models.py` |
| 业务单号 | `flask-app/app/order_numbers.py` |
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
- 报名在 `/trips/<slug>` **弹窗内** 5 步；正式页 `use_experimental_modal=True` → `_modal_steps_experimental.html`（套餐卡 + Travelers 步进器）
- File Upload：`POST /api/booking/upload`（UI：自定义 dropzone，见 `05` / `booking-modal.css`）
- DOB 日历：月/年 Uiverse 下拉（同 Gender）；选月年不关日历；逻辑在 `trip_booking.html`
- 付款后摘要 `GET /api/booking/<id>/summary`：须 `token` 或 `payment_intent_id`；`trip_total` 用套餐+附加**目录价**（$0 Payment 时勿用 `base_amount_cents`）
- Download receipt（站内）：白底灰边（success / 报名弹窗 / 分期弹窗一致；见 `05`）
- 静态 CSS/JS 部署后若样式「没变」：先 **Ctrl+F5**（无版本号时易缓存）

## 业务单号 Order number

| 项 | 值 |
|----|-----|
| 格式 | `{YYMM}{ABBR}-{SEQ}` → `2612MT-001` |
| YYMM | Trip `start_date` 出发年月（写入后改期不改旧号） |
| ABBR | `Trip.trip_abbr`（库内 2–4 字母；Basics 输入框可显示 `YYMM`+字母，保存时剥年月） |
| SEQ | 每 trip `001…`；取消不回收 |
| 时机 | 正式 Booking 创建时；PendingBooking 不生成 |
| 代码 | `app/order_numbers.py` → `assign_order_number` |
| 展示 | 界面只显示 Order number（不再附内部数据库 id） |
| 路由 | URL/API 仍用 `booking.id` |

## 后台 Excel 导出

| 项 | 值 |
|----|-----|
| 入口 | Manage → **Download Excel**；Payments → **Export** |
| 行程订单 | `GET /admin/trips/<id>/bookings/export`：Participants / Contact / Bookings Summary / **Canceled** |
| Participants | Payment Status（含 Refunded）、**Refunds**、Net Paid |
| Summary | Expected、Payments Received、**Refunds**、Net Paid、Balance due + Totals + Collected Funds |
| Payments 导出 | `GET /admin/payments/export`：Order Number、Amount、**Refunded**、Net、Status、Refund Reason、Refunded At |
| 取消/退款 | 取消单在 Summary 标 cancelled 并显示退款；详表见 Canceled sheet |
| 列宽 | 按内容撑开、不换行（`export_bookings` `_autosize`） |
| 不再使用 | Power Query / Web 连接刷新；Manage「验证数据源」已移除 |

## AI 快速参考 — 本地全量回归

| 项 | 值 |
|----|-----|
| 冒烟编排 | `cd flask-app && python local_tests/run_all.py` |
| 金钱 E2E | `python local_tests/e2e_full_suite.py`（Stripe Test 真扣/真退 + SES） |
| Playwright 对抗 | `cd tests/e2e && npm test`（约 180 条：门禁+细节；需 8080 + QA trip + `E2E_STRIPE_*` / `E2E_ADMIN_*`） |
| Messaging | `python local_tests/test_messaging.py` |


| 项 | 值 |
|----|-----|
| 口径 | **基础金额**退款；**卡手续费永不退** |
| 退款 | 手填金额（上限=订单可退总额；系统自动分摊到各 Payment；卡费不退） |
| Balance due | `expected − paid − refunded`（退款不产生新欠款）；`booking_balance_due` |
| 退款状态 | 展示 `partially_refunded` / `fully_refunded`（`booking_refund_display_kind`）；Refund 弹窗可勾 Full refund 填满可退额 |
| Payment Type | Manage：`Full` / `Deposit + Final` / `Installment (N)`（`booking_payment_type_display`） |
| 取消订单 | Manage → **Cancel order** → `POST .../bookings/<id>/cancel`（不退款）；Payment Status 下拉无 Cancelled |
| $0 / 退款同时取消 | Refund 弹窗勾选 Cancel booking；或仅 Cancel order |
| 代码 | `payments.py`（`payment_max_refund` / `stripe_refunded_as_base`）、`refund_booking`、`cancel_booking_order`、`handle_refund` |

## 部署

| 项 | 值 |
|----|-----|
| 正式站 | **https://nhtours.com** 、https://www.nhtours.com |
| 后台 | https://nhtours.com/admin/login |
| 服务器 IP | `54.69.40.218`（Lightsail **StaticIp-1**，已附加 `NHtours`；勿删） |
| 目录 | `/var/www/nhtours` |
| 环境变量 | **`/var/www/nhtours/flask-app/.env`**（非仓库根 `.env`） |
| **生产 venv** | **`/var/www/nhtours/flask-app/venv`**（与 systemd gunicorn 一致；Deploy 勿装到仓库根 `venv`） |
| Gunicorn | Unix socket `flask-app/nhtours.sock`（非 8000 端口） |
| Nginx | `/etc/nginx/sites-enabled/nhtours` |
| 触发部署 | 用户同意后才 `git push origin main` |
| Workflow | 根目录 `.github/workflows/deploy.yml`（reset 前 chown；装依赖 + 校验 fpdf2） |
| 域名脚本 | `deploy/setup-domain.sh`；DNS 验证 `deploy/verify-dns.ps1` |
| Stripe Webhook | `https://nhtours.com/webhooks/stripe`（**仅沙盒** Test mode；Live 延后） |
| 邮件 SES | **生产已配置**（`nhtours.com` / `us-west-2`，已出沙箱）；详见 `06` / `08` |
| 收据邮件 | HTML+PDF；日期美西；全款：Expected→实扣斜体→Paid（无 Due/Remaining）；定稿 `.cursor/rules/receipt-pdf-layout.mdc` |
| 退款 / 取消 | **不自动发客户邮件**；退款走 Stripe/账本；需通知请用 Messages |
| 分期催款 | 美西日历；每天美西 9:00；**仅 1 个 Gunicorn worker 跑 APScheduler**（文件锁防重复发） |
| Payments 标签 | 以 order 分类：Full=全款或定金+单笔尾款；Installment=定金后>1期 |
| 报名校验 | 前端 `booking.js` + 后端 `booking_validation.py`（email/phone/name/dob/zip）；Promo 未选套餐 → `#discount-message` 琥珀提示 |
| 安全审计 | `/var/log/nhtours/audit.log`；`nh-audit` / `nh-audit --all` / `nh-audit -f` |
| 安全加固 | ✅ **生产已完成**（2026-07-06）；凭据轮换、审计、限流；详见 `06` / [手册/安全手册.md](../手册/安全手册.md) |
| 生产 DB | ✅ Lightsail 托管 `nhtours-db`（私有+自动备份）；VM 本机 MySQL 已停用；见 `06`/`08` |
| 未完成速查 | 见 `08`：Stripe Live |
| 后台角色 | `User.role`：`admin`（默认）/ `staff`；敏感操作 `@admin_required` |
| 测试 | `pytest tests/`（门禁等）；全量冒烟 `local_tests/run_all.py` |
| Download receipt | 站内白底灰边；邮件蓝钮；胶囊 CSS 仍保留未引用 || 支付门禁 | summary 须 token/PI；`/booking/payment` 须 token；discount apply 服务端重算；upload 须 `trip_id`+魔数；`/test/*` 仅 debug |

## Testimonials / Feedback

| 项 | 值 |
|----|-----|
| 首页提交 | `POST /`，`form=testimonial` |
| Feedback 页 | `/feedback`（不进主导航） |
| 数据表 | `testimonials`；`source=homepage\|feedback` |
| 后台 | `/admin/customers/testimonials`；勾选批量删除（含 approved 须确认） |

## Leads

| 项 | 值 |
|----|-----|
| 后台 | `/admin/customers/leads`；折叠 Show more；**批量删除** `POST .../bulk-delete`（admin） |
| 新线索邮件 | `emails/contact_lead_notify.html` → `RECIPIENT_EMAIL`；主题 `New contact lead — …`；Reply-To=提交者 |
| 管理员通知邮件 | 统一 `emails/admin_notify_base.html`：Contact / Newsletter / Testimonial pending / Feedback pending / Security alert |
| 客户人工邮件 | `emails/branded_customer_message.html`：Booking 单发 + Messages 群发外壳 |

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

**最后更新**: 2026-07-28（收据定稿：Due this time + Includes 说明；History 按付款方式；退款/取消不自动邮件）
