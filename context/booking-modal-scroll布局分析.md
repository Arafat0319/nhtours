# booking-modal-scroll 水平布局无法生效的原因分析

## 1. DOM 结构概览

```
#booking-modal-scroll                    ← 滚动容器，flex 容器
├── form#bookingForm                     ← 子项 1：左侧（步骤内容）
│   └── div.w-full.lg:max-w-[535px]      ← 表单内容区
└── div#booking-modal-right              ← 子项 2：右侧（Your Booking）
```

- **#booking-modal-scroll** 有两个直接子元素：`form` 和 `#booking-modal-right`。
- 设计意图：在 `lg`（≥1024px）下为 **flex-row**，即 form 与右侧栏左右并排。

---

## 2. 当前样式

| 元素 | 关键 class | 含义 |
|------|------------|------|
| #booking-modal-scroll | `flex flex-col lg:flex-row` | 默认纵向，lg 横向 ✓ |
| form | `w-full lg:flex-1 lg:min-w-0` | **w-full 无 lg 覆盖** → 大屏仍是 100% 宽 |
| form 内层 div | `w-full lg:max-w-[535px] flex-1 min-w-0` | 左栏内容区 |
| #booking-modal-right | `w-full lg:w-[335px] lg:min-w-[335px] flex-shrink-0` | 右栏固定 335px ✓ |

---

## 3. 无法水平布局的根本原因

**form 使用了 `w-full`，且没有在任何断点下被覆盖。**

- `w-full` = `width: 100%`，对所有断点（包括 lg）都生效。
- 在 `lg` 时，虽然父级是 `flex-row`，但 **flex 子项若显式设为 `width: 100%`，会占满整行**。
- 结果：form 占满 #booking-modal-scroll 的整行宽度（例如 870px），**右侧 335px 的 #booking-modal-right 没有空间留在同一行**，只能被挤到下一行或产生横向溢出，看起来就是「无法水平布局」。

即便有 `lg:flex-1 lg:min-w-0`，**在存在 `width: 100%` 的情况下，flex 的收缩/分配仍受该宽度约束**，所以仅靠 flex-1 无法让出右侧空间。

---

## 4. 解决思路

在 **lg 断点** 下，让 form **不再使用 100% 宽度**，改为由 flex 分配剩余空间：

- 增加 **`lg:w-0`**（或 `lg:min-w-0` 已存在时可配合 **`lg:flex-1`**），使 form 在 lg 下不强制 100% 宽，可被 flex 收缩并只占「剩余空间」。
- 这样：
  - 左栏（form）：占满「容器宽度 − 335px」；
  - 右栏 #booking-modal-right：固定 335px，与 form 同一行显示。

推荐 form 的 class 调整为：

- 保留：`w-full`（小屏仍整行）、`lg:flex-1 lg:min-w-0`；
- **新增：`lg:w-0`**，即：`w-full lg:w-0 lg:flex-1 lg:min-w-0`。

这样在 lg 下，form 的宽度由 flex 决定，水平布局即可生效。

---

## 5. 其他可能影响因素（可排查）

- **Tailwind 未生成 lg 样式**：若通过 CDN 或未扫描到该模板，可能没有生成 `lg:flex-row`、`lg:w-0` 等，需确认构建/引入方式。
- **弹窗实际宽度不足**：若 #booking-modal 或父级在 lg 下实际宽度小于 870px，或 max-width 更小，也可能看起来仍像纵向；一般 870px 足够 535 + 335 并排。
- **overflow**：当前 `overflow-x-hidden` 会隐藏横向溢出，若之前是「本应一行但被挤出去」，会表现为只看到一列；修复宽度分配后，溢出消失，两列可同时可见。

---

**结论**：水平布局不生效的直接原因是 **form 的 `w-full` 在 lg 下未被覆盖**，导致整行被 form 占满。给 form 增加 **`lg:w-0`** 后，由 flex 分配宽度，即可实现左右并排。

---

## 6. 窄屏布局（2026-02-09 实现）

**需求**：缩小浏览器时 Continue 按钮固定在最下面，且不改 DOM 顺序（left-col 仍在 right 前）。

**方案**：

1. **左侧列包装器**：在 `#booking-modal-scroll` 下增加 **`#booking-modal-left-col`** 包裹 form，大屏下由媒体查询设置 `width: 0; flex: 1 1 0%`，左栏与 `#booking-modal-right`（335px）并排。
2. **窄屏（max-width: 1023px）**：
   - **`#booking-modal-scroll`** 使用 **`flex-direction: column-reverse`**：视觉顺序变为 Your Booking 在上、步骤 + 按钮在下，Continue 自然在整块内容底部。
   - **`#booking-modal-btn-bar`**（Continue/Confirm 所在 div）设置 **`position: sticky; bottom: 0`**，滚动时贴在视口底部。
   - 弹窗卡片固定高度 `height: calc(100vh - 8rem)`，内容区可滚动。
3. **滚轮**：窄屏下不拦截滚轮，由 `#booking-modal-scroll` 或内部区域原生滚动，避免整块被滚走导致按钮看不见。

窄屏样式放在页面底部 `<style id="booking-modal-narrow-styles">` 内，确保覆盖其它样式。
