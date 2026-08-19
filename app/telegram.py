"""Telegram 渠道适配器:发消息、设 webhook、解析 update。

直接用 requests 调 Telegram Bot API,不引入重型框架,保持透明。
"""

from dataclasses import dataclass
from typing import Optional

import requests

from . import config

API_BASE = f"https://api.telegram.org/bot{config.settings.telegram_bot_token}"


def send_message(chat_id: int, text: str) -> dict:
    resp = requests.post(
        f"{API_BASE}/sendMessage",
        json={"chat_id": chat_id, "text": text},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def set_webhook() -> dict:
    """把 Telegram 的 webhook 指向我们的 /webhook(启动时若配了 WEBHOOK_URL 才调用)。"""
    url = f"{config.settings.webhook_url.rstrip('/')}/webhook"
    payload = {"url": url}
    if config.settings.webhook_secret:
        payload["secret_token"] = config.settings.webhook_secret
    resp = requests.post(f"{API_BASE}/setWebhook", json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


@dataclass(frozen=True)
class TelegramMessage:
    """Telegram 入站消息的渠道信息。

    sender_id 是用户身份；chat_id 是投递回复的会话地址。两者在私聊中常常
    相同，但概念上必须分开，才能支持群聊和未来自有 App。
    """

    sender_id: str
    chat_id: str
    text: str


def extract_message(update: dict) -> Optional[TelegramMessage]:
    """提取 Telegram 文字消息；非文字或缺少发送者时返回 None。"""
    message = update.get("message")
    if not message:
        return None

    text = message.get("text")
    chat = message.get("chat") or {}
    sender = message.get("from") or {}
    chat_id = chat.get("id")
    sender_id = sender.get("id")

    if chat_id is None or sender_id is None or text is None:
        return None

    text = text.strip()
    if not text:
        return None
    return TelegramMessage(sender_id=str(sender_id), chat_id=str(chat_id), text=text)
