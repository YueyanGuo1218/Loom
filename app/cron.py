"""定时唤醒入口:Railway Cron 每分钟调一次 /internal/cron。

DB 是定时器的唯一事实源;Cron 只负责按点敲门,由这里检查并触发到期任务。
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Header
from sqlalchemy import and_

from . import brain, config, models, telegram
from .db import SessionLocal

logger = logging.getLogger(__name__)

router = APIRouter()


def fire_due_timers() -> int:
    """把到期的定时器全部触发,返回触发个数。"""
    db = SessionLocal()
    fired = 0
    try:
        now = datetime.now(timezone.utc)
        due = (
            db.query(models.ScheduledWakeup)
            .filter(
                and_(
                    models.ScheduledWakeup.status == "pending",
                    models.ScheduledWakeup.fire_at <= now,
                )
            )
            .all()
        )
        for w in due:
            # 先标记 fired,避免下次 Cron 重复触发。
            w.status = "fired"
            db.commit()

            try:
                reply = brain.run_agent(
                    w.chat_id, f"定时器到点,当时的理由是:「{w.reason}」"
                )
                db.add(models.Message(chat_id=w.chat_id, role="assistant", content=reply))
                db.commit()
                telegram.send_message(w.chat_id, reply)
                fired += 1
            except Exception:
                logger.exception("cron: 触发定时器 %s 失败", w.id)

        return fired
    finally:
        db.close()


@router.post("/internal/cron")
def internal_cron(x_cron_secret: str = Header(default=None)):
    if config.settings.cron_secret and x_cron_secret != config.settings.cron_secret:
        logger.warning("cron: secret 不匹配,已拒绝")
        return {"ok": False}

    fired = fire_due_timers()
    return {"ok": True, "fired": fired}
