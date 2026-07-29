# 订单收据定稿样例（2026-07-28）

本目录保存**已确认版式**的 PDF 样例，供人工对照与 AI 核实风格。  
规则全文：仓库根目录 `.cursor/rules/receipt-pdf-layout.mdc`。  
实现：`app/receipt_pdf.py` + `_booking_receipt_context`。

> 样例基于生产订单当时数据生成，金额会随真实账本变化；**版式与区块顺序**才是要锁住的。

## 分页（按付款方式，不是按已付笔数）

| 文件 | 场景 | 页数 | 用来核对什么 |
|------|------|------|----------------|
| `sample-oneshot-2603SH-002.pdf` | **一次付全款** | 1 | **无** History |
| `sample-deposit-schedule-2612MT-003.pdf` | **定金/分期**（可能只付了 1 笔） | 2 | 第 2 页有 Installment Schedule |
| `sample-multipay-history-2603SH-001.pdf` | 多笔 / payoff | 2 | History + 明细 |

## Trip Total 顺序（定稿）

1. Total Expected (base)  
2. Due this time (base)  
3. 可选说明行：`Includes: Deposit $… + Add-ons $…`（定金/追缴场景；非单独 Deposit 行）  
4. Amount Paid (net base)  
5. Amount Remaining (net base)  

## 视觉要点

- 页头：竖版 NHTOURS logo（蓝 `rgb(0,54,112)`）+ 大标题 + Order number，底边对齐  
- 页脚：邮件品牌 logo `nexus-horizons-email.png`（勿换成页头竖版）  
- 第 1 页页脚横线上方：Paid/Remaining / Due this time 说明  

**样例生成日**：2026-07-28（按付款方式修正 History 后）
