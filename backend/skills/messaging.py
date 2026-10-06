"""Messaging skill: send Telegram messages through the Bot API.

The user's own chat (TELEGRAM_CHAT_ID) is the only "self" destination. In
DEMO_MODE, messages to other chats are logged but not delivered, unless the
chat is the configured demo attacker chat (one you control, for the
shield-off demo).
"""

from typing import Any

import httpx

from tripwire.events import EgressEvent, EventBus

API = "https://api.telegram.org"
MAX_MESSAGE_CHARS = 4000


class TelegramSender:
    def __init__(
        self,
        token: str,
        owner_chat_id: str,
        bus: EventBus,
        demo_mode: bool = False,
        demo_attacker_chat_id: str = "",
        http: httpx.Client | None = None,
    ) -> None:
        self.token = token
        self.owner_chat_id = str(owner_chat_id)
        self.bus = bus
        self.demo_mode = demo_mode
        self.demo_attacker_chat_id = str(demo_attacker_chat_id)
        self.http = http or httpx.Client(timeout=15)

    def send(self, text: str, chat_id: str | int | None = None) -> dict[str, Any]:
        chat = str(chat_id) if chat_id not in (None, "") else self.owner_chat_id
        text = str(text)[:MAX_MESSAGE_CHARS]
        to_self = chat == self.owner_chat_id and bool(chat)
        target = "self" if to_self else f"chat:{chat}"

        if not chat:
            return self._log(target, text, False, "no chat id configured (set TELEGRAM_CHAT_ID)")
        if not self.token:
            return self._log(target, text, False, "no bot token configured (set TELEGRAM_BOT_TOKEN)")
        if self.demo_mode and not to_self and chat != self.demo_attacker_chat_id:
            return self._log(target, text, False, "demo mode: messages to other chats are not delivered")

        try:
            resp = self.http.post(f"{API}/bot{self.token}/sendMessage", json={"chat_id": chat, "text": text})
        except httpx.HTTPError as exc:
            # Never surface the exception text: Bot API URLs contain the token.
            return self._log(target, text, False, f"network error contacting Telegram ({type(exc).__name__})")
        try:
            body = resp.json()
        except ValueError:
            body = {}
        ok = resp.status_code == 200 and body.get("ok") is True
        note = "delivered" if ok else f"Telegram error {resp.status_code}: {body.get('description', 'no description')}"
        return self._log(target, text, ok, note)

    def _log(self, target: str, text: str, delivered: bool, note: str) -> dict[str, Any]:
        self.bus.publish(EgressEvent.build("send_telegram", target, text, delivered, note))
        return {"delivered": delivered, "to": target, "note": note}
