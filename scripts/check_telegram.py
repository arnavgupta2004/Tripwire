"""Check the Telegram bot: replies "Tripwire online" to /start and echoes text.

Prints your chat ID when you send /start -- put it in .env as TELEGRAM_CHAT_ID.
Stop with Ctrl+C.

Usage: uv run python scripts/check_telegram.py
"""

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from _common import load_env, require


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    print(f"/start from chat_id={chat.id} ({chat.username or chat.title or 'unknown'})")
    await update.message.reply_text("Tripwire online")


async def echo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"echo to chat_id={update.effective_chat.id}: {update.message.text!r}")
    await update.message.reply_text(update.message.text)


def main() -> None:
    load_env()
    app = Application.builder().token(require("TELEGRAM_BOT_TOKEN")).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, echo))
    print("Bot polling. Send /start to your bot in Telegram. Ctrl+C to stop.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
