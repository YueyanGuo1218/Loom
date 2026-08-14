"""SQLAlchemy ORM 模型:三张表。"""

from sqlalchemy import BigInteger, Column, DateTime, Integer, String, Text, func
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Message(Base):
    """完整对话日志,也是 AI 的上下文来源。"""

    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    role = Column(String(20))  # "user" | "assistant"
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Thought(Base):
    """AI 用 save_thought 工具记录下来的灵感/想法。"""

    __tablename__ = "thoughts"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ScheduledWakeup(Base):
    """定时器:AI 设定后,由 Railway Cron 每分钟检查并触发。reason 即「唤醒原因」。"""

    __tablename__ = "scheduled_wakeups"

    id = Column(Integer, primary_key=True)
    chat_id = Column(BigInteger, index=True)
    fire_at = Column(DateTime(timezone=True), index=True)
    reason = Column(Text)
    status = Column(String(20), default="pending")  # pending | fired | cancelled
    created_at = Column(DateTime(timezone=True), server_default=func.now())
