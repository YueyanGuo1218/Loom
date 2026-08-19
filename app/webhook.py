"""用户消息入口:Telegram 把消息 POST 到 /webhook。

流程:校验 secret → 按 update_id 去重 → 存用户消息 → 丢进后台队列 → 立即返回 200。
AI 的实际处理和回复在 worker 里异步完成,不阻塞本请求(避免 Telegram 因等待超时而重试)。
"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Header
from sqlalchemy.exc import IntegrityError

from . import config, models, telegram, worker
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

    # 2. 按 update_id 去重。Telegram 会重试同一 update_id,靠主键唯一约束原子去重。
    update_id = payload.get("update_id")
    if update_id is not None:
        db = SessionLocal()
        try:
            db.add(models.ProcessedUpdate(update_id=update_id))
            db.commit()
        except IntegrityError:
            db.rollback()
            logger.info("webhook: update_id %s 已处理过,跳过", update_id)
            return {"ok": True}
        finally:
            db.close()

    # 3. 解析文字消息;非文本消息(图片/贴纸等)v1 直接忽略。
    parsed = telegram.extract_message(payload)
    if parsed is None:
        return {"ok": True}
    chat_id, text = parsed

    # 4. 存用户消息。
    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="user", content=text))
        db.commit()
    finally:
        db.close()

    # 5. 丢进后台队列,立即返回;AI 处理在 worker 里异步进行。
    worker.enqueue(chat_id, f"用户发来消息:「{text}」")
    return {"ok": True}
