# Checkout 模块（对抗性 · Priority 1）

本目录是 Playwright 的 **第一个交付模块**：站在 QA 角度尽量打断 Checkout，而不是证明 “能付钱”。

## 运行前

1. 本地 Flask：`cd flask-app && python run.py`（默认 `8080`）
2. 确保 QA 行程存在：`python -m local_tests.setup_test_trip`（slug=`qa-payment-trip-2026`）
3. 本目录：

```bash
cd tests/e2e
cp .env.e2e.example .env.e2e
npm install
npx playwright install chromium
npm run test:checkout
```

## 文件

| 文件 | 意图 |
|------|------|
| `api-chaos.spec.ts` | 非法/空/伪造/并发 POST，断言不 500、不盲信客户端金额 |
| `ui-resilience.spec.ts` | 未选套餐 Continue、连点、刷新、断网、XSS、后退 |

## 刻意不做（留给后续模块）

- 真实 Stripe 刷卡成功（→ Stripe Payment 模块）
- Coupon 全矩阵（→ Coupon 模块）
- Webhook 重复投递（→ Stripe 模块）
- Admin 退款（→ Admin 模块）
