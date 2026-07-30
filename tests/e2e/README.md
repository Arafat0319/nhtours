# NH Tours Playwright E2E

QA 对抗性自动化。原则：**先打坏，再证明 happy path**。

## 模块

| 目录 | 内容 |
|------|------|
| `checkout/` | 报名结账入口与 API 边界 |
| `stripe/` | PI / Webhook / 幂等与中断；`webhook-idempotency` 签名双投 |
| `booking/` | 建单幂等 / 门禁 / Success；`receipt-ledger` 金额细节 |
| `coupon/` | 折扣边界 / $0 create-free 幂等 |
| `admin/` | 后台门禁 / 角色 / 退款校验 |
| `installment/` | 分期 token / quote；`pay-detail` 真确认 |
| `upload/` | 报名附件 magic / trip 绑定 |
| `public/` | 前台页冒烟 + 表单校验 |
| `messaging/` | 后台消息门禁与草稿校验 |
| `builder/` | Trip Builder 各步 + 删行程分权 |
| `crm/` | Leads / Testimonials 分权 |
| `export/` | data-source-url → CSV/HTML token 链 |

```bash
cd tests/e2e
npm test
```

付费 / admin / 分期 fixture 需：`E2E_STRIPE_SECRET_KEY`、`E2E_ADMIN_*`（或 `TEST_ADMIN_PASSWORD`）、本机 Flask `:8080` + `qa-payment-trip-2026`。

## 公共层

- `fixtures/base.ts` — 扩展 test（page objects + JS error 收集）
- `helpers/` — env / API / chaos / paid-booking / discount / admin-auth / installment-fixture
- `pages/` — Page Object
