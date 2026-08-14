# Loom

Loom 是一个会**主动发起对话**的 AI Agent,主要目的是帮助用户通过碎片化的思考构建理论。

它不只是等你问 —— 它会在合适的时机主动找你聊、提醒你、跟进你之前提过的想法。

## 愿景

Loom 希望实现如下功能:

- 吸引用户将注意力适当分配给思考和理论产出
- 记录用户偶然产生的灵感,在合适的时候主动发起与用户的进一步讨论
- 能够通过用户的反馈调整自身行为,例如:
  - 「我本月底有一个重要的考试,近期多让我思考一下关于考试的内容」
  - 「下周一发消息给我,提醒我处理银行相关事宜」
- 对用户的行为模式进行记录和建模

## 技术栈

- **部署**:Railway
- **语言/框架**:Python + FastAPI + Uvicorn
- **前端**:Telegram(以聊天机器人形式运作,通过 webhook)
- **数据库**:PostgreSQL(Railway 托管);本地开发可用 SQLite 兜底
- **AI**:Claude API(`claude-opus-5`)
- **定时唤醒**:Railway Cron

## 当前进度(v1)

- ✅ 最小闭环:Telegram 收到消息 → AI 回复 → 存入数据库
- ✅ 主动对话基座:AI 可自己设定时器;能被定时器唤醒;每次都知道「本次唤醒原因」
- ⏳ 待做:多用户支持、灵感召回、行为建模/个性化

## 工作原理

```
用户发消息 ──▶ Telegram ──▶ POST /webhook ──▶ 存库 ──▶ Claude 大脑 ──▶ 回复
                                                        ▲
Railway Cron(每分钟)──▶ POST /internal/cron ──▶ 找到期定时器 ──┘
```

- **唤醒上下文**:每次调 AI 都会告诉它「这次为什么被叫醒」(用户消息 or 定时器到点),以及当前时间。
- **AI 的两个工具**:`set_timer`(设定时器)、`save_thought`(记录灵感)。

## 部署到 Railway

### 1. 准备两个密钥

- **Telegram Bot Token**:在 Telegram 里找 `@BotFather` → 发 `/newbot` → 按提示创建 → 得到 token。
- **Anthropic API Key**:到 <https://console.anthropic.com> 申请。

### 2. 在 Railway 上部署

1. 新建一个 Railway 项目,关联本 GitHub 仓库。
2. 给项目**附加一个 PostgreSQL 服务**(Railway 会自动注入 `DATABASE_URL`)。
3. 在服务的 **Variables** 面板里配置环境变量(见下方表格)。
4. 部署。启动命令已在 `Procfile` 里:`uvicorn app.main:app --host 0.0.0.0 --port $PORT`。
5. 部署完成后,访问 `https://<你的域名>/health`,应返回 `{"status":"ok"}`。

### 3. 配置 Telegram webhook

- 把 `WEBHOOK_URL` 设为 Railway 分配给你的公网地址(形如 `https://xxx.up.railway.app`)。服务启动时会自动 `setWebhook`,把 Telegram 指过来。
- 或者手动设置一次(把 token 和域名替换掉):

  ```bash
  curl "https://api.telegram.org/bot<TOKEN>/setWebhook?url=https://<你的域名>/webhook"
  ```

### 4. 配置 Railway Cron(定时唤醒)

新建一个 **Cron Job**:

- 时间表达式:`* * * * *`(每分钟)
- 命令:

  ```bash
  curl -fsS -X POST "https://<你的域名>/internal/cron" -H "X-Cron-Secret: <你的 CRON_SECRET>"
  ```

- 该 Cron Job 的环境变量里配好 `CRON_SECRET`。

> 如果 Cron 容器里没有 `curl`,把命令换成 `python -m app.tick` 即可(已提供备用入口)。

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `TELEGRAM_BOT_TOKEN` | ✅ | 从 @BotFather 获取 |
| `ANTHROPIC_API_KEY` | ✅ | 从 console.anthropic.com 获取 |
| `ANTHROPIC_BASE_URL` | 可选 | 用中转站时填中转站地址;直连留空 |
| `DATABASE_URL` | 本地可空 | Railway 附加 Postgres 后自动注入;本地默认 SQLite |
| `WEBHOOK_URL` | 可选 | 公网地址,用于自动 setWebhook |
| `WEBHOOK_SECRET` | 可选 | Telegram webhook 鉴权(推荐) |
| `CRON_SECRET` | 可选 | 保护 `/internal/cron`(推荐) |
| `LOOM_TZ` | 可选 | 时区,默认 `Asia/Shanghai` |

## 本地开发(可选)

虽然目标是部署到 Railway,但想本地调试也可以:

```bash
# 建议用 Python 3.11+
pip install -r requirements.txt
cp .env.example .env   # 填入 TELEGRAM_BOT_TOKEN 和 ANTHROPIC_API_KEY
uvicorn app.main:app --reload
```

本地没有公网地址时,Telegram 收不到 webhook,可先只测 `/internal/cron` 和数据库。

## 验证

1. `GET /health` 返回 `{"status":"ok"}`。
2. 在 Telegram 给 bot 发消息 → 收到回复;数据库 `messages` 表有记录。
3. 说「30 秒后提醒我喝水」→ 约 30 秒后(下个 Cron 周期)主动收到提醒;`scheduled_wakeups` 状态变 `fired`。
4. 说一句灵感 → 确认 `thoughts` 表有记录。

## 已知限制

- Cron 粒度 1 分钟,提醒最多晚约 1 分钟(对提醒/讨论场景够用)。
- Railway 免费档实例可能休眠;Cron 按点触发会唤醒它,但可能有冷启动延迟,想要更及时可开启 always-on。
- 服务停机期间到期的定时器,恢复后会由 Cron 补触发(晚到总比不到好)。
- 灵感目前「只存不回看」,跨会话召回和个性化在后续里程碑。
