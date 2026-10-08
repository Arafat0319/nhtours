# ACH（美国银行转账）付款规则

> **给人看** · 更新 2026-10-08  
> 技术细节另见 `context/`（API / webhook）；日常以本文为准。

---

## 1. 客户能选什么

报名弹窗、分期付款页、Payoff 的 Stripe Payment Element 同时支持：

- **Card**（信用卡 / 借记卡）
- **US bank account（ACH）**

选 ACH 时手续费为 **$0**（卡仍按原规则计费）。**须为美国银行账户**（加国等非 US 账户通常无法完成 ACH）。

---

## 2. 状态时间线（核心）

| 阶段 | Stripe | 我们系统 | 客户看到 |
|------|--------|----------|----------|
| 需微存款验证银行 | `requires_action`（verify microdeposits） | 仍为 **PendingBooking**（未成正式单）；占位最长约 **12 天**（对齐 Stripe ~10 天超时） | 品牌邮件「请验证银行」+ Stripe 验证链接；**授权≠报名成功** |
| 已提交、银行未清算 | `payment_intent.processing` | Booking / Payment → **Processing** | 弹窗「Payment Processing」 |
| 到账成功 | `payment_intent.succeeded` | 升级为 Deposit Paid / Fully Paid；分期计划在此时创建 | 成功页；确认信 + 收据 |
| 清算失败 / 微存款超时 | `payment_intent.payment_failed` | Pending 立刻 expired 放名额；若已是 Processing 订单 → **Cancelled** | 失败提示 |

测试环境 ACH 可能很快变成功；**生产通常要几个工作日**。微存款验证码常 **1–2 个工作日**才出现在银行流水里。

---

## 3. 邮件规则

### 3.0 微存款验证（requires_action）

- **会发**：`ach_microdeposit_verify`（说明还要验银行、给验证链接；无需回到原付款页）
- **另可能有**：Stripe Link 的「direct debit authorization」确认信（第三方，不是我们系统发的）
- **不发**：确认信、收据（尚未成单）

### 3.1 Processing（银行清算中）

- **会发**：订单/付款已受理通知（英文模板 `order_processing`）
  - 首次报名：说明订单已建立、状态 Processing
  - 分期 / Payoff：说明本笔付款在 Processing
- **不发**：确认信、收据 PDF（避免未到账却像付清）
- 文案要点：到账后会再发 **confirmation + receipt**

### 3.2 Succeeded（到账成功）

- **会发**：确认信 + 收据 PDF（与刷卡成功同一套）
- 金额按本笔实收，不是整单余额

### 3.3 Failed

- 不发「成功」类邮件；订单按失败规则处理（见上表）
- 微存款超时：Pending 立即释放；客户需重新报名付款

---

## 4. 首次报名（定金 / 全款）选 ACH

0. 若银行需微存款验证：先停在 Pending + 验证邮件；客户填码后才进入 processing
1. 客户 Confirm → Stripe 接受 ACH → `processing`
2. 系统会立刻建 **Booking**（有订单号），状态 Processing，`amount_paid` 仍为 0  
   - 原因：临时单 `PendingBooking` 默认约 24h 过期；微存款/清算中会按规则延期或立刻释放（见上表）
3. 发 Processing 通知邮件
4. **到账成功后**才：
   - 记已付金额
   - 若是分期计划 → **这时才创建**各期 `InstallmentPayment`
   - 发确认信 + 收据

因此：定金 ACH 清算期间，客户**还没有**分期付款链接，也不会收到分期提醒。

---

## 5. 分期 / Payoff 选 ACH

1. 客户提交 → Payment → Processing；对应分期行在数据库里仍可能是 pending（未标 paid）
2. 发 Processing 通知（不是「新建订单」口吻）
3. **清算期间整单锁定**（见第 6 节）
4. 到账成功后：覆盖的期标 paid，再发确认信 + 收据

---

## 5.1 Manage 后加 Add-on 选 ACH

1. 管理员在订单上 **+ Add add-on** → 客户打开 `/pay-addon/…` 独立付款（**金额只含该附加项**，不含已付套餐）
2. 若银行需微存款：同 §3.0，发验证邮件；付款页点 Place Order 后**停在本页**说明「我们会发验证邮件，请在邮件里完成验证」（可选按钮 Open verification page）；**不要**无提示地卡住或默默跳走
3. 验证通过后进入 Processing → 附加项行标 Processing → 到账后 Paid；**不会**取消整单
4. 未付 Manual 附加项不进分期 / Auto Pay / Payoff

**给客户口头说明（示例：已付清主行程、后加机票 $1600）**：打开邮件里的 Pay now → 确认 Total 只有附加项金额 → 选 US bank account → Place Order。若银行要验证，页面会提示查邮箱（系统另发验证邮件），也可点 Open verification page；到银行流水找 Stripe 小额/验证码（常 1–2 个工作日）完成验证后，付款进入 Processing，几个工作日到账；到账后会再收到确认。期间不要重复提交，也不要用旧的错误金额链接。

---

## 6. 清算期间的保护（Edge cases）

订单上只要有一笔 `Payment.status = processing`：

| 场景 | 行为 |
|------|------|
| 分期提醒 / 逾期催款定时任务 | **跳过**（不发信、不标 overdue） |
| 后台手动 Send Reminder | **拒绝** |
| 再打开 `/pay-installment/...` | 只显示 Processing，**不挂付款表单**、不新建 PaymentIntent |
| Payoff 入口 | 重定向到同一锁定态 |
| quote / intent API | `409 payment_processing` |
| 已有 processing 的 Stripe PI | **禁止** cancel / rebuild |

原则：**清算完成（成功或失败）前，整单不能再发起新的分期/Payoff 扣款**，避免二次扣款和账本混乱。

Webhook 若稍慢：打开付款页时会按 Stripe PI 状态同步；本地未更新也会按锁定展示。

---

## 7. 弹窗体验（Processing / Loading）

Confirm 后切到等待 / Processing / 成功 / 失败时：

- 锁定切换前弹窗高度，避免左侧变矮后「塌下去」
- 结果区有最短高度 + 短淡入过渡

---

## 8. 后台 Manage 里怎么看

- Booking / Payment 会出现 **Processing** 徽章
- Processing ≠ 已收款；Balance / Amount paid 以 succeeded 为准
- ACH 失败且订单被取消后，名额会释放（与建单阶段失败逻辑一致）

---

## 8.1 退款（ACH / 卡 / 混付）

- Manage → **Refund**：一次只退 **一笔** 已成功收款；多笔时先选 Payment，再手填金额（不超过该笔可退）
- ACH 与卡均原路退回；**不能**把 ACH 的钱退到卡，也不能把卡 A 的钱退到卡 B（Stripe 规则）
- ACH 仍在 Processing 时不可退；成功后可退，银行入账通常需数个工作日
- **会发**退款通知邮件（卡 / ACH 文案不同：到账天数与账单显示说明）；邮件失败不影响退款本身
- $0 仅取消订单不发退款信

---

## 9. 本地 / 生产自测要点

```text
本地：cd flask-app && python run.py（8080）
Stripe CLI：stripe listen --forward-to localhost:8080/webhooks/stripe
```

- Dashboard 开启 US bank account
- Webhook 需包含 `payment_intent.processing`（以及 succeeded / failed）
- 沙盒测 ACH：Test non-OAuth → Success …6789 等官方测试账号
- 邮件里的 Download receipt 若指向生产域名，本地可能 404；以邮件附件 PDF 为准

---

## 10. 和刷卡的对比（一句话）

| | 卡 | ACH |
|--|----|-----|
| 到账 | 通常立即 succeeded | 先 processing，再 succeeded / failed |
| 手续费 | 按原规则 | $0 |
| 建单时机 | 成功时建单 | processing 时先建壳，成功再升级 |
| 确认信+收据 | 成功时 | **仅成功时**；processing 只发受理通知 |

---

## 相关文件（开发查阅）

- Webhook：`flask-app/app/routes.py` → `handle_payment_intent_processing` / succeeded / failed  
- 清算锁定：`payments.py`（`booking_has_processing_ach_payment` 等）、`tasks.py`  
- 邮件模板：`emails/order_processing.*`、`emails/receipt.*`  
- 前端：`booking.js`、`installment_modal.js`、`booking-modal.css`
