"""后台 agent worker:串行处理所有「唤醒」,让 webhook / cron 能秒回。

webhook 和 cron 只负责把 (chat_id, wake_reason) 丢进队列就立刻返回;
真正跑 AI、存回复、发消息都在这里由单一线程串行完成,保证回复有序、
不会因为并行而读到互相覆盖的旧上下文。
"""

import logging
import queue
import threading

from . import brain, models, telegram
from .db import SessionLocal

logger = logging.getLogger(__name__)

_queue: "queue.Queue[tuple[int, str]]" = queue.Queue()


def enqueue(chat_id: int, wake_reason: str) -> None:
    """把一次唤醒丢进后台队列,立即返回。"""
    _queue.put((chat_id, wake_reason))


def start() -> None:
    """启动单一后台 worker 线程(在 app lifespan 里调用)。"""
    t = threading.Thread(target=_worker, daemon=True, name="agent-worker")
    t.start()


def _worker() -> None:
    while True:
        chat_id, wake_reason = _queue.get()
        try:
            _process(chat_id, wake_reason)
        except Exception:
            logger.exception("agent worker: 处理失败")
        finally:
            _queue.task_done()


def _process(chat_id: int, wake_reason: str) -> None:
    try:
        reply = brain.run_agent(chat_id, wake_reason)
    except Exception:
        logger.exception("brain.run_agent 失败")
        reply = "我这边出了点问题,稍后再试。"

    db = SessionLocal()
    try:
        db.add(models.Message(chat_id=chat_id, role="assistant", content=reply))
        db.commit()
    finally:
        db.close()

    try:
        telegram.send_message(chat_id, reply)
    except Exception:
        logger.exception("send_message 失败")
