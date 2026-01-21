# API 参考

本文档列出 NH Tours 项目的所有路由和 API 端点。

## 目录

- [路由概览](#路由概览)
- [后台管理路由](#后台管理路由)
- [API 端点](#api-端点)
- [Webhook 端点](#webhook-端点)
- [前台公共路由](#前台公共路由)

---

## 路由概览

| 蓝图 | 前缀 | 说明 |
|------|------|------|
| admin | `/admin` | 后台管理功能 |
| auth | `/auth` | 用户认证 |
| main | `/` | 前台公共页面 |
| (routes.py) | `/api`, `/webhook` | API 和 Webhook |

---

## 后台管理路由

### 仪表盘

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/` | GET | 仪表盘首页 |
| `/admin/reports` | GET | 财务报表页面 |

### 行程管理

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips` | GET | 行程列表（卡片视图） |
| `/admin/trips/calendar` | GET | 行程日历视图 |
| `/admin/trips/new` | GET | 创建新行程，跳转 Trip Builder |
| `/admin/trips/<id>` | GET | 行程详情/订单管理页 |
| `/admin/trips/<id>/publish` | POST | 发布行程 |
| `/admin/trips/<id>/archive` | POST | 归档行程 |
| `/admin/trips/<id>/delete` | POST | 删除行程 |

### Trip Builder

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips/<id>/edit/step/<n>` | GET | 显示步骤 n 表单 |
| `/admin/trips/<id>/edit/step/<n>` | POST | 保存步骤 n 数据 |

步骤说明：
- Step 1: 基础信息
- Step 2: 描述
- Step 3: 套餐管理
- Step 4: 附加选项
- Step 5: 购买者信息
- Step 6: 参与者问卷
- Step 7: 折扣码

### 订单管理

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips/<id>/bookings` | GET | 行程订单列表 |
| `/admin/trips/<id>/bookings/<bid>` | GET | 订单详情 |
| `/admin/trips/<id>/bookings/<bid>/receipt` | GET | 生成收据 |
| `/admin/trips/<id>/bookings/<bid>/refund` | POST | 发起退款 |

### 客户管理

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/customers` | GET | 客户列表 |
| `/admin/customers/<id>` | GET | 客户详情 |
| `/admin/leads` | GET | 潜在客户列表 |

### 数据导出

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips/<id>/export` | GET | 导出订单 Excel |
| `/admin/trips/<id>/financials` | GET | 获取财务统计 JSON |

---

## API 端点

### 支付相关

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/payment/intent` | POST | 创建 PaymentIntent |
| `/api/payment/status` | GET | 查询支付状态 |
| `/api/payment/fee` | POST | 计算手续费 |

#### POST /api/payment/intent

创建或更新 Stripe PaymentIntent。

**请求体**:

```json
{
  "trip_id": 1,
  "payment_type": "deposit",
  "amount": 500,
  "booking_data": {
    "packages": [...],
    "participants": [...],
    "buyer_info": {...}
  },
  "payment_intent_id": null,
  "booking_id": null,
  "installment_id": null
}
```

**响应**:

```json
{
  "clientSecret": "pi_xxx_secret_xxx",
  "paymentIntentId": "pi_xxx",
  "pendingBookingId": 123
}
```

#### GET /api/payment/status

查询支付状态（前端轮询）。

**参数**:
- `payment_intent_id`: PaymentIntent ID

**响应**:

```json
{
  "status": "succeeded",
  "booking_id": 456,
  "redirect_url": "/booking/success?booking_id=456"
}
```

#### POST /api/payment/fee

计算支付手续费。

**请求体**:

```json
{
  "amount": 1000,
  "funding": "credit",
  "brand": "visa"
}
```

**响应**:

```json
{
  "base_amount": 1000,
  "fee": 29,
  "total": 1029
}
```

### 折扣码

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/discount/validate` | POST | 验证折扣码 |

**请求体**:

```json
{
  "trip_id": 1,
  "code": "SAVE10"
}
```

**响应**:

```json
{
  "valid": true,
  "type": "percentage",
  "amount": 10,
  "message": "折扣码有效"
}
```

### 行程数据

| 路由 | 方法 | 说明 |
|------|------|------|
| `/api/trips/<id>` | GET | 获取行程详情 JSON |
| `/api/trips/<id>/availability` | GET | 获取剩余名额 |

---

## Webhook 端点

| 路由 | 方法 | 说明 |
|------|------|------|
| `/webhook/stripe` | POST | Stripe Webhook 接收端点 |

### 处理的事件

| 事件类型 | 处理函数 | 说明 |
|----------|----------|------|
| `payment_intent.succeeded` | `handle_payment_intent_succeeded` | 支付成功 |
| `payment_intent.payment_failed` | `handle_payment_failed` | 支付失败 |
| `checkout.session.completed` | `handle_checkout_completed` | Checkout 完成 |
| `charge.refunded` | `handle_charge_refunded` | 退款完成 |

### Webhook 签名验证

```python
@app.route('/webhook/stripe', methods=['POST'])
def stripe_webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400
    
    # 处理事件...
```

---

## 前台公共路由

### 行程页面

| 路由 | 方法 | 说明 |
|------|------|------|
| `/trips` | GET | 行程列表页 |
| `/trips/<slug>` | GET | 行程详情页 |
| `/trips/<slug>/book` | GET | 报名页面（5步向导） |

### 支付页面

| 路由 | 方法 | 说明 |
|------|------|------|
| `/payment/pending` | GET | 支付处理中页面 |
| `/booking/success` | GET | 支付成功页面 |

### 其他页面

| 路由 | 方法 | 说明 |
|------|------|------|
| `/contact` | GET/POST | 联系表单 |
| `/about` | GET | 关于我们 |

---

## 认证路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/auth/login` | GET/POST | 登录页面 |
| `/auth/logout` | GET | 退出登录 |

---

## 响应格式规范

### 成功响应

```json
{
  "success": true,
  "data": { ... },
  "message": "操作成功"
}
```

### 错误响应

```json
{
  "success": false,
  "error": "error_code",
  "message": "错误描述"
}
```

### 常见错误码

| 错误码 | HTTP 状态 | 说明 |
|--------|-----------|------|
| `invalid_request` | 400 | 请求参数无效 |
| `unauthorized` | 401 | 未登录 |
| `forbidden` | 403 | 无权限 |
| `not_found` | 404 | 资源不存在 |
| `payment_failed` | 402 | 支付失败 |

---

## 更新日期

**最后更新**: 2026-01-21
