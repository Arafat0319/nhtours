# Booking 模块（对抗性 · Priority 1）

第 3 模块：关注 **建单后幂等、收据门禁、Success 刷新**，不是「付一次就过」。

## 环境

```bash
# flask-app/.env 已有 Stripe Test 时，把同一 sk_test_ 写入：
# tests/e2e/.env.e2e
E2E_STRIPE_SECRET_KEY=sk_test_...
```

无 secret 时：`gates.spec.ts` 仍会跑；`idempotency` / 部分 `success-ui` 会 **skip**（不假绿）。

```bash
cd tests/e2e
npm run test:booking
```

## 文件

| 文件 | 场景 |
|------|------|
| `gates.spec.ts` | receipt/summary/installment 无 token / 假 token |
| `idempotency.spec.ts` | confirm 后 status 风暴单 booking_id；跨单 token；summary 门禁 |
| `success-ui.spec.ts` | 脏 success、刷新风暴、浏览器后退 |

## 未覆盖

- Deposit 建单后分期行数量
- create-free 双提交幂等（需 $0 Pending）
- Webhook 与 status 同时触发的双写竞态（需可控 webhook 注入）
- 邮件只发一封（需 SES 观测）
