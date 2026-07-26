# 域名上线后检查清单（阶段 4）



`nhtours.com` / `www.nhtours.com` 已 HTTPS 可访问后，逐项完成：



## Stripe（当前：仅沙盒 Test mode）



1. [Stripe Dashboard → Webhooks](https://dashboard.stripe.com/test/webhooks)（**Test mode**）

2. Endpoint：**`https://nhtours.com/webhooks/stripe`**

   - 备选路径（代码兼容）：`/api/stripe/webhook`

3. 订阅事件：`payment_intent.succeeded`、`payment_intent.payment_failed`、`charge.refunded`、`checkout.session.completed`

4. Signing secret → 服务器 **`/var/www/nhtours/flask-app/.env`**：

   ```bash

   STRIPE_WEBHOOK_SECRET=whsec_...

   sudo systemctl restart nhtours

   ```

5. Dashboard → 最近投递 → 确认 **200**



> **Live mode 延后**：待后台收款功能沙盒实测通过后，再换 `sk_live_`/`pk_live_` 并新建 **Live** Webhook endpoint（与 Test 分开）。



## AWS SES（邮件 — 未配置；测邮件前必读）



> 2026-06-30 DNS 已迁 **GoDaddy**。SES 验证记录须在 **GoDaddy DNS** 添加，不能只在旧 AWS Route 53 配。完整清单见 **`context/08_任务追踪.md` →「邮件/SES 上线前必读」**。



1. SES 控制台 → 验证域名 `nhtours.com`（务必开 **Easy DKIM**）

2. GoDaddy DNS 添加 SES 提供的 **DKIM CNAME**；建议再加 SPF（`v=spf1 include:amazonses.com ~all`，或并入现有 SPF）

3. 申请移出 SES 沙箱（否则只能发给已验证邮箱）

4. **`/var/www/nhtours/flask-app/.env`** 确认：

   - `AWS_REGION`、`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`

   - `SENDER_EMAIL=noreply@nhtours.com`（与 SES 已验证身份一致；**不要用个人 Gmail 当地址**，否则易进垃圾箱）

   - `REPLY_TO_EMAIL=info@nhtours.com`（客户点回复进工作邮箱）

   - **`BASE_URL=https://nhtours.com`**（分期提醒邮件中的支付链接）

5. `sudo systemctl restart nhtours`

6. 冒烟：Contact 表单、Test 支付收据、后台 Messages / 分期提醒；收件箱而非 Spam



## GitHub Actions（可选）



- Secret `DEPLOY_HOST` 可改为 `nhtours.com`（仍可用 IP）



## 冒烟测试



- [ ] `https://nhtours.com` 首页

- [ ] `https://www.nhtours.com` 首页

- [ ] `https://nhtours.com/admin/login` 后台

- [ ] 任一线路报名页 + Stripe **Test** 支付

- [ ] Webhook 200

- [ ] （SES 配好后）支付确认邮件、分期提醒链接

