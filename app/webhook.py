"""用户消息入口:Telegram 把消息 POST 到 /webhook。

流程:校验 secret → 按 update_id 去重 → 存用户消息和持久任务 → 立即返回 200。
AI 的实际处理和回复在 worker 里异步完成,不阻塞本请求(避免 Telegram 因等待超时而重试)。
"""

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Body, Header
from sqlalchemy.exc import IntegrityError

from . import config, identity, models, telegram, worker
from .db import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/webhook")
def webhook(
    payload: Any = Body(...),
    x_telegram_bot_api_secret_token: str = Header(default=None),
):
    # 1. 校验 secret(若配置了 WEBHOOK_SECRET)。
    if (
        config.settings.webhook_secret
        and x_telegram_bot_api_secret_token != config.settings.webhook_secret
    ):
        logger.warning("webhook: secret 不匹配,已忽略该请求")
        return {"ok": False}

    # 2. 解析文字消息;非文本消息(图片/贴纸等)v1 直接忽略。
    parsed = telegram.extract_message(payload)
    if parsed is None:
        return {"ok": True}
    resolved = identity.resolve_telegram(parsed.sender_id, parsed.chat_id)

    # 3. update 去重、存消息、创建任务必须同一事务提交。否则数据库短暂失败时
    # 可能出现“Telegram 认为已处理、但 Loom 实际没有收到任务”。
    update_id = payload.get("update_id")
    db = SessionLocal()
    try:
        if update_id is not None:
            db.add(models.ProcessedUpdate(update_id=update_id))
            db.flush()  # 唯一约束在 commit 前就能发现重复 update。
        db.add(
            models.Message(
                user_id=resolved.user_id,
                conversation_id=resolved.conversation_id,
                role="user",
                content=parsed.text,
            )
        )
        db.add(
            models.AgentJob(
                user_id=resolved.user_id,
                conversation_id=resolved.conversation_id,
                kind="user_message",
                run_at=datetime.now(timezone.utc),
                payload={"wake_reason": f"用户发来消息:「{parsed.text}」"},
                status="pending",
            )
        )
        db.commit()
    except IntegrityError:
        db.rollback()
        if update_id is not None and db.get(models.ProcessedUpdate, update_id) is not None:
            logger.info("webhook: update_id %s 已处理过,跳过", update_id)
            return {"ok": True}
        raise
    finally:
        db.close()

    # 4. 数据已经可靠落库；通知本实例 worker 即可立即处理。
    worker.notify_new_job()
    return {"ok": True}
