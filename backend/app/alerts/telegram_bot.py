"""
Telegram linking: one bot (yours, from BotFather) serves every user.

Flow:
  1. A signed-in user asks the app for a link code (Settings -> Connect
     Telegram). The app returns https://t.me/<bot>?start=<code>.
  2. Telegram delivers "/start <code>" to the bot. This poller sees it,
     redeems the code, stores the chat id against the user, and replies.
  3. Alerts and digests for that user go to that chat id.
  "/stop" in the chat unlinks. Codes expire after 30 minutes.

Uses getUpdates long-polling, so it needs no public URL and works behind
NAT (phone hosting). Only one process may poll a given bot token.

.env: TELEGRAM_BOT_TOKEN=123456:ABC...  (TELEGRAM_CHAT_ID stays as the
      legacy fallback for a single-user install.)
"""
import threading
import time

import requests

from app.core import accounts, envutil

_bot_username = None
_started = False


def _token():
    return envutil.get("TELEGRAM_BOT_TOKEN")


def _api(method, **params):
    r = requests.post(f"https://api.telegram.org/bot{_token()}/{method}",
                      json=params, timeout=35)
    data = r.json() if r.content else {}
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method}: {data.get('description')}")
    return data["result"]


def bot_username():
    global _bot_username
    if not _token():
        return None
    if _bot_username is None:
        try:
            _bot_username = _api("getMe").get("username") or ""
        except Exception:
            _bot_username = ""
    return _bot_username or None


def send_to(chat_id, text):
    """Returns (ok, error|None). Never raises."""
    try:
        _api("sendMessage", chat_id=str(chat_id), text=text)
        return True, None
    except Exception as e:
        return False, str(e)


def _handle(update):
    msg = update.get("message") or update.get("edited_message") or {}
    text = (msg.get("text") or "").strip()
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    if not chat_id or not text:
        return
    tg_user = (msg.get("from") or {}).get("username")
    if text.startswith("/start"):
        parts = text.split(maxsplit=1)
        code = parts[1].strip() if len(parts) > 1 else ""
        user = accounts.telegram_redeem(code, chat_id, tg_user) if code else None
        if user:
            send_to(chat_id, f"Linked to account '{user}'. Your alerts and "
                             f"the weekly digest will arrive here. Send "
                             f"/stop to disconnect.")
        else:
            send_to(chat_id, "To connect, open the app's Settings page, "
                             "press Connect Telegram, and use the button "
                             "it shows. Codes expire after 30 minutes.")
    elif text.startswith("/stop"):
        accounts.telegram_unlink(chat_id=chat_id)
        send_to(chat_id, "Disconnected. Nothing more will be sent here.")
    else:
        send_to(chat_id, "This bot only delivers alerts. Ask the analyst "
                         "inside the app.")


def _poll_loop():
    offset = None
    while True:
        try:
            updates = _api("getUpdates", timeout=30, offset=offset,
                           allowed_updates=["message"])
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    _handle(u)
                except Exception:
                    pass
        except Exception:
            time.sleep(15)              # network blip or 409 (double poller)


def start():
    """Start the poller once per process, if a token exists."""
    global _started
    if _started or not _token():
        return
    _started = True
    threading.Thread(target=_poll_loop, daemon=True,
                     name="telegram-poll").start()
