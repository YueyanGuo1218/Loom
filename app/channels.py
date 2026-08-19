"""渠道出站适配层。

园丁 worker 只向 Conversation 发消息，不直接依赖 Telegram。新增 App 渠道时，
在这里增加适配器即可。
"""

from . import models, telegram


def send_text(conversation: models.Conversation, text: str) -> None:
    """向指定会话发送纯文本。"""
    if conversation.channel == "telegram":
        telegram.send_message(int(conversation.external_chat_id), text)
        return
    raise ValueError(f"不支持的渠道: {conversation.channel}")
