# Loom

Loom 是一个会主动发起对话的 AI Agent，帮助用户把碎片化思考、偶然的灵感逐步构建成理论。

它不只是等待提问：它会记录值得培育的想法、在合适的时机跟进，也会尊重不该被打扰的时刻。

## 当前架构

Loom 以 Telegram 作为当前唯一渠道，但核心不依赖 Telegram 身份或 Railway Cron。

```text
Telegram ──▶ /webhook ──▶ PostgreSQL(messages + agent_jobs) ──▶ 立即返回 200
                                      │
                                      ▼
                         常驻 Gardener Worker（同一 Python 进程）
                                      │
                                      ▼
                         AI / 记忆 / Telegram 渠道适配器
```

- **一个 Railway 服务、一个 Python 进程**：FastAPI 接 webhook；后台 Gardener Worker 在 lifespan 中启动。
- **数据库任务账本**：`agent_jobs` 是所有 AI 唤醒的唯一事实来源；重部署后会恢复未完成任务。
- **不使用 Cron**：worker 会等待下一项任务到期；大部分时间不调用 AI。
- **内部身份模型**：`users` / `identities` / `conversations` 把 Loom 用户、Telegram 身份与投递地址分开。未来 App 登录可绑定到同一位 Loom 用户。
- **可靠投递**：任务保存 AI 回复后再发送；发送失败会重试投递，不会重复调用 AI。

## 数据模型

| 表 | 用途 |
|---|---|
| `users` | Loom 内部用户身份，未来 App 登录也关联这里 |
| `identities` | 外部身份映射，例如 Telegram `from.id` |
| `conversations` | 某渠道上的投递会话，例如 Telegram `chat.id` |
| `messages` | 对话记录 |
| `thoughts` | 已保存的灵感 |
| `scheduled_wakeups` | 园丁设定的未来唤醒记录 |
| `agent_jobs` | 待执行、执行中、已完成或可重试的园丁任务 |
| `processed_updates` | Telegram `update_id` 去重 |

## 部署到 Railway

1. 新建 Railway 项目并关联本仓库。
2. 附加 PostgreSQL；Railway 会注入 `DATABASE_URL`。
3. 在 Web 服务的 Variables 配置下列变量。
4. 部署；启动命令已在 `Procfile`：`uvicorn app.main:app --host 0.0.0.0 --port $PORT`。
5. 让该服务保持常驻运行。Gardener Worker 与 Web 服务在同一实例，不需要另建 Railway 服务。
6. 删除旧的 Railway Cron Job；新版不再提供 `/internal/cron`。

首次部署新版时，应用会自动：

- 建立新的身份与任务表；
- 将旧版按 `chat_id` 保存的数据回填为 Loom 用户和 Telegram 会话；
- 将旧版尚未触发的定时器转为 `agent_jobs`；
- 若设置了 `WEBHOOK_URL`，重新设置 Telegram webhook。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | 是 | 从 @BotFather 获取 |
| `ANTHROPIC_API_KEY` | 是 | Claude API 或中转站的 key |
| `ANTHROPIC_BASE_URL` | 否 | Anthropic 协议中转站地址；官方直连留空 |
| `DATABASE_URL` | Railway 自动提供 | PostgreSQL 连接串 |
| `WEBHOOK_URL` | 推荐 | Railway 公网地址，用于自动设置 Telegram webhook |
| `WEBHOOK_SECRET` | 推荐 | Telegram webhook 鉴权 secret |
| `LOOM_TZ` | 否 | 时区，默认 `Asia/Shanghai` |

## 验证

1. `GET /health` 返回 `{"status":"ok"}`。
2. 向 Telegram bot 发送消息：webhook 应快速返回，随后收到 AI 回复。
3. 发送“30 秒后提醒我喝水”：worker 会在约 30 秒后直接处理对应任务，无需等待 Cron 周期。
4. Railway 日志应看到“后台 worker 已启动”；任务与消息会保留在 PostgreSQL。

## 下一步

- 灵感召回与对话摘要；
- 主动介入策略、安静时段与频率上限；
- 自有 App 的标准登录、JWT 校验与 Telegram 账户绑定；
- 多实例安全并发与管理界面。
