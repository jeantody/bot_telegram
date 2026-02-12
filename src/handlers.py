from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.automations_lib.models import AutomationContext
from src.automations_lib.orchestrator import StatusOrchestrator
from src.config import Settings


def is_status_command(text: str, bot_username: str | None = None) -> bool:
    token = text.strip().split()[0].lower() if text.strip() else ""
    if token in {"status", "/status"}:
        return True
    if token.startswith("/status@"):
        if not bot_username:
            return True
        target = token.split("@", maxsplit=1)[1]
        return target == bot_username.lower()
    return False


class BotHandlers:
    def __init__(self, settings: Settings, orchestrator: StatusOrchestrator) -> None:
        self._settings = settings
        self._orchestrator = orchestrator

    async def start_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text(
            "Bot online. Use status ou /status para consultar as automacoes."
        )

    async def help_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text("Comandos: /start, /help, status, /status")

    async def status_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._run_status(update, context)

    async def text_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.message or not update.message.text:
            return
        bot_username = context.bot.username.lower() if context.bot.username else None
        if is_status_command(update.message.text, bot_username=bot_username):
            await self._run_status(update, context)

    async def _run_status(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat:
            return

        if not self._is_allowed_chat(chat.id):
            await message.reply_text("Acesso nao autorizado para este chat.")
            return

        automation_context = AutomationContext(settings=self._settings)
        results = await self._orchestrator.run_trigger("status", automation_context)
        if not results:
            await message.reply_text("Nenhuma automacao registrada para status.")
            return

        for result in results:
            await message.reply_text(
                result.message,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    def _is_allowed_chat(self, chat_id: int) -> bool:
        allowed_chat_id = self._settings.telegram_allowed_chat_id
        if allowed_chat_id is None:
            return False
        return chat_id == allowed_chat_id

