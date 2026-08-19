"""AgentJob 的创建与认领。

PostgreSQL 是任务的唯一事实来源：webhook 写入任务后即可返回，worker 重启后也
会恢复 pending 或租约过期的任务。当前部署只有一个 worker；认领逻辑仍保留 lease，
为未来安全扩容打下基础。
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func

from . import models
from .db import SessionLocal

LEASE_SECONDS = 300


def create_job(
    user_id: str,
    conversation_id: str,
    kind: str,
    payload: Dict[str, Any],
    run_at: Optional[datetime] = None,
) -> models.AgentJob:
    """创建一项待执行的园丁任务，并返回已持久化对象。"""
    job = models.AgentJob(
        user_id=user_id,
        conversation_id=conversation_id,
        kind=kind,
        payload=payload,
        run_at=run_at or datetime.now(timezone.utc),
        status="pending",
    )
    db = SessionLocal()
    try:
        db.add(job)
        db.commit()
        db.refresh(job)
        return job
    finally:
        db.close()


def claim_due_job() -> Optional[models.AgentJob]:
    """原子地认领一项到期任务；没有任务时返回 None。"""
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        # 上一个进程中断时留下的 running 任务，租约到期后可安全重试。
        (
            db.query(models.AgentJob)
            .filter(
                models.AgentJob.status == "running",
                models.AgentJob.lease_until.is_not(None),
                models.AgentJob.lease_until < now,
            )
            .update(
                {
                    models.AgentJob.status: "pending",
                    models.AgentJob.lease_until: None,
                },
                synchronize_session=False,
            )
        )

        query = (
            db.query(models.AgentJob)
            .filter(
                models.AgentJob.status == "pending",
                models.AgentJob.run_at <= now,
            )
            .order_by(models.AgentJob.run_at.asc(), models.AgentJob.created_at.asc())
        )
        if db.bind.dialect.name == "postgresql":
            query = query.with_for_update(skip_locked=True)

        job = query.first()
        if job is None:
            db.commit()
            return None

        job.status = "running"
        job.attempts += 1
        job.lease_until = now + timedelta(seconds=LEASE_SECONDS)
        db.commit()
        db.refresh(job)
        db.expunge(job)
        return job
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def complete_job(job_id: str) -> None:
    db = SessionLocal()
    try:
        job = db.get(models.AgentJob, job_id)
        if job is not None:
            job.status = "completed"
            job.completed_at = datetime.now(timezone.utc)
            job.lease_until = None
            wakeup_id = (job.payload or {}).get("scheduled_wakeup_id")
            if wakeup_id is not None:
                wakeup = db.get(models.ScheduledWakeup, wakeup_id)
                if wakeup is not None:
                    wakeup.status = "fired"
            db.commit()
    finally:
        db.close()


def retry_job(job_id: str, error: str) -> None:
    """失败任务延迟重试，避免瞬时网络故障直接丢掉用户消息。"""
    db = SessionLocal()
    try:
        job = db.get(models.AgentJob, job_id)
        if job is not None:
            delay = min(60 * max(job.attempts, 1), 15 * 60)
            job.status = "pending"
            job.run_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
            job.lease_until = None
            job.last_error = error[:2000]
            db.commit()
    finally:
        db.close()


def stored_result(job_id: str) -> Optional[str]:
    """返回已生成但可能尚未投递成功的回复。"""
    db = SessionLocal()
    try:
        job = db.get(models.AgentJob, job_id)
        return job.result_text if job is not None else None
    finally:
        db.close()


def store_result_and_message(job: models.AgentJob, reply: str) -> str:
    """原子保存 AI 回复与对话记录，防止投递重试时重复调用 AI。"""
    db = SessionLocal()
    try:
        persisted_job = db.get(models.AgentJob, job.id)
        if persisted_job is None:
            raise ValueError(f"找不到任务: {job.id}")
        if persisted_job.result_text is not None:
            return persisted_job.result_text
        persisted_job.result_text = reply
        db.add(
            models.Message(
                user_id=job.user_id,
                conversation_id=job.conversation_id,
                role="assistant",
                content=reply,
            )
        )
        db.commit()
        return reply
    finally:
        db.close()


def seconds_until_next_job(default: float = 30.0) -> float:
    """返回到下一项 pending 任务的等待秒数；从不忙等。"""
    db = SessionLocal()
    try:
        next_run_at = (
            db.query(func.min(models.AgentJob.run_at))
            .filter(models.AgentJob.status == "pending")
            .scalar()
        )
        if next_run_at is None:
            return default
        if next_run_at.tzinfo is None:
            next_run_at = next_run_at.replace(tzinfo=timezone.utc)
        return max(0.0, min((next_run_at - datetime.now(timezone.utc)).total_seconds(), default))
    finally:
        db.close()
