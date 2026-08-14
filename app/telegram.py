"""Telegram 客户端:发消息、设 webhook、解析 update。

直接用 requests 调 Telegram Bot API,不引入重型框架,保持透明。
"""

from typing import Optional, Tuple

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


def extract_message(update: dict) -> Optional[Tuple[int, str]]:
    """从 Telegram update 里提取 (chat_id, text)。非文本消息(图片/贴纸等)返回 None。"""
    message = update.get("message")
    if not message:
        return None

    text = message.get("text")
    chat = message.get("chat") or {}
    chat_id = chat.get("id")

    if chat_id is None or text is None:
        return None

    text = text.strip()
    if not text:
        return None
    return chat_id, text
