"""Claude 大脑:Loom 的人设、工具定义、agent 循环。

这是整个项目的核心。每次「唤醒」(用户消息 or 定时器),都通过 run_agent()
执行一次:构造上下文 → 调 Claude(带工具)→ 执行工具 → 直到拿到最终回复。
"""

import logging
from datetime import datetime, timezone

import anthropic

from . import config, models
from .db import SessionLocal

logger = logging.getLogger(__name__)

MODEL = "claude-opus-5"
MAX_TOKENS = 8000
MAX_TOOL_ITERATIONS = 8

SYSTEM_PROMPT = """你是 Loom,一个会主动发起对话的 AI 助手。你的使命:帮助用户把碎片化的思考、偶然的灵感,逐步构建成完整的理论。

你的性格:
- 你是一个耐心、好奇、有思想的思考伙伴,不是冷冰冰的应答机器。
- 你会在合适的时机主动追问、提议继续讨论,帮助用户把一个想法想得更深。
- 语气自然、真诚,始终用中文交流;回复长度适中,不要啰嗦,也不要用一堆表情。

你每次会收到一条「唤醒消息」,里面包含:
1. [唤醒原因] —— 这次为什么被叫醒(可能是用户刚发来的消息,也可能是你之前设定的定时器到点了)
2. [当前时间] —— 用来理解「下周一」「半小时后」这类时间表达

你可以调用两个工具:
- set_timer(when, reason):设定一个未来的时间点,到点你会被唤醒并主动找用户。当用户要求提醒、或你想在某个时间继续跟进某个话题时使用。
- save_thought(content):把用户分享的灵感、想法、或重要信息保存下来,留作以后的素材。

行为准则:
- 如果用户要求提醒(比如「下周一提醒我处理银行的事」),务必调用 set_timer。
- 如果用户提出了一个有价值的想法或灵感,可以主动用 save_thought 记下来。
- 当用户表达的想法值得展开时,可以追问一两个好问题,但不要过度追问。
- 不要编造你「记得」的、但当前对话里没有的东西;你只能基于唤醒原因和对话历史来判断。
- 用户发 "/start" 或打招呼时,自然地介绍一下自己,说说你能帮什么忙。"""


TOOLS = [
    {
        "name": "set_timer",
        "description": (
            "设定一个未来的时间点,到点后你会被唤醒并主动找用户聊对应的话题。"
            "用于提醒、后续跟进、或约定在某个时间继续讨论。"
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "when": {
                    "type": "string",
                    "description": "触发时间,ISO 8601 格式(建议带时区),例如 2026-08-17T09:00:00+08:00",
                },
                "reason": {
                    "type": "string",
                    "description": "设定这个定时器的原因,也就是到点后要和用户聊什么",
                },
            },
            "required": ["when", "reason"],
        },
    },
    {
        "name": "save_thought",
        "description": "把用户分享的灵感、想法或重要信息保存下来,便于以后回顾。",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "要保存的想法/灵感内容"},
            },
            "required": ["content"],
        },
    },
]


def run_agent(user_id: str, conversation_id: str, wake_reason: str) -> str:
    """执行一次唤醒,返回要发给用户的回复文本。

    wake_reason 是一句人话,描述「这次为什么被唤醒」,会作为
    [唤醒原因] 注入给模型。
    """
    client = anthropic.Anthropic(
        api_key=config.settings.anthropic_api_key,
        base_url=config.settings.anthropic_base_url,
    )

    messages = _recent_history(conversation_id) + [
        {"role": "user", "content": _build_wake_message(wake_reason)}
    ]

    for _ in range(MAX_TOOL_ITERATIONS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=TOOLS,
        )

        # 模型想调用工具:执行工具,把结果喂回去继续。
        if response.stop_reason == "tool_use":
            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type == "tool_use":
                    result = _execute_tool(
                        block.name, block.input, user_id, conversation_id
                    )
                    tool_results.append(
                        {"type": "tool_result", "tool_use_id": block.id, "content": result}
                    )
            messages.append({"role": "user", "content": tool_results})
            continue

        # 正常结束(或 refusal / max_tokens)。
        text = "".join(b.text for b in response.content if b.type == "text").strip()
        if response.stop_reason == "refusal":
            return text or "抱歉,这条消息我暂时没法回应。"
        return text or "……"

    logger.warning("run_agent: 工具调用轮次用尽")
    return "……"


def _build_wake_message(wake_reason: str) -> str:
    now = datetime.now(config.settings.tzinfo).strftime("%Y-%m-%d %H:%M:%S %Z")
    return f"[唤醒原因] {wake_reason}\n[当前时间] {now}"


def _recent_history(conversation_id: str, limit: int = 30) -> list:
    """取最近 limit 条对话作为上下文,保证首条是 user(API 要求)。"""
    db = SessionLocal()
    try:
        rows = (
            db.query(models.Message)
            .filter(models.Message.conversation_id == conversation_id)
            .order_by(models.Message.id.desc())
            .limit(limit)
            .all()
        )
        messages = [{"role": r.role, "content": r.content} for r in reversed(rows)]
        while messages and messages[0]["role"] != "user":
            messages = messages[1:]
        return messages
    finally:
        db.close()


def _execute_tool(
    name: str, args: dict, user_id: str, conversation_id: str
) -> str:
    """执行模型调用的工具,返回给模型的工具结果文本。"""
    if name == "set_timer":
        fire_at = _parse_datetime(args.get("when"))
        reason = str(args.get("reason") or "").strip()
        if fire_at is None:
            return "错误:when 不是合法的 ISO 8601 时间,请改用形如 2026-08-17T09:00:00+08:00 的格式。"
        if not reason:
            return "错误:reason 不能为空。"
        db = SessionLocal()
        try:
            wakeup = models.ScheduledWakeup(
                user_id=user_id,
                conversation_id=conversation_id,
                fire_at=fire_at,
                reason=reason,
                status="pending",
            )
            db.add(wakeup)
            db.flush()
            db.add(
                models.AgentJob(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    kind="timer",
                    run_at=fire_at,
                    payload={
                        "wake_reason": f"定时器到点,当时的理由是:「{reason}」",
                        "scheduled_wakeup_id": wakeup.id,
                    },
                    status="pending",
                )
            )
            db.commit()
            return f"已设定定时器:{fire_at.isoformat()}(UTC)。到点后你会被唤醒,理由是「{reason}」。"
        finally:
            db.close()

    if name == "save_thought":
        content = str(args.get("content") or "").strip()
        if not content:
            return "错误:content 不能为空。"
        db = SessionLocal()
        try:
            thought = models.Thought(
                user_id=user_id, conversation_id=conversation_id, content=content
            )
            db.add(thought)
            db.commit()
            return "已保存这条想法。"
        finally:
            db.close()

    return f"未知工具:{name}"


def _parse_datetime(value):
    """把 ISO 字符串解析成 timezone-aware 的 UTC datetime;无法解析返回 None。"""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        # 模型没带时区时,按配置的时区理解。
        dt = dt.replace(tzinfo=config.settings.tzinfo)
    return dt.astimezone(timezone.utc)
