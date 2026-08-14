# Loom

会主动发起对话的 Telegram AI 助手,帮助用户把碎片化思考、偶然的灵感逐步构建成理论。

## 技术栈

- Python 3.9+(Railway 上用 3.11+)
- FastAPI + Uvicorn(承载 Telegram webhook)
- PostgreSQL(Railway 托管)/ SQLite(本地兜底),SQLAlchemy ORM
- Claude API(`claude-opus-5`)
- Railway Cron(每分钟触发 `/internal/cron` 做定时唤醒)

## 架构(数据流)

- **用户消息**:Telegram → `POST /webhook` → 存 `messages` → `brain.run_agent` → 回复
- **定时唤醒**:Railway Cron → `POST /internal/cron`(带 `CRON_SECRET`)→ 找到期定时器 → `brain.run_agent` → 主动发消息

## 核心概念

- **唤醒上下文(wake reason)**:每次调 AI 都告诉它「为什么被叫醒」,通过用户消息里的 `[唤醒原因]` 注入。这是本项目的灵魂 —— 用户消息唤醒和定时器唤醒走同一套 `run_agent`,只是 `wake_reason` 不同。
- **工具(tool use)**:`set_timer`(设定时器)/ `save_thought`(存灵感)。手动 tool-use 循环在 `brain.py` 里,不使用 SDK 的 tool runner,便于控制 DB 副作用。

## 文件结构

| 文件 | 职责 |
|------|------|
| `app/main.py` | FastAPI 入口 + lifespan(建表、设 webhook) |
| `app/config.py` | 环境变量(pydantic-settings) |
| `app/db.py` | SQLAlchemy 引擎 + Session 工厂(处理 `postgres://` → `postgresql://`) |
| `app/models.py` | 三张表:`messages` / `thoughts` / `scheduled_wakeups` |
| `app/telegram.py` | `send_message` / `set_webhook` / `extract_message` |
| `app/brain.py` | Claude 大脑:系统提示词 + 工具 + agent 循环 |
| `app/webhook.py` | `POST /webhook`(用户消息入口) |
| `app/cron.py` | `POST /internal/cron`(定时唤醒入口)+ `fire_due_timers()` |
| `app/tick.py` | 备用 Cron 入口(`python -m app.tick`,curl 不可用时用) |

## 环境变量

见 `.env.example`:`TELEGRAM_BOT_TOKEN` / `ANTHROPIC_API_KEY` / `DATABASE_URL` / `WEBHOOK_URL` / `WEBHOOK_SECRET` / `CRON_SECRET` / `LOOM_TZ`。

## 当前进度(v1)

- ✅ 最小闭环(收到消息 → AI 回复 → 存库)
- ✅ 定时唤醒基座(AI 可设定时器、知道唤醒原因、Railway Cron 触发)
- ⏳ 待做(按优先级):多用户支持、灵感召回(thoughts 目前只存不回看)、行为建模/个性化

## 注意事项

- `fire_at` 统一存 UTC(timezone-aware),比较时也用 UTC。
- 定时器触发是先标 `fired` 再发消息,避免 Cron 重叠导致重复触发;触发失败会打日志但不重试。
- Claude API 用 `claude-opus-5`(adaptive thinking 默认开启),代码只取 text 块;已处理 `refusal` 停因。
