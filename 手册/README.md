# 手册（给人看）

> 日常只看 **`手册/`**；技术细节在 **`context/`**（给 AI）  
> **更新** 2026-07-28

---

## 我该看哪个？

- **网站安全、SSH、审计日志（`nh-audit`）**
    - → [安全手册.md](安全手册.md)

- **后台操作、建行程、客户报名、订单号（Order number）**
    - → [用户手册.md](用户手册.md)

- **ACH（美国银行转账）付款规则、清算期、邮件与锁定**
    - → [ACH付款规则.md](ACH付款规则.md)

- **域名 / HTTPS**
    - → [域名接入GoDaddy.md](域名接入GoDaddy.md)

- **新开 Cursor Agent**
    - → [新Agent开场白.md](新Agent开场白.md)

---

## 文档一览

- **[安全手册.md](安全手册.md)**
    - SSH（`ssh nhtours`）、`nh-audit` / `--all` / `-a`、改密码、巡检

- **[用户手册.md](用户手册.md)**
    - Trip Builder、Order number、退款、Excel 快照、报名、收据、**分期邮件提醒规则**、Testimonials / Feedback

- **[ACH付款规则.md](ACH付款规则.md)**
    - US bank account（ACH）：Processing → 成功/失败、邮件、清算期锁定、与分期关系

- **[安全手册-凭据.local.md](安全手册-凭据.local.md)**
    - 用户名密码（本地专用，不提交 Git）

- **[域名接入GoDaddy.md](域名接入GoDaddy.md)**
    - nhtours.com DNS + HTTPS

- **[新Agent开场白.md](新Agent开场白.md)**
    - 新开 Agent 时复制话术

---

## 日常流程

- 1 — 本地 `cd flask-app && python run.py`（端口 8080）
- 2 — 满意后告诉 AI「可以 push」
- 3 — GitHub Actions **Deploy** 变绿 → 生产生效
- 新开 Agent — 复制 [新Agent开场白.md](新Agent开场白.md)「通用版」

---

## 和别的目录分工

- **`手册/`**
    - 你只看这里

- **`context/`**
    - AI：API、数据库、部署、开发日志

- **`.cursor/rules/`**
    - AI 自动遵守的规则

- **注意**
    - `context/07` 历史可能过时
    - push 到 `main` 会部署生产
