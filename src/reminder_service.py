from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import html
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram.constants import ParseMode
from telegram.ext import Application

from src.config import Settings
from src.state_store import BotStateStore


logger = logging.getLogger(__name__)


class ReminderService:
    def __init__(
        self,
        application: Application,
        settings: Settings,
        state_store: BotStateStore,
    ) -> None:
        self._application = application
        self._settings = settings
        self._state_store = state_store
        self._task: asyncio.Task | None = None
        self._tzinfo = _resolve_timezone(settings.bot_timezone)

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="reminder_service_loop")
        logger.info("reminder service started", extra={"event": "reminder_started"})

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info("reminder service stopped", extra={"event": "reminder_stopped"})

    async def _loop(self) -> None:
        while True:
            await self._dispatch_due_reminders()
            await asyncio.sleep(max(5, self._settings.reminder_poll_interval_seconds))

    async def _dispatch_due_reminders(self) -> None:
        now_utc = datetime.now(timezone.utc)
        due = self._state_store.list_due_reminders(
            now_utc=now_utc,
            retry_limit=self._settings.reminder_send_retry_limit,
            limit=100,
        )
        for item in due:
            reminder_id = int(item["id"])
            chat_id = int(item["chat_id"])
            text = str(item["text"])
            remind_at = _parse_iso(item["remind_at_utc"])
            message = (
                "<b>Lembrete</b>\n"
                f"Horario: {html.escape(_format_dt(remind_at, self._tzinfo))}\n"
                f"Texto: {html.escape(text)}"
            )
            try:
                await self._application.bot.send_message(
                    chat_id=chat_id,
                    text=message,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                self._state_store.mark_reminder_sent(
                    reminder_id=reminder_id,
                    sent_at_utc=datetime.now(timezone.utc),
                )
                self._state_store.record_audit_event(
                    trace_id=None,
                    event_type="reminder_sent",
                    command="/lembrete",
                    chat_id=chat_id,
                    user_id=item.get("user_id"),
                    username=item.get("username"),
                    status="ok",
                    severity="info",
                    payload={"reminder_id": reminder_id},
                )
            except Exception as exc:
                self._state_store.mark_reminder_failed(
                    reminder_id=reminder_id,
                    error_text=str(exc),
                )
                self._state_store.record_audit_event(
                    trace_id=None,
                    event_type="reminder_send_error",
                    command="/lembrete",
                    chat_id=chat_id,
                    user_id=item.get("user_id"),
                    username=item.get("username"),
                    status="error",
                    severity="alerta",
                    payload={"reminder_id": reminder_id, "error": str(exc)},
                )


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def _format_dt(value: datetime | None, tzinfo) -> str:
    if value is None:
        return "indisponivel"
    return value.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M")


def _resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            from datetime import timedelta

            return timezone(timedelta(hours=-3))
        return timezone.utc
