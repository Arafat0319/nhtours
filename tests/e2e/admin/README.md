# Admin 模块（对抗性 · Priority 1）

关注 **匿名门禁、staff vs admin、退款校验、export token、收据**。

## 环境

```bash
# tests/e2e/.env.e2e
E2E_ADMIN_USERNAME=nh_ops_947d43
E2E_ADMIN_PASSWORD=...   # 或导出 TEST_ADMIN_PASSWORD
# optional staff (defaults to local pytest fixture):
# E2E_STAFF_USERNAME=_pytest_staff
# E2E_STAFF_PASSWORD=pytest-staff-temp
# refund/receipt paid path also needs:
# E2E_STRIPE_SECRET_KEY=sk_test_...
```

```bash
cd tests/e2e
npm run test:admin
```

无 admin 密码时：`gates.spec.ts` 仍跑；角色/退款用例 skip。

## 文件

| 文件 | 场景 |
|------|------|
| `gates.spec.ts` | 匿名 302、export token、无 CSRF 登录、错密 |
| `roles-money.spec.ts` | staff 403 export/refund；admin 退款校验/IDOR；admin 收据 PDF |

## 未覆盖

- 真退款打 Stripe（避免污染账本；仅校验器）
- CSRF 跨站（SameSite 浏览器行为）
- 登录爆破限速（易锁 IP，不默认跑）
