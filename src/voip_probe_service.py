from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import html
import logging
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram.constants import ParseMode
from telegram.ext import Application

from src.automations_lib.providers.voip_probe_provider import (
    VoipProbeProvider,
    VoipProbeResult,
)
from src.config import Settings
from src.state_store import BotStateStore


logger = logging.getLogger(__name__)


class VoipProbeService:
    def __init__(
        self,
        *,
        application: Application,
        settings: Settings,
        state_store: BotStateStore,
        provider: VoipProbeProvider,
    ) -> None:
        self._application = application
        self._settings = settings
        self._state_store = state_store
        self._provider = provider
        self._task: asyncio.Task | None = None
        self._tzinfo = _resolve_timezone(settings.bot_timezone)

    async def start(self) -> None:
        if not self._settings.voip_probe_enabled:
            logger.info(
                "voip probe service disabled by config",
                extra={"event": "voip_probe_disabled"},
            )
            return
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="voip_probe_service_loop")
        logger.info("voip probe service started", extra={"event": "voip_probe_started"})

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        logger.info("voip probe service stopped", extra={"event": "voip_probe_stopped"})

    async def _loop(self) -> None:
        while True:
            await self._run_probe_once()
            await asyncio.sleep(max(60, self._settings.voip_probe_interval_seconds))

    async def _run_probe_once(self) -> None:
        chat_id = self._settings.voip_alert_chat_id or self._settings.telegram_allowed_chat_id
        try:
            result = await self._provider.run_once()
            self._state_store.record_audit_event(
                trace_id=None,
                event_type="voip_probe_tick",
                command="/voip",
                chat_id=chat_id,
                user_id=None,
                username="voip-probe-service",
                status="ok" if result.ok else "error",
                severity=self._result_severity(result),
                payload={
                    "target_number": result.target_number,
                    "setup_latency_ms": result.setup_latency_ms,
                    "sip_final_code": result.sip_final_code,
                    "error": result.error,
                },
            )
            if chat_id is not None and self._should_alert(result):
                await self._application.bot.send_message(
                    chat_id=chat_id,
                    text=self._format_alert_message(result),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        except Exception as exc:
            self._state_store.record_audit_event(
                trace_id=None,
                event_type="voip_probe_tick",
                command="/voip",
                chat_id=chat_id,
                user_id=None,
                username="voip-probe-service",
                status="error",
                severity="critico",
                payload={"error": str(exc)},
            )
            if chat_id is not None:
                await self._application.bot.send_message(
                    chat_id=chat_id,
                    text=(
                        "<b>Alerta VoIP</b>\n"
                        "Falha ao executar teste automatico.\n"
                        f"Erro: {html.escape(str(exc))}"
                    ),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )

    def _should_alert(self, result: VoipProbeResult) -> bool:
        if not result.ok:
            return True
        summary = result.summary if isinstance(result.summary, dict) else {}
        if bool(summary.get("ami_warning")):
            return True
        if bool(summary.get("deviation_alert")):
            return True
        return (
            result.setup_latency_ms is not None
            and result.setup_latency_ms > self._settings.voip_latency_alert_ms
        )

    def _result_severity(self, result: VoipProbeResult) -> str:
        if not result.ok:
            return "critico"
        summary = result.summary if isinstance(result.summary, dict) else {}
        if bool(summary.get("ami_warning")):
            return "alerta"
        if bool(summary.get("deviation_alert")):
            return "alerta"
        if (
            result.setup_latency_ms is not None
            and result.setup_latency_ms > self._settings.voip_latency_alert_ms
        ):
            return "alerta"
        return "info"

    def _format_alert_message(self, result: VoipProbeResult) -> str:
        started = _format_dt(result.started_at_utc, self._tzinfo)
        finished = _format_dt(result.finished_at_utc, self._tzinfo)
        summary = result.summary if isinstance(result.summary, dict) else {}
        ami_warning = bool(summary.get("ami_warning"))
        ami_warning_reason = str(summary.get("ami_warning_reason") or "").strip() or None
        baseline_alert = bool(summary.get("deviation_alert"))
        destination = result.failure_destination_number or result.target_number
        high_latency = (
            result.setup_latency_ms is not None
            and result.setup_latency_ms > self._settings.voip_latency_alert_ms
        )
        if not result.ok:
            status = "FALHA"
        elif baseline_alert:
            status = "DESVIO BASELINE"
        elif ami_warning:
            status = "AMI WARN"
        elif high_latency:
            status = "LATENCIA ALTA"
        else:
            status = "INFO"
        error_text = result.error or "-"
        if result.ok and ami_warning and ami_warning_reason:
            error_text = ami_warning_reason
        message = (
            "<b>Alerta VoIP</b>\n"
            f"Status: <b>{status}</b>\n"
            f"Destino: {html.escape(destination)}\n"
            f"Latencia: {result.setup_latency_ms if result.setup_latency_ms is not None else '-'} ms\n"
            f"Codigo SIP: {result.sip_final_code if result.sip_final_code is not None else '-'}\n"
            f"Inicio: {html.escape(started)}\n"
            f"Fim: {html.escape(finished)}\n"
            f"Erro: {html.escape(error_text)}"
        )
        if result.failure_stage:
            message += f"\nEstagio: {html.escape(result.failure_stage)}"
        if ami_warning and not (result.ok and ami_warning_reason):
            message += f"\nAMI: {html.escape(ami_warning_reason or 'warn')}"
        if baseline_alert:
            reasons = summary.get("deviation_reasons")
            if isinstance(reasons, list) and reasons:
                message += "\nBaseline:\n"
                for item in reasons[:3]:
                    message += f"- {html.escape(str(item)[:180])}\n"
            else:
                message += "\nBaseline: desvio detectado."
        return message.rstrip()


def _resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            from datetime import timedelta

            return timezone(timedelta(hours=-3))
        return timezone.utc


def _format_dt(value: str, tzinfo) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return "indisponivel"
    return parsed.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M:%S")
