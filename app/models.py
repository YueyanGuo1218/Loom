"""Loom 的持久化领域模型。

核心层只认识 Loom 自己的 User / Conversation。Telegram 只是当前唯一的
渠道适配器，不能再用 Telegram chat_id 作为产品身份。
"""

import uuid

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


def new_id() -> str:
    return str(uuid.uuid4())


class User(Base):
    """Loom 的内部用户；未来 App 登录也落到这一层。"""

    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=new_id)
    timezone = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Identity(Base):
    """一个外部身份与一个 Loom 用户的绑定。"""

    __tablename__ = "identities"
    __table_args__ = (UniqueConstraint("provider", "external_id", name="uq_identity"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    provider = Column(String(32), nullable=False)  # telegram | app
    external_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Conversation(Base):
    """一个用户在某个渠道上的可投递会话。"""

    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("channel", "external_chat_id", name="uq_channel_conversation"),
    )

    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    channel = Column(String(32), nullable=False)  # telegram | app
    external_chat_id = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Message(Base):
    """完整对话日志,也是 AI 的上下文来源。"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    # chat_id 是早期 Telegram 数据的兼容列；新代码使用 user_id / conversation_id。
    chat_id = Column(BigInteger, index=True, nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    conversation_id = Column(
        String(36), ForeignKey("conversations.id"), index=True, nullable=True
    )
    role = Column(String(20))  # "user" | "assistant"
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Thought(Base):
    """AI 用 save_thought 工具记录下来的灵感/想法。"""

    __tablename__ = "thoughts"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    conversation_id = Column(
        String(36), ForeignKey("conversations.id"), index=True, nullable=True
    )
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScheduledWakeup(Base):
    """园丁设定的一次性未来唤醒；对应的 AgentJob 负责实际执行。"""

    __tablename__ = "scheduled_wakeups"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True, nullable=True)
    user_id = Column(String(36), ForeignKey("users.id"), index=True, nullable=True)
    conversation_id = Column(
        String(36), ForeignKey("conversations.id"), index=True, nullable=True
    )
    fire_at = Column(DateTime(timezone=True), index=True)
    reason = Column(Text)
    status = Column(String(20), default="pending")  # pending | fired | cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ProcessedUpdate(Base):
    """已处理过的 Telegram update_id,用于去重。

    Telegram 对未及时确认的请求会用同一个 update_id 重试;这里用主键唯一约束
    原子地去重 —— 谁先插入谁处理,重试请求撞主键直接跳过。
    """

    __tablename__ = "processed_updates"

    update_id = Column(BigInteger, primary_key=True)
    processed_at = Column(DateTime(timezone=True), server_default=func.now())


class AgentJob(Base):
    """持久化的园丁任务账本。

    webhook 只写入任务并立刻返回；常驻 worker 原子认领任务。lease_until
    让部署中断后的 running 任务可被重新接管。
    """

    __tablename__ = "agent_jobs"

    id = Column(String(36), primary_key=True, default=new_id)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    conversation_id = Column(
        String(36), ForeignKey("conversations.id"), nullable=False, index=True
    )
    kind = Column(String(32), nullable=False)  # user_message | timer | garden_review
    run_at = Column(DateTime(timezone=True), nullable=False, index=True)
    payload = Column(JSON, nullable=False, default=dict)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    lease_until = Column(DateTime(timezone=True), nullable=True, index=True)
    last_error = Column(Text, nullable=True)
    result_text = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    completed_at = Column(DateTime(timezone=True), nullable=True)
