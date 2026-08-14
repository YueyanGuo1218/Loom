"""用户消息入口:Telegram 把消息 POST 到 /webhook。"""

import logging
from typing import Any

from fastapi import APIRouter, Body, Header

from . import brain, config, models, telegram
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
    chat_id, text = parsed

    # 3. 存用户消息。
    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="user", content=text))
        db.commit()
    finally:
        db.close()

    # 4. 调大脑。
    try:
        reply = brain.run_agent(chat_id, f"用户发来消息:「{text}」")
    except Exception:
        logger.exception("webhook: brain.run_agent 失败")
        reply = "我这边出了点问题,稍后再试。"

    # 5. 存回复 + 发回用户。
    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="assistant", content=reply))
        db.commit()
    finally:
        db.close()

    try:
        telegram.send_message(chat_id, reply)
    except Exception:
        logger.exception("webhook: send_message 失败")

    return {"ok": True}
