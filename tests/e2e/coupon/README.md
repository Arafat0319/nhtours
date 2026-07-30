# Coupon 模块（对抗性 · Priority 1）

关注 **伪造金额、trip 错绑、apply 竞态、$0 create-free 幂等**。

## 前置

- Flask `:8080` + `qa-payment-trip-2026`
- 折扣码 **`QAZERO`**（fixed $5000，绑 QA trip）。可用：

```bash
cd flask-app
# 与 e2e_full_suite 同逻辑：缺则创建
python -c "from app import create_app, db; from app.models import Trip, DiscountCode; app=create_app();
app.app_context().push(); t=Trip.query.filter_by(slug='qa-payment-trip-2026').first();
c=DiscountCode.query.filter(db.func.upper(DiscountCode.code)=='QAZERO').first();
... "
```

或跑过一次 `python local_tests/e2e_full_suite.py`。

```bash
cd tests/e2e
npm run test:coupon
```

## 文件

| 文件 | 场景 |
|------|------|
| `validate-chaos.spec.ts` | 空码 / XSS / 负金额 / 大小写 / 错 trip |
| `apply-free.spec.ts` | 伪造 amount、apply 往返、并行 apply、submit 伪造、QAZERO→create-free 风暴 |

## 未覆盖

- percent 封顶 / 低于 Stripe $0.50 边界（需专用小额码）
- admin 建码 CRUD UI
