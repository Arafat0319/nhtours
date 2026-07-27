# 报名弹窗 Pencil 设计稿与代码对照

本文档说明 `designs/booking-modal.pen` 中的设计如何对应项目里的 **报名弹窗** 代码与视觉规范，便于在 Pencil 中调视觉后落回模板/CSS。

> **2026-07 起**：正式 `/trips/<slug>` 已使用 `_modal_steps_experimental.html`（套餐卡 + Travelers 步进器）。下文部分描述仍对旧 `_modal_steps.html`（Uiverse 数量下拉），作历史对照；落代码时以 experimental + `booking-modal.css` 为准。

---

## 1. 代码与资源位置

| 类型 | 路径 |
|------|------|
| 弹窗 HTML 结构 | `flask-app/app/templates/booking/trip_booking.html` |
| 步骤内容（**现用**） | `flask-app/app/templates/booking/_modal_steps_experimental.html` |
| 步骤内容（旧对照） | `flask-app/app/templates/booking/_modal_steps.html` |
| 支付步骤共用片段 | `flask-app/app/templates/booking/_modal_payment_step_content.html` |
| 弹窗专用 CSS | `flask-app/app/static/css/booking-modal.css` |
| 内联/覆盖样式 | `trip_booking.html` 内 `<style>` 及部分内联 style |

---

## 2. 弹窗整体

| 项目 | 代码/规范 | Pencil 对应 |
|------|-----------|-------------|
| 遮罩 | `background-color: rgba(39, 43, 43, 0.88)` | 可在画布外或单独帧表示 |
| 卡片 | `max-width: 870px`，`border-radius: 0.5rem`，`box-shadow: 0 4px 24px rgba(0,0,0,0.12)` | 主卡片帧 870×fit_content，圆角 8px |
| 顶部留白 | `margin-top: 5rem`，`padding-top: 60px` | 由画布或外层留白体现 |

---

## 3. Header（头部）

| 元素 | 代码/规范 | Pencil 对应 |
|------|-----------|-------------|
| 背景 | `#f4f4f5`，高 `180px`，上圆角 `0.5rem` | Header 帧 fill #f4f4f5，height 180 |
| 关闭按钮 | `top: 12px; right: 12px`，40×40，SVG 22×22，hover 灰底 | 右上关闭按钮帧 + “×” 文本 |
| 行程图 | 103×103 圆图，`margin-top: -52px`（压卡片上缘） | 椭圆 103×103，fill #e5e7eb |
| 标题 | `font-size: 1.25rem`，`font-weight: 700`，`#1f2937` | 标题文本 20px / 700 / #1f2937 |
| 日期 | `0.875rem`，#4b5563，配 14×14 日历图标 | 日期行 + 小矩形作图标占位 |
| 步骤条 | Package（当前 #1f2937 / 600）> Participant info > Add-ons > Payment（#9ca3af），分隔符 “ > ” | 步骤行：Package 粗体深色，其余灰色，“ > ” 分隔 |

---

## 4. 左侧：步骤区（Step 1 Select package）

| 元素 | 代码/规范 | Pencil 对应 |
|------|-----------|-------------|
| 步骤区内边距 | `padding: 20px 30px 12px 30px`（section） | 左侧列 padding 20 30 12 30 |
| 步骤标题 | “Select package”，1.125rem / 600 / #111827 | 步骤标题文本 |
| 套餐行 | 每行：左侧数量选择器 + 右侧套餐信息，行间 `border-bottom: 1px solid #d1d5db` | 每行：96×40 数量框 + 套餐名称/价格/ meta/描述/分期 |
| 数量选择器 | 96–116px 宽，40px 高，`#f8fafc` 底，`2px #e2e8f0` 边框，圆角 5px，Uiverse 风格 | 数量框：96×40，fill #f8fafc，stroke #e2e8f0，圆角 5 |
| 套餐名/价格 | 16px / 600 / #111827，同行左右分布 | 名称左、价格右 |
| 第二行 meta | Available until · Only X left；Deposit（有分期时），0.9375rem / #4b5563、#6b7280 | Available until · Only 8 left；Deposit: $500 |
| Payment plan 块 | 标题 0.875rem / 600；左侧日期列、右侧金额列，灰色 #6b7280，金额右对齐 | “Payment plan” + Deposit / Jun 1, 2025 | $500 / $1,500 |
| Continue 按钮 | 高 40px，绿底 #16a34a，白字，14px | 绿色按钮 “CONTINUE” |

---

## 5. 右侧：Your Booking

| 元素 | 代码/规范 | Pencil 对应 |
|------|-----------|-------------|
| 背景 | `#faf9f6`（模板内联）；CSS lg 下 `#f8fafc`，左边框 `#e2e8f0` | 右侧列 #faf9f6 或 #f8fafc |
| 宽度 | `335px`（lg） | 右列 width 335 |
| “Your Booking” 标题 | 16px / medium / #111827，下边 `border-bottom` | 标题 + 底部分隔线 |
| Discount code 行 | 输入框 + Apply 等高 40px，`gap` 约 1rem，下边 `border-bottom` | 输入框占位 + “Apply” 按钮，gap 16 |
| 输入框/Apply | 高 40，白底，#e2e8f0 边框，圆角 5px；focus 蓝框 + 光晕 | 浅灰底框 + 圆角 5 |
| Trip Total | 左 “Trip Total”，右金额 18px semibold #111827 | 一行左右分布 |
| Fee | 13px #6b7280，`border-top: 1px solid #e5e7eb` | “Fee” / “$0.00” + 顶部分隔线 |
| Due at Booking | `border-t border-gray-200 pt-3`，左 label 粗体，右金额 `text-lg font-bold` | 顶部分隔 + “Due at Booking” / 金额 |

---

## 6. 色彩与字体速查

| 用途 | 色值 / 字号 |
|------|-------------|
| 标题/强调 | #111827，600/700 |
| 正文/次要 | #4b5563，#6b7280 |
| 步骤未选/分隔 | #9ca3af |
| 边框/分割线 | #d1d5db，#e2e8f0，#e5e7eb |
| 输入背景 | #f8fafc |
| 主按钮 | #16a34a（绿），hover #15803d |
| 焦点/主题蓝 | #0066ff，光晕 rgba(0,102,255,0.2) |
| 必填星号 | #ea580c |
| “Only X left” | 橙色 #d97706 / 600 |

---

## 7. 在 Pencil 中改完后的落地步骤

1. 在 `.pen` 里改颜色、间距、圆角、字号等，用 **get_screenshot** 确认。
2. 把要改的数值记下来（如：Header 高改为 200px、主按钮绿改为 #0ea5e9）。
3. 在项目里对应修改：
   - 全局/弹窗内联样式 → `trip_booking.html` 内 `<style>` 或内联 `style`；
   - 弹窗专用类 → `booking-modal.css`；
   - 结构或 class 名 → `_modal_steps.html` / `trip_booking.html` 弹窗区块。

若你提供「在 Pencil 里改成了什么样」（或截图 + 数值），我可以按此文档帮你写出具体要改的 CSS/HTML 片段。

---

**最后更新**: 2026-03-03（与 Pencil 设计稿细节同步）
