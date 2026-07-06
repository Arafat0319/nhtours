# 手册（给人看）

本目录是**人工文档**唯一入口；技术细节在 `context/`（给 AI 用）。

| 文档 | 说明 |
|------|------|
| [用户手册.md](用户手册.md) | 后台操作、客户报名、FAQ |
| [新Agent开场白.md](新Agent开场白.md) | 新开 Agent 时复制粘贴的话术 |
| [域名接入GoDaddy.md](域名接入GoDaddy.md) | **nhtours.com 接到 Lightsail**（GoDaddy DNS + HTTPS） |
| [安全手册.md](安全手册.md) | **生产安全**：审计日志、告警、SSH 巡检、凭据轮换 |

## 日常流程

1. 新开 Agent → 复制 [新Agent开场白.md](新Agent开场白.md) 里的「通用版」
2. 本地自测 → `cd flask-app && python run.py`（8080）
3. 满意后告诉 AI「可以 push」（会更新 `context/` 并触发 Deploy）

## 目录分工

| 目录 | 用途 |
|------|------|
| **`手册/`** | 你只看这里 |
| **`context/`** | AI 读：API、数据库、部署、开发日志 |
| **`.cursor/rules/`** | AI 自动遵守（勿 push、push 前写 07） |
| **`.agent/workflows/`** | 部署/排障分步剧本（按需） |

**注意**：`context/07` 历史可能过时；push 到 `main` 会部署生产。

**最后更新**: 2026-07-05
