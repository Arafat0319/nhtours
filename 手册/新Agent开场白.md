# 新 Agent 开场白

复制下面整段发给 Agent，把最后一行换成你的任务。

```
这是 NH Tours 项目：Flask 旅游网站 + WeTravel 风格后台。

请先读：context/AI_快速参考.md → context/00_项目概览.md → 按任务读 context/ 其它文档。
07_开发日志 只看最近条目；与 04/02/代码冲突时以代码和 04/02 为准。
遵守 .cursorrules；未经我同意不要 git push。

本地：cd flask-app && python run.py（8080）
读完后 3～5 条总结，再执行。

【我的任务】
```

## 按场景加一句（可选）

| 场景 | 追加 |
|------|------|
| UI | 读 context/05_UI设计系统.md |
| 支付/报名 | 读 context/03_功能模块/报名付款系统.md、04_API参考.md |
| 订单号 / Order number | 读 context/AI_快速参考.md「业务单号」+ context/02；逻辑在 app/order_numbers.py |
| 数据库 | 对照 context/02_数据库设计.md + migrations |
| 部署 | 读 context/06 或 .agent/workflows/；等我确认再 push |
| 只改本地 | 不要 commit/push |
