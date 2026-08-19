# Loom

本项目是一个单实例、常驻运行的思想园丁：FastAPI 接 Telegram webhook，后台 Gardener Worker 与 Web 服务运行在同一个 Railway Python 进程。它使用 PostgreSQL 持久化所有任务，**不使用 Railway Cron**。

## 关键架构

- Webhook：验证 → `processed_updates` 去重 → 存 Message → 建立 `AgentJob` → 立即返回 200。
- Worker：从 DB 认领到期任务 → 调 `brain.run_agent`（如需要）→ 原子保存回复 → 经 `channels.py` 投递。
- 重启恢复：running 任务使用 5 分钟 lease；过期后会变回 pending 并重试。
- 用户身份：核心关联 `user_id` / `conversation_id`，不依赖 Telegram `chat_id`。Telegram sender 与会话地址的解析在 `identity.py`。
- 渠道：核心只能调用 `channels.send_text()`；Telegram 细节只在 `telegram.py`。

## 文件

`main.py` app 生命周期；`models.py` 领域模型；`db.py` 兼容迁移；`identity.py` 渠道身份映射；`webhook.py` 入站；`jobs.py` 持久队列；`worker.py` 常驻园丁；`brain.py` AI/工具；`channels.py` 出站适配；`telegram.py` Telegram API。

## 约束

- 不要重新引入 Cron、内存任务队列或对 `chat_id` 的核心依赖。
- `AgentJob` 必须可重试且幂等；投递失败不能重复 AI 调用或重复写 assistant message。
- 每次 AI 调用都包含唤醒原因与当前时间。
- 未来自有 App 用标准 OIDC/JWT 认证，认证 subject 绑定为 `Identity`，不要自建密码系统。
