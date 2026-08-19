"""常驻园丁 worker。

FastAPI 与 worker 仍在同一个 Railway 实例、同一个 Python 进程内；区别在于任务
不再放内存队列，而是保存在 PostgreSQL。进程重启后 worker 会自动接手未完成任务。
"""

import logging
import threading
from typing import Optional

from . import brain, channels, jobs, models
from .db import SessionLocal

logger = logging.getLogger(__name__)

_wake_event = threading.Event()
_stop_event = threading.Event()
_thread: Optional[threading.Thread] = None


def notify_new_job() -> None:
    """通知本进程的 worker 提前检查数据库；任务本身已可靠地在数据库内。"""
    _wake_event.set()


def start() -> None:
    """启动单一常驻 worker 线程(在 app lifespan 里调用)。"""
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stop_event.clear()
    _thread = threading.Thread(target=_worker, daemon=True, name="gardener-worker")
    _thread.start()


def stop() -> None:
    """请求 worker 尽快结束；Railway 进程退出时任务仍会留在数据库。"""
    _stop_event.set()
    _wake_event.set()


def _worker() -> None:
    while not _stop_event.is_set():
        job = jobs.claim_due_job()
        if job is None:
            _wake_event.wait(timeout=jobs.seconds_until_next_job())
            _wake_event.clear()
            continue
        try:
            _process(job)
            jobs.complete_job(job.id)
        except Exception as exc:
            logger.exception("gardener worker: 处理任务 %s 失败", job.id)
            jobs.retry_job(job.id, str(exc))


def _process(job: models.AgentJob) -> None:
    wake_reason = str(job.payload.get("wake_reason") or "园丁任务到期")
    reply = jobs.stored_result(job.id)
    if reply is None:
        generated_reply = brain.run_agent(job.user_id, job.conversation_id, wake_reason)
        reply = jobs.store_result_and_message(job, generated_reply)

    db = SessionLocal()
    try:
        conversation = db.get(models.Conversation, job.conversation_id)
        if conversation is None:
            raise ValueError(f"任务 {job.id} 的会话不存在")
        db.refresh(conversation)
        db.expunge(conversation)
    finally:
        db.close()

    channels.send_text(conversation, reply)
