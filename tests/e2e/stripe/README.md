# Stripe Payment 模块（对抗性 · Priority 1）

Checkout 之后的第二模块。目标：**伪造 webhook、status 风暴、断网 Stripe.js、用 pi_ 骗 create-free**，而不是刷卡成功。

## 运行

```bash
# Flask + Stripe Test keys in flask-app/.env
cd tests/e2e
npm run test:stripe
```

`seedCheckoutIntent` 依赖真实 Test Stripe；若种子失败，相关用例会 `skip`（环境问题），不会假绿成支付成功。

## 覆盖

| 文件 | 场景 |
|------|------|
| `api-chaos.spec.ts` | 未签名 webhook、垃圾 payload、status 伪造/并发、quote/intent 非法、种子 PI + status 风暴、quote 伪造金额、create-free(pi_) |
| `ui-chaos.spec.ts` | 拦截 Stripe.js、pending/success 脏 query |

## 未覆盖（下一模块或更深）

- 真实 `pm_card_visa` confirm + webhook 双投幂等
- 失败卡 / 3DS / requires_action
- charge.refunded 重复
- Payment Element 双击 Confirm
