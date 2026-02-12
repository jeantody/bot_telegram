from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return
    await update.message.reply_text(
        "Bot online. Use status ou /status para consultar as automações."
    )


async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    del context
    if not update.message:
        return
    await update.message.reply_text("Comandos: /start, /help, status, /status")

