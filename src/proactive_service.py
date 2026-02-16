from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
import hashlib
import logging
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram.constants import ParseMode
from telegram.ext import Application

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.orchestrator import StatusOrchestrator
from src.config import AlertPriorityRule, Settings
from src.message_utils import split_message
from src.state_store import BotStateStore


logger = logging.getLogger(__name__)


class ProactiveService:
    def __init__(
        self,
        application: Application,
        settings: Settings,
        orchestrator: StatusOrchestrator,
        state_store: BotStateStore,
    ) -> None:
        self._application = application
        self._settings = settings
        self._orchestrator = orchestrator
        self._state_store = state_store
        self._task: asyncio.Task | None = None
        self._last_check_at: datetime | None = None
        self._last_morning_date: str | None = None
        self._last_night_date: str | None = None
        self._morning_time = self._parse_hhmm(settings.proactive_morning_time)
        self._night_time = self._parse_hhmm(settings.proactive_night_time)
        self._tzinfo = self._resolve_timezone(settings.bot_timezone)

    async def start(self) -> None:
        if not self._settings.proactive_enabled:
            logger.info(
                "proactive service disabled by config",
                extra={"event": "proactive_disabled"},
            )
            return
        if self._settings.telegram_allowed_chat_id is None:
            logger.warning(
                "proactive service disabled: no allowed chat configured",
                extra={"event": "proactive_disabled"},
            )
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="proactive_service_loop")
        logger.info("proactive service started", extra={"event": "proactive_started"})

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info("proactive service stopped", extra={"event": "proactive_stopped"})

    async def _loop(self) -> None:
        while True:
            now_local = datetime.now(self._tzinfo)
            await self._run_periodic_if_due(now_local)
            await self._run_daily_summaries_if_due(now_local)
            await asyncio.sleep(15)

    async def _run_periodic_if_due(self, now_local: datetime) -> None:
        if self._last_check_at:
            elapsed = (now_local - self._last_check_at).total_seconds()
            if elapsed < self._settings.proactive_check_interval_seconds:
                return
        self._last_check_at = now_local
        trace_id = self._new_trace_id()
        context = self._build_context(trace_id, "proactive:host-check")
        results = await self._orchestrator.run_trigger("host", context)
        for result in results:
            state_key = f"proactive:host:{result.title}"
            signature = self._build_state_signature(result.message)
            changed, previous = self._state_store.compare_and_set_state(state_key, signature)
            if previous is None:
                logger.info(
                    "baseline state stored for proactive host check",
                    extra={"event": "proactive_baseline", "trace_id": trace_id},
                )
                continue
            if not changed:
                continue
            severity = self._classify_severity(result)
            rule = self._match_priority_rule(result.message)
            await self._notify_change(result, trace_id, severity, rule)

    async def _run_daily_summaries_if_due(self, now_local: datetime) -> None:
        date_key = now_local.strftime("%Y-%m-%d")
        if (
            self._last_morning_date != date_key
            and now_local.time() >= self._morning_time
        ):
            self._last_morning_date = date_key
            await self._send_summary("manha", "proactive:morning-summary")
        if self._last_night_date != date_key and now_local.time() >= self._night_time:
            self._last_night_date = date_key
            await self._send_summary("noite", "proactive:night-summary")

    async def _send_summary(self, label: str, command_name: str) -> None:
        chat_id = self._settings.telegram_allowed_chat_id
        if chat_id is None:
            return
        trace_id = self._new_trace_id()
        context = self._build_context(trace_id, command_name)
        await self._send_text(
            chat_id,
            f"<b>Resumo automatico ({label})</b>\nTrace: <code>{trace_id}</code>",
        )
        for trigger in ("status", "host"):
            results = await self._orchestrator.run_trigger(trigger, context)
            for result in results:
                for chunk in split_message(result.message):
                    await self._send_text(chat_id, chunk)

    async def _notify_change(
        self,
        result: AutomationResult,
        trace_id: str,
        severity: str,
        rule: AlertPriorityRule | None,
    ) -> None:
        chat_id = self._settings.telegram_allowed_chat_id
        if chat_id is None:
            return
        header = (
            f"<b>Alerta Proativo</b>\n"
            f"Severidade: <b>{severity.upper()}</b>\n"
            f"Fonte: {result.title}\n"
            f"Trace: <code>{trace_id}</code>"
        )
        if rule:
            header += (
                f"\nCliente: <b>{rule.client}</b>\nSistema: <b>{rule.system}</b>"
            )
        await self._send_text(chat_id, header)
        for chunk in split_message(result.message):
            await self._send_text(chat_id, chunk)

        if rule and rule.call and severity == "critico":
            await self._send_text(
                chat_id,
                "<b>ALERTA CRITICO (modo ligacao)</b>\n"
                "Bot nao consegue ligar diretamente via Telegram. "
                "Enviando notificacoes reforcadas.",
            )
            repeats = max(1, self._settings.proactive_call_repeat_count)
            for idx in range(repeats):
                await self._send_text(
                    chat_id,
                    f"<b>ALERTA CRITICO</b> {rule.client}/{rule.system} "
                    f"(toque {idx + 1}/{repeats})",
                )
                await asyncio.sleep(1)

    async def _send_text(self, chat_id: int, text: str) -> None:
        await self._application.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    def _build_context(self, trace_id: str, command_name: str) -> AutomationContext:
        return AutomationContext(
            settings=self._settings,
            trace_id=trace_id,
            chat_id=self._settings.telegram_allowed_chat_id,
            user_id=None,
            username="proactive-service",
            command=command_name,
        )

    @staticmethod
    def _new_trace_id() -> str:
        return uuid.uuid4().hex[:12]

    def _classify_severity(self, result: AutomationResult) -> str:
        if result.severity in {"info", "alerta", "critico"}:
            return result.severity
        if not result.ok:
            return "critico"
        text = result.message.lower()
        if "major_outage" in text or "fora do ar" in text:
            return "critico"
        if "alerta" in text or "down" in text or "falha" in text:
            return "alerta"
        return "info"

    def _match_priority_rule(self, message: str) -> AlertPriorityRule | None:
        text = message.lower()
        for rule in self._settings.alert_priority_rules:
            if rule.pattern in text:
                return rule
        return None

    def _build_state_signature(self, message: str) -> str:
        lines: list[str] = []
        for raw_line in message.splitlines():
            stripped = self._strip_html(raw_line).strip()
            if not stripped:
                continue
            lowered = stripped.lower()
            if lowered.startswith("trace:"):
                continue
            if lowered.startswith("server maintenance |"):
                continue
            if re.match(r"^\d{2}:\d{2}\s+---\s+\d{2}:\d{2}", lowered):
                continue
            if "| inicio:" in lowered and "| fim:" in lowered:
                continue
            if lowered.startswith("- pve-node"):
                continue
            normalized = re.sub(
                r"\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}",
                "<datetime>",
                lowered,
            )
            lines.append(normalized)
        digest = hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
        return digest

    @staticmethod
    def _strip_html(text: str) -> str:
        return re.sub(r"<[^>]*>", "", text)

    @staticmethod
    def _parse_hhmm(value: str) -> time:
        raw = (value or "").strip()
        try:
            hour_str, minute_str = raw.split(":")
            hour = int(hour_str)
            minute = int(minute_str)
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return time(hour=hour, minute=minute)
        except Exception:
            pass
        return time(hour=8, minute=0)

    @staticmethod
    def _resolve_timezone(timezone_name: str):
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            if timezone_name == "America/Sao_Paulo":
                return timezone(timedelta(hours=-3))
            return timezone.utc
