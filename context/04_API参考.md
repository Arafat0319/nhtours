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
| admin | `/admin` | 后台管理功能（含认证） |
| main | `/` | 前台公共页面、API、Webhook |

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
| `/admin/trips` | GET | 行程列表（卡片视图；`?filter=`、`?view=calendar`） |
| `/admin/trips?view=calendar` | GET | 行程日历视图（FullCalendar） |
| `/admin/trips/json` | GET | 日历/列表用 JSON 数据 |
| `/admin/trips/new` | GET | 创建新行程，跳转 Trip Builder |
| `/admin/trips/<id>/manage` | GET | 行程详情 / 订单管理页 |
| `/admin/trips/<id>/deactivate` | POST | 停用行程（`status=deactivated`） |
| `/admin/trips/<id>/reactivate` | POST | 重新启用 |
| `/admin/trips/<id>/archive` | POST | 归档行程 |
| `/admin/trips/<id>/copy` | POST | 复制行程 |
| `/admin/trips/<id>/delete` | POST | 删除行程 |

> **发布**：无独立 `/publish` 路由；Trip Builder 步骤完成度达标后自动 `published`，或通过 reactivate 恢复。

### Trip Builder

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips/<id>/builder/<step>` | GET | 显示步骤表单 |
| `/admin/trips/<id>/builder/<step>` | POST | 保存步骤数据 |

**step 参数值**：
- `basics`: 基础信息
- `description`: 描述
- `packages`: 套餐管理
- `addons`: 附加选项
- `buyer_info`: 购买者信息
- `participants`: 参与者问卷
- `coupons`: 折扣码

### 订单管理

订单列表嵌入 `/admin/trips/<id>/manage` 页面，无独立 list 路由。

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips/<id>/bookings/add` | POST | 后台手动添加订单 |
| `/admin/trips/<trip_id>/bookings/<booking_id>` | GET/POST | 订单详情 / 编辑 |
| `/admin/trips/<trip_id>/bookings/<booking_id>/receipt` | GET | 生成收据 |
| `/admin/trips/<trip_id>/bookings/<booking_id>/refund` | POST | 发起退款 |

### 客户管理

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/customers` | GET | 客户列表 |
| `/admin/customers/<id>` | GET | 客户详情 |
| `/admin/customers/leads` | GET | 潜在客户列表 |
| `/admin/customers/testimonials` | GET | Testimonials 列表；`?status=`、`?source=homepage\|feedback` |
| `/admin/customers/testimonials/save` | POST | 弹窗创建/更新 JSON `{ id?, quote, author_name, organization?, status }` |
| `/admin/customers/testimonials/<id>/json` | GET | 编辑弹窗加载单条 JSON |
| `/admin/customers/testimonials/new` | GET/POST | 新建 Testimonial（独立页，备用） |
| `/admin/customers/testimonials/<id>/edit` | GET/POST | 编辑 Testimonial（独立页，备用） |
| `/admin/customers/testimonials/reorder` | POST | 保存轮播顺序 JSON `{ ids: [...] }` |
| `/admin/customers/testimonials/<id>/approve` | POST | 批准 |
| `/admin/customers/testimonials/<id>/reject` | POST | 拒绝 |
| `/admin/customers/testimonials/<id>/delete` | POST | 删除 |

### 数据导出

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/trips/<id>/bookings/export` | GET | 导出订单 Excel（需登录，xlsx 内含 Web 连接，打开时自动刷新） |
| `/admin/trips/bookings/export/csv` | GET | 按 token 导出 Participants：`?token=xxx` CSV；`?token=xxx&format=html` HTML（供 Excel 刷新用，无需登录） |
| `/admin/trips/<id>/financials` | GET | 获取财务统计 JSON |

---

## API 端点

### 支付相关

| 路由 | 方法 | 说明 |
|------|------|------|
| `POST /trips/<slug>` | POST | **AJAX 报名首步**：创建 PendingBooking + Stripe PaymentIntent，返回 `client_secret` |
| `/api/payment/quote` | POST | 根据 PendingBooking 计算报价 |
| `/api/payment/intent` | POST | 更新已有 PaymentIntent 的金额与 metadata（用于确认前写入手续费等） |
| `/api/payment/status` | GET | 查询支付状态 |
| `/api/payment/fee` | POST | 计算手续费 |
| `/api/booking/create-free` | POST | 零元订单直接创建 Booking |
| `/api/booking/<id>/summary` | GET | 订单摘要 JSON |
| `/booking/payment/<id>` | GET | 独立支付页（邮件链接等） |
| `/booking/<id>/receipt` | GET | 前台收据页 |

#### POST /api/payment/intent

更新已有 Stripe PaymentIntent 的金额与 metadata（不创建新 PI；首步创建在报名提交 `POST /trips/<slug>` 的 JSON 流程中完成）。前端在用户填写卡信息后、确认支付前调用，用于按卡种计算手续费并更新 PI 金额。

**请求体**（三选一标识支付对象）:

- `payment_method_id`（必填）：Stripe PaymentMethod ID（由前端 Stripe Elements 创建）
- 以下其一（必填）：`payment_intent_id`（新流程，首次支付）、`booking_id`（已有订单）、`installment_id`（分期单期）
- `payment_plan`（可选）：`full` \| `deposit_installment`，默认 `full`
- `payment_step`（可选）：`initial` \| `payoff` 等

```json
{
  "payment_intent_id": "pi_xxx",
  "payment_method_id": "pm_xxx",
  "payment_plan": "full",
  "payment_step": "initial"
}
```

或使用已有订单：`"booking_id": 123`；或分期：`"installment_id": 456`。

**响应**:

```json
{
  "payment_intent_id": "pi_xxx",
  "final_amount": 5029
}
```

- `final_amount`: 更新后的应付金额（分，含手续费）。

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
| `/api/discount/validate` | POST | 验证折扣码并返回折扣金额 |
| `/api/discount/apply` | POST | 应用折扣码到订单 |

**POST /api/discount/validate 请求体**:

```json
{
  "trip_id": 1,
  "code": "SAVE10",
  "order_amount": 2000
}
```

**响应**（有效时）:

```json
{
  "valid": true,
  "message": "Discount code applied successfully",
  "discount": {
    "id": 1,
    "code": "SAVE10",
    "type": "percent",
    "value": 10,
    "discount_amount": 200,
    "final_amount": 1800
  }
}
```

> `type` 取值：`percent` / `fixed`（非 `percentage`）。

---

## Webhook 端点

| 路由 | 方法 | 说明 |
|------|------|------|
| `/webhooks/stripe` | POST | Stripe Webhook（生产推荐） |
| `/api/stripe/webhook` | POST | 同上（兼容 Stripe CLI 默认路径） |

### 处理的事件

| 事件类型 | 处理函数 | 说明 |
|----------|----------|------|
| `payment_intent.succeeded` | `handle_booking_payment_intent_succeeded` + `handle_payment_intent_succeeded` | 支付成功（双处理器） |
| `payment_intent.payment_failed` | `handle_payment_intent_failed` | 支付失败 |
| `checkout.session.completed` | `handle_checkout_completed` | Checkout 完成 |
| `charge.refunded` | `handle_refund` | 退款完成 |

### 本地测试

```bash
cd flask-app
python run.py   # 默认 http://localhost:8080
stripe listen --forward-to localhost:8080/webhooks/stripe
```

---

## 前台公共路由

### 行程页面

| 路由 | 方法 | 说明 |
|------|------|------|
| `/trips/<slug>` | GET/POST | 行程详情页（GET 展示；POST 为 AJAX 报名提交，创建 PendingBooking + PaymentIntent） |
| `/trips/<slug>/design-preview` | GET/POST | 设计预览实验页（与正式页同数据，渲染实验模板；POST 逻辑同正式页） |

> 无 `/trips` 列表页、无 `/trips/<slug>/book` 独立向导；报名在详情页弹窗内完成（5 步）。

### 内容页（Asia / North America 等）

| 路由 | 方法 | 说明 |
|------|------|------|
| `/asia`、`/asia/educational`、`/asia/family`、`/asia/business` 等 | GET | Asia 内容页 |
| `/north-america`、`/north-america/educational`、`/north-america/newyork` 等 | GET | North America 内容页 |
| `/mindx` | GET | Mindx 页 |
| `/privacy` | GET | 隐私政策 |
| `/terms` | GET | 服务条款 |

### 设计预览与首页

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET/POST | 正式首页（Modern V1）；POST：`form=newsletter` \| `form=testimonial`（JSON 或表单） |
| `/feedback` | GET/POST | 行程结束 Feedback 页（私有链接）；POST：`form=feedback` |
| `/home-classic` | GET/POST | **旧版首页存档**（经典透明导航 + Wukong 叙事）；POST 支持 newsletter |
| `/home-preview` | GET/POST | 兼容旧链接：GET **301** 重定向至 `/`；POST 与 `/` 一致 |
| `/our-team` | GET | Our Team 正式页 |

**`/` 关联文件**（Modern V1 正式首页）：

| 类型 | 路径 |
|------|------|
| 路由 | `app/routes.py` → `index()` |
| 页面模板 | `templates/index.html` |
| Layout | `templates/base.html`（全站新导航） |
| 导航 | `templates/includes/nav.html`；`static/css/site-nav.css`；`static/js/home-preview-nav.js` |
| 首页样式/脚本 | `static/css/home-preview.css`、`static/js/home-preview.js` |

**`/home-classic` 关联文件**（旧版存档）：

| 类型 | 路径 |
|------|------|
| 路由 | `app/routes.py` → `index_classic()` |
| 页面模板 | `templates/index_classic.html` |
| 导航 | `templates/includes/legacy/nav_classic.html`；`static/js/legacy/navigation_classic.js` |

**存档模板**（无独立路由）：`templates/index_experimental.html`（原 `/home-preview` 实验页）

**`/our-team` 关联文件**：

| 类型 | 路径 |
|------|------|
| 路由 | `app/routes.py` → `our_team()` |
| 页面模板 | `templates/our_team.html`（extends `base.html`，`body.our-team-page`） |
| 导航 | 继承 `base.html` → `includes/nav.html` |
| 样式 | `static/css/home-preview.css`（`body.our-team-page` 下团队区块） |
| 成员照片 | `static/images/content/team/luke-hao.png`、`amy-wu.png`、`rui-dong.png`、`sophia-chen.png` |

**样式隔离说明**：Our Team 的 hero 高度、标题字号等写在 `body.our-team-page` 选择器下，修改时不影响正式首页 `/`。

### 支付页面

| 路由 | 方法 | 说明 |
|------|------|------|
| `/payment/pending` | GET | 支付处理中页面 |
| `/booking/success` | GET | 支付成功页面 |
| `/pay-installment/<id>` | GET | 分期付款弹窗页（query: token=，模板 installment_modal_page.html） |
| `/pay-installment/<id>/payoff` | GET | 一次性付清页（query: token=） |

### 其他页面

| 路由 | 方法 | 说明 |
|------|------|------|
| `/contact` | GET/POST | 联系表单 |
| `/about` | — | **未实现**（文档占位；About Us 相关链接目前多指向 `/`） |

---

## 认证路由

| 路由 | 方法 | 说明 |
|------|------|------|
| `/admin/login` | GET/POST | 登录页面 |
| `/admin/logout` | GET | 退出登录 |

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

**最后更新**: 2026-06-18（对照代码审计：路由/Webhook/支付 API 修正）
