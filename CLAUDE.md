# Loom

会主动发起对话的 AI 助手，帮助用户把碎片化思考逐步构建成理论。

## 运行模型

一个 Railway 服务、一个 FastAPI 进程：Webhook 快速确认 Telegram 请求；同一进程内的常驻 Gardener Worker 从 PostgreSQL 认领任务并在必要时调用 AI。**不使用 Railway Cron。**

```text
Telegram → POST /webhook → messages + agent_jobs → 200 OK
                                      ↓
                     Gardener Worker → brain → channels → Telegram
```

- `agent_jobs` 是任务唯一事实来源，绝不把关键任务只放内存。
- `running` job 使用 lease；进程中断后会自动重新成为可认领任务。
- worker 单线程串行处理，保证当前单实例下回复与上下文有序。
- AI 只在用户消息、明确到点任务或未来的低频园丁复盘发生时调用。

## 身份和渠道边界

- `User` 是 Loom 内部身份。
- `Identity` 把外部身份连到 User；当前为 `telegram` + Telegram `from.id`。
- `Conversation` 是渠道投递地址；当前为 `telegram` + Telegram `chat.id`。
- 核心逻辑必须使用 `user_id` / `conversation_id`，不得新增 `chat_id` 依赖。
- 所有渠道发送必须经 `app/channels.py`，不得从 worker 或 brain 直接调用 Telegram API。
- 未来 App 认证只需把经验证的认证 subject 绑定为另一条 Identity；不要自行实现密码认证。

## 文件职责

| 文件 | 职责 |
|---|---|
| `app/main.py` | FastAPI 入口、数据库初始化、worker 生命周期 |
| `app/models.py` | User / Identity / Conversation / Message / Thought / ScheduledWakeup / AgentJob |
| `app/db.py` | 引擎、session、旧版数据库兼容迁移 |
| `app/identity.py` | Telegram 入站身份到内部用户/会话的解析 |
| `app/telegram.py` | Telegram API 和 update 解析 |
| `app/channels.py` | 通用出站渠道适配层 |
| `app/webhook.py` | Telegram 去重、入库、创建 AgentJob、秒回 200 |
| `app/jobs.py` | 持久任务创建、认领、租约恢复、重试 |
| `app/worker.py` | 常驻单线程 Gardener Worker |
| `app/brain.py` | 模型调用、工具循环、记忆写入、设定定时任务 |

## 不变量

- `fire_at` 和 `AgentJob.run_at` 均是 UTC timezone-aware 时间。
- AI 生成成功后，回复文本与 assistant Message 必须原子保存；投递重试不得再次调用 AI。
- Telegram webhook 按 `update_id` 去重，重复请求直接返回 200。
- 新功能不应要求新增 Railway 服务或 Cron。
