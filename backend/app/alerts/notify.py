"""Telegram notifications. Free: create a bot with @BotFather, put
TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env. To find your chat id,
message your bot once, then open
https://api.telegram.org/bot<TOKEN>/getUpdates in a browser."""

import requests

from app.core import envutil


def configured():
    return bool(envutil.get("TELEGRAM_BOT_TOKEN")
                and envutil.get("TELEGRAM_CHAT_ID"))


def bot_configured():
    """A bot token alone is enough for per-user delivery."""
    return bool(envutil.get("TELEGRAM_BOT_TOKEN"))


def send_to_user(username, text):
    """Deliver to the user's linked chat; falls back to the legacy chat id
    only for the admin (the single-user install case)."""
    from app.core import accounts
    link = accounts.telegram_chat_for(username)
    if link:
        return send(text, chat_id=link["chat_id"])
    if accounts.is_admin(username) and configured():
        return send(text)
    return False, "no Telegram linked for this user"


def send(text, chat_id=None):
    """Send a message. Returns (ok, error|None). Never raises.
    chat_id: a user's linked chat; default is the legacy TELEGRAM_CHAT_ID."""
    token = envutil.get("TELEGRAM_BOT_TOKEN")
    chat = chat_id or envutil.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        return False, "Telegram not configured (.env missing token/chat id)."
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text}, timeout=15,
        )
        if r.status_code == 200:
            return True, None
        return False, f"Telegram error {r.status_code}: {r.text[:120]}"
    except Exception as e:
        return False, str(e)