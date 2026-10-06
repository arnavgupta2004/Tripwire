"""Telegram as a full interface: chat, approval cards with inline buttons, memory.

The approval card mirrors what the UI shows. Whichever channel answers first wins
(the broker enforces it), so a tap here and a click in the web UI can't both apply.
"""

import logging
import threading
from collections.abc import Callable
from typing import Any

from tripwire.session import ApprovalInfo, Session

log = logging.getLogger(__name__)

# (label, answer) pairs for the inline keyboard.
BUTTONS = [("✅ Allow once", "allow"), ("🚫 Deny", "deny"), ("⛔ Always deny this", "always_deny")]
ANSWER_REPLY = {"allow": "Allowed once.", "deny": "Denied.", "always_deny": "Denied, and I'll always deny this pattern."}

# Sender: (chat_id, text, buttons) -> None. buttons is a list of (label, callback_data) or None.
Sender = Callable[[str, str, list[tuple[str, str]] | None], None]


def approval_card(info: ApprovalInfo) -> tuple[str, list[tuple[str, str]]]:
    """The message text and inline buttons for a pending approval."""
    lines = [
        "⚠️ *Tripwire paused an action*",
        f"*What:* `{info.tool}` {_short(info.args)}",
        f"*Why:* {info.explanation or info.reason}",
    ]
    if info.evidence:
        lines.append(f"*Source:* {info.evidence}")
    buttons = [(label, f"ap:{info.id}:{answer}") for label, answer in BUTTONS]
    return "\n".join(lines), buttons


def _short(args: dict[str, Any], limit: int = 120) -> str:
    import json

    text = json.dumps(args, ensure_ascii=False, default=str)
    return text if len(text) <= limit else text[: limit - 1] + "…"


class TripwireBot:
    """Channel-agnostic Telegram logic. PTB wiring lives in build_telegram()."""

    def __init__(self, session: Session, owner_chat_id: str, sender: Sender) -> None:
        self.session = session
        self.owner = str(owner_chat_id)
        self.sender = sender
        self._unsub: Callable[[], None] | None = None

    def start(self) -> None:
        """Send an approval card to the owner whenever a turn pauses."""
        def on_event(event: Any) -> None:
            if getattr(event, "kind", None) == "approval_opened":
                info = self.session.broker.get(event.call_id)
                if info is not None:
                    text, buttons = approval_card(info)
                    self.sender(self.owner, text, buttons)

        self._unsub = self.session.bus.subscribe(on_event)

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None

    def authorized(self, chat_id: str | int) -> bool:
        return str(chat_id) == self.owner

    # --- incoming ------------------------------------------------------------

    def handle_text(self, chat_id: str | int, text: str) -> None:
        if not self.authorized(chat_id):
            self.sender(str(chat_id), "Sorry, this assistant only talks to its owner.", None)
            return
        text = text.strip()
        if text in ("/start", "/help"):
            self.sender(self.owner, "Tripwire online. Ask me to research, read your files, or brief you.", None)
            return
        if text == "/memory":
            self.sender(self.owner, self.memory_listing(), None)
            return
        if text in ("/brief_now", "/brief"):
            self._run_async(self.session.run_brief)
            return
        if text == "/new":
            self.session.new_thread()
            self.sender(self.owner, "Started a new thread.", None)
            return
        scheduled = self.session.maybe_schedule_brief(text)
        if scheduled is not None:
            self.sender(self.owner, scheduled, None)
            return
        self._run_async(lambda: self.session.chat(text, source="telegram"))

    def handle_button(self, chat_id: str | int, data: str) -> str:
        """Resolve an approval from a button tap. Returns a short status for the tap."""
        if not self.authorized(chat_id):
            return "Not authorized."
        try:
            _, approval_id, answer = data.split(":", 2)
        except ValueError:
            return "Unrecognized button."
        if answer not in ("allow", "deny", "always_deny"):
            return "Unrecognized choice."
        won = self.session.broker.resolve(approval_id, answer)
        return ANSWER_REPLY[answer] if won else "Already answered elsewhere."

    def memory_listing(self) -> str:
        facts = self.session.skills.memory.all()
        lines = ["*What I remember:*"] if facts else ["I don't have anything saved yet."]
        for f in facts:
            mark = "" if f.label.is_trusted else "  ⚠️ _untrusted — info only_"
            lines.append(f"• {f.value}{mark}")
        tasks = self.session.skills.memory.tasks()
        if tasks:
            lines.append("\n*Daily briefs:*")
            lines += [f"• {t.schedule} — {t.topic}" for t in tasks]
        return "\n".join(lines)

    def _run_async(self, work: Callable[[], Any]) -> None:
        """Run a turn off the bot loop, then send its reply. Approval cards arrive
        meanwhile via the bus subscription set up in start()."""
        def run() -> None:
            try:
                outcome = work()
                reply = getattr(outcome, "reply", None)
                if reply:
                    self.sender(self.owner, reply, None)
            except Exception:
                log.exception("telegram turn failed")
                self.sender(self.owner, "Something went wrong handling that. Please try again.", None)

        threading.Thread(target=run, daemon=True).start()


def build_telegram(session: Session):  # pragma: no cover - requires a bot token and network
    """Wire TripwireBot into a python-telegram-bot Application."""
    import asyncio

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
    from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

    token = session.settings.telegram_bot_token
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN is not set")
    app = Application.builder().token(token).build()
    loop_box: dict[str, Any] = {}

    def sender(chat_id: str, text: str, buttons: list[tuple[str, str]] | None) -> None:
        markup = None
        if buttons:
            markup = InlineKeyboardMarkup([[InlineKeyboardButton(label, callback_data=data)] for label, data in buttons])
        loop = loop_box.get("loop")
        coro = app.bot.send_message(chat_id=chat_id, text=text, reply_markup=markup, parse_mode="Markdown")
        if loop is not None:
            asyncio.run_coroutine_threadsafe(coro, loop)

    bot = TripwireBot(session, session.settings.telegram_chat_id, sender)

    async def on_message(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        bot.handle_text(update.effective_chat.id, update.message.text or "")

    async def on_button(update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        status = bot.handle_button(update.effective_chat.id, update.callback_query.data)
        await update.callback_query.answer(status)

    async def post_init(_app: Application) -> None:
        loop_box["loop"] = asyncio.get_running_loop()
        bot.start()

    app.post_init = post_init
    app.add_handler(CommandHandler(["start", "help", "memory", "brief_now", "brief", "new"],
                                   lambda u, c: on_message(u, c)))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_message))
    app.add_handler(CallbackQueryHandler(on_button))
    return app, bot
