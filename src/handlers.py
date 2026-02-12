from __future__ import annotations

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from src.automations_lib.models import AutomationContext
from src.automations_lib.orchestrator import StatusOrchestrator
from src.config import Settings


def _command_token(text: str) -> str:
    return text.strip().split()[0].lower() if text.strip() else ""


def _is_named_command(
    text: str,
    command: str,
    bot_username: str | None = None,
) -> bool:
    token = _command_token(text)
    if token in {command, f"/{command}"}:
        return True
    if token.startswith(f"/{command}@"):
        if not bot_username:
            return True
        target = token.split("@", maxsplit=1)[1]
        return target == bot_username.lower()
    return False


def is_status_command(text: str, bot_username: str | None = None) -> bool:
    return _is_named_command(text=text, command="status", bot_username=bot_username)


def is_host_command(text: str, bot_username: str | None = None) -> bool:
    return _is_named_command(text=text, command="host", bot_username=bot_username)


def is_all_command(text: str, bot_username: str | None = None) -> bool:
    return _is_named_command(text=text, command="all", bot_username=bot_username)


def split_message(text: str, max_length: int = 3900) -> list[str]:
    if len(text) <= max_length:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_length:
        split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        chunks.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip("\n")
    if remaining:
        chunks.append(remaining)
    return chunks


class BotHandlers:
    BLOCKED_MESSAGE = "Acesso nao autorizado para este chat."

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
            "Bot online. Use /status, /host ou /all."
        )

    async def help_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text(
            "Comandos: /start, /help, status, /status, /host, /all"
        )

    async def status_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._run_single_trigger(update, context, trigger="status")

    async def host_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._run_single_trigger(update, context, trigger="host")

    async def all_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat:
            return
        if not self._is_allowed_chat(chat.id):
            await message.reply_text(self.BLOCKED_MESSAGE)
            return

        automation_context = AutomationContext(settings=self._settings)
        await self._execute_trigger(message, automation_context, "status")
        await self._execute_trigger(message, automation_context, "host")

    async def text_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not update.message or not update.message.text:
            return
        bot_username = context.bot.username.lower() if context.bot.username else None
        if is_status_command(update.message.text, bot_username=bot_username):
            await self._run_single_trigger(update, context, trigger="status")

    async def _run_single_trigger(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        trigger: str,
    ) -> None:
        del context
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat:
            return

        if not self._is_allowed_chat(chat.id):
            await message.reply_text(self.BLOCKED_MESSAGE)
            return

        automation_context = AutomationContext(settings=self._settings)
        await self._execute_trigger(message, automation_context, trigger)

    async def _execute_trigger(
        self,
        message,
        automation_context: AutomationContext,
        trigger: str,
    ) -> None:
        results = await self._orchestrator.run_trigger(trigger, automation_context)
        if not results:
            await message.reply_text(
                f"Nenhuma automacao registrada para {trigger}."
            )
            return

        for result in results:
            for chunk in split_message(result.message):
                await message.reply_text(
                    chunk,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )

    def _is_allowed_chat(self, chat_id: int) -> bool:
        allowed_chat_id = self._settings.telegram_allowed_chat_id
        if allowed_chat_id is None:
            return False
        return chat_id == allowed_chat_id
