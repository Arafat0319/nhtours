# Stripe Payment Element 测试模块

本目录为独立可运行的 Stripe 沙盒支付验证模块，用于测试 **站内支付 + 动态手续费** 逻辑。

## 启动方式

1. 安装依赖
   ```bash
  pip install -r testing_payment/requirements.txt
   ```
2. 准备环境变量（复制并修改）
   ```bash
  copy testing_payment/env.example testing_payment/.env
   ```
3. 启动服务
   ```bash
  python testing_payment/app.py
   ```

默认运行在 `http://localhost:5000`。

## Webhook 转发

```bash
stripe listen --forward-to localhost:5000/api/stripe/webhook
```

## 测试卡

- 成功支付：`4242 4242 4242 4242`
- 失败支付：`4000 0000 0000 9995`
- 任意未来日期与 CVC 均可

## 业务规则

- base_amount 来自 mock 订单（cents）
- 信用卡（funding == credit）加收 2% 手续费并向上取整到 cents
- 其他情况不加手续费

## 自动化测试脚本

前提：服务已启动（`python testing_payment/app.py`）。

运行脚本（验证 credit/debit/prepaid 的报价差异）：
```bash
python testing_payment/scripts/auto_quote_test.py
```

脚本会：
- 生成测试 PaymentMethod
- 调用 `/api/quote` 输出 funding 与 fee
- 调用 `/api/payment-intent` 验证可创建 PI

如需指定服务地址，可在 `.env` 中设置：
```
TEST_API_BASE=http://localhost:5000
```

## Webhook 日志

启动服务后，终端会输出：
- `Quote computed ...`
- `Webhook received type=...`
- `Order marked PAID/FAILED ...`

## 未来合并回正式模块时需要替换的点

- `services/order_store.py`：替换为真实的 Booking/Order 数据模型与数据库
- mock 数据（packages/add-ons/participants）：替换为正式订单数据
- 金额计算：迁移到统一 pricing/fee 服务
- 内存订单状态：替换为 Payment/Booking 状态字段与日志
