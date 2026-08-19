"""渠道身份到 Loom 内部 User / Conversation 的解析。

这里是 Telegram 与核心领域的边界。未来 App 的 JWT 验证成功后，也只需调用
同一层来取得或绑定 Loom 用户，而无需改动记忆、园丁任务或 AI 逻辑。
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError

from . import models
from .db import SessionLocal


@dataclass(frozen=True)
class ResolvedConversation:
    user_id: str
    conversation_id: str


def resolve_telegram(sender_id: str, chat_id: str) -> ResolvedConversation:
    """取得 Telegram 发送者对应的 Loom 用户和当前会话。

    现阶段一个 Telegram identity 会自动创建一个 Loom 用户。未来 App 的账户
    绑定流程只需要把另一条 identity 连到同一个 user_id。
    """
    db = SessionLocal()
    try:
        identity = (
            db.query(models.Identity)
            .filter(
                models.Identity.provider == "telegram",
                models.Identity.external_id == sender_id,
            )
            .one_or_none()
        )
        if identity is None:
            user = models.User(id=str(uuid.uuid4()))
            db.add(user)
            db.flush()
            identity = models.Identity(
                user_id=user.id, provider="telegram", external_id=sender_id
            )
            db.add(identity)
            db.flush()

        conversation = (
            db.query(models.Conversation)
            .filter(
                models.Conversation.channel == "telegram",
                models.Conversation.external_chat_id == chat_id,
            )
            .one_or_none()
        )
        if conversation is None:
            conversation = models.Conversation(
                id=str(uuid.uuid4()),
                user_id=identity.user_id,
                channel="telegram",
                external_chat_id=chat_id,
            )
            db.add(conversation)
            db.flush()
        elif conversation.user_id != identity.user_id:
            # 群聊不是 v1 的产品场景；绝不把群会话错误归到某个发送者。
            raise ValueError("该 Telegram 会话已绑定到另一位 Loom 用户")

        db.commit()
        return ResolvedConversation(
            user_id=identity.user_id, conversation_id=conversation.id
        )
    except IntegrityError:
        # 极少数并发首次消息可能同时建 identity；回滚后重试一次读取。
        db.rollback()
        identity = (
            db.query(models.Identity)
            .filter(
                models.Identity.provider == "telegram",
                models.Identity.external_id == sender_id,
            )
            .one()
        )
        conversation = (
            db.query(models.Conversation)
            .filter(
                models.Conversation.channel == "telegram",
                models.Conversation.external_chat_id == chat_id,
            )
            .one()
        )
        return ResolvedConversation(
            user_id=identity.user_id, conversation_id=conversation.id
        )
    finally:
        db.close()
