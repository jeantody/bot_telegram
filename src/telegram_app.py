from __future__ import annotations

from telegram.ext import Application, CommandHandler

from src.config import Settings
from src.handlers import help_handler, start_handler


def build_application(settings: Settings) -> Application:
    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(CommandHandler("help", help_handler))
    return application

