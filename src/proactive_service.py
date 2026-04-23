from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta, timezone
import html
import hashlib
import logging
import re
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram.constants import ParseMode
from telegram.ext import Application

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.orchestrator import StatusOrchestrator
from src.automations_lib.providers.ami_client import AmiError
from src.automations_lib.providers.issabel_ami_provider import IssabelAmiProvider
from src.bridge import BridgeNotifier
from src.config import AlertPriorityRule, Settings
from src.message_utils import split_message
from src.state_store import BotStateStore


logger = logging.getLogger(__name__)


class ProactiveService:
    AMI_ONLINE_DROP_ALERT_DELTA = -2
    AMI_ALERT_QUIET_START = time(hour=18, minute=0)
    AMI_ALERT_QUIET_END = time(hour=7, minute=0)

    def __init__(
        self,
        application: Application,
        settings: Settings,
        orchestrator: StatusOrchestrator,
        state_store: BotStateStore,
        issabel_provider: IssabelAmiProvider | None = None,
        bridge_notifier: BridgeNotifier | None = None,
    ) -> None:
        self._application = application
        self._settings = settings
        self._orchestrator = orchestrator
        self._state_store = state_store
        self._bridge_notifier = bridge_notifier
        self._task: asyncio.Task | None = None
        self._last_check_at: datetime | None = None
        self._last_morning_date: str | None = None
        self._last_night_date: str | None = None
        self._morning_time = self._parse_hhmm(settings.proactive_morning_time)
        self._night_time = self._parse_hhmm(settings.proactive_night_time)
        self._tzinfo = self._resolve_timezone(settings.bot_timezone)
        self._issabel_provider = issabel_provider or IssabelAmiProvider(
            host=settings.issabel_ami_host,
            rawman_url=settings.issabel_ami_rawman_url,
            port=settings.issabel_ami_port,
            username=settings.issabel_ami_username,
            secret=settings.issabel_ami_secret,
            timeout_seconds=settings.issabel_ami_timeout_seconds,
            use_tls=settings.issabel_ami_use_tls,
            peer_name_regex=settings.issabel_ami_peer_name_regex,
        )

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
            severity = self._classify_severity(result)
            signature = self._build_state_signature(result.message)
            state_value = f"{severity}|{signature}"
            changed, previous = self._state_store.compare_and_set_state(
                state_key, state_value
            )
            if previous is None:
                logger.info(
                    "baseline state stored for proactive host check",
                    extra={"event": "proactive_baseline", "trace_id": trace_id},
                )
                continue
            if not changed:
                continue
            previous_severity = self._parse_state_severity(previous)
            is_recovery = previous_severity in {"alerta", "critico"} and severity == "info"
            # Periodic notifications should reduce noise: only alert on real problems
            # (alerta/critico) or when recovering from a previous problem.
            if severity == "info" and not is_recovery:
                continue
            rule = self._match_priority_rule(result.message)
            await self._notify_change(
                result,
                trace_id,
                severity,
                rule,
                is_recovery=is_recovery,
            )
        await self._run_ami_check(trace_id, now_local=now_local)

    async def _run_ami_check(
        self,
        trace_id: str,
        *,
        now_local: datetime | None = None,
    ) -> None:
        chat_id = self._settings.telegram_allowed_chat_id
        current_local = now_local or datetime.now(self._tzinfo)
        try:
            overview = await self._issabel_provider.list_voip_overview()
        except ValueError:
            self._state_store.record_audit_event(
                trace_id=trace_id,
                event_type="ami_probe_tick",
                command="/host",
                chat_id=chat_id,
                user_id=None,
                username="proactive-service",
                status="ok",
                severity="info",
                payload={"configured": False, "reason": "not_configured"},
            )
            return
        except AmiError as exc:
            await self._handle_ami_error(
                trace_id,
                str(exc),
                now_local=current_local,
            )
            return
        except Exception as exc:
            await self._handle_ami_error(
                trace_id,
                str(exc),
                now_local=current_local,
            )
            return

        now_utc = datetime.now(timezone.utc)
        previous_snapshot = self._state_store.get_ami_peer_snapshot_at_or_before(
            target_utc=now_utc - timedelta(microseconds=1)
        )
        self._state_store.record_ami_peer_snapshot(
            captured_at_utc=now_utc,
            online_count=overview.online_count,
            offline_count=overview.offline_count,
            connected_peers=overview.connected_peers,
        )
        changed, previous = self._state_store.compare_and_set_state(
            "proactive:ami:online_count",
            str(overview.online_count),
        )
        # Reset previous error signature on successful probe.
        self._state_store.compare_and_set_state("proactive:ami:last_error_signature", "")
        previous_online: int | None = None
        if previous is not None:
            try:
                previous_online = int(str(previous).strip())
            except ValueError:
                previous_online = None
        diff_online_prev: int | None = None
        drop_detected = False
        if previous_online is not None:
            diff_online_prev = int(overview.online_count) - previous_online
            drop_detected = (
                changed
                and diff_online_prev < self.AMI_ONLINE_DROP_ALERT_DELTA
            )
        dropped_peers = self._build_dropped_peers(
            previous_snapshot=previous_snapshot,
            current_connected_peers=overview.connected_peers,
        )
        suppression_reason = self._get_ami_alert_suppression_reason(current_local)
        payload = {
            "transport": self._issabel_provider.transport_name(),
            "endpoint": self._issabel_provider.endpoint_label(),
            "online_count": overview.online_count,
            "offline_count": overview.offline_count,
            "total_count": overview.total_count,
            "diff_online_prev": diff_online_prev,
            "drop_alert_threshold": self.AMI_ONLINE_DROP_ALERT_DELTA,
            "drop_detected": drop_detected,
        }
        if dropped_peers:
            payload["dropped_peers"] = dropped_peers
        if suppression_reason is not None:
            payload["alert_suppressed"] = True
            payload["suppression_reason"] = suppression_reason

        self._state_store.record_audit_event(
            trace_id=trace_id,
            event_type="ami_probe_tick",
            command="/host",
            chat_id=chat_id,
            user_id=None,
            username="proactive-service",
            status="ok",
            severity="alerta" if drop_detected else "info",
            payload=payload,
        )
        if drop_detected and chat_id is not None and suppression_reason is None:
            await self._notify_ami_alert(
                trace_id=trace_id,
                severity="alerta",
                details=self._build_ami_drop_details(
                    online_count=overview.online_count,
                    offline_count=overview.offline_count,
                    diff_online_prev=diff_online_prev,
                    dropped_peers=dropped_peers,
                ),
            )

    async def _handle_ami_error(
        self,
        trace_id: str,
        error_text: str,
        *,
        now_local: datetime | None = None,
    ) -> None:
        chat_id = self._settings.telegram_allowed_chat_id
        current_local = now_local or datetime.now(self._tzinfo)
        suppression_reason = self._get_ami_alert_suppression_reason(current_local)
        signature = error_text.strip().lower() or "unknown"
        changed, previous = self._state_store.compare_and_set_state(
            "proactive:ami:last_error_signature",
            signature,
        )
        payload = {
            "transport": self._issabel_provider.transport_name(),
            "endpoint": self._issabel_provider.endpoint_label(),
            "error": error_text,
            "phase": self._detect_ami_phase(error_text),
        }
        if suppression_reason is not None:
            payload["alert_suppressed"] = True
            payload["suppression_reason"] = suppression_reason
        self._state_store.record_audit_event(
            trace_id=trace_id,
            event_type="ami_probe_tick",
            command="/host",
            chat_id=chat_id,
            user_id=None,
            username="proactive-service",
            status="error",
            severity="alerta",
            payload=payload,
        )
        if chat_id is None:
            return
        if suppression_reason is not None:
            return
        if previous is not None and not changed:
            return
        await self._notify_ami_alert(
            trace_id=trace_id,
            severity="alerta",
            details=f"Falha AMI: {error_text}",
        )

    async def _notify_ami_alert(
        self,
        *,
        trace_id: str,
        severity: str,
        details: str,
    ) -> None:
        chat_id = self._settings.telegram_allowed_chat_id
        if chat_id is None:
            return
        text = (
            "<b>Alerta Proativo</b>\n"
            f"Severidade: <b>{severity.upper()}</b>\n"
            "Fonte: AMI\n"
            f"Trace: <code>{trace_id}</code>\n\n"
            f"{html.escape(details)}"
        )
        await self._send_text(chat_id, text)

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
        *,
        is_recovery: bool = False,
    ) -> None:
        chat_id = self._settings.telegram_allowed_chat_id
        if chat_id is None:
            return
        title = "Recuperacao Proativa" if is_recovery else "Alerta Proativo"
        header = (
            f"<b>{title}</b>\n"
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
        if self._bridge_notifier is not None:
            await self._bridge_notifier.send_telegram(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
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

    @staticmethod
    def _parse_state_severity(state_value: str) -> str:
        # Stored value format is "{severity}|{signature}". Keep backward compatibility
        # with older values that stored only the signature.
        raw = (state_value or "").strip()
        if "|" not in raw:
            return "info"
        prefix = raw.split("|", 1)[0].strip().lower()
        return prefix if prefix in {"info", "alerta", "critico"} else "info"

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
    def _detect_ami_phase(error_text: str | None) -> str | None:
        text = (error_text or "").strip().lower()
        if not text:
            return None
        if "login" in text:
            return "login"
        if "sippeers" in text:
            return "sippeers"
        if "logoff" in text:
            return "logoff"
        if "connect" in text or "connection" in text or "timeout" in text:
            return "connect"
        return None

    def _get_ami_alert_suppression_reason(
        self,
        now_local: datetime,
    ) -> str | None:
        if now_local.weekday() == 6:
            return "sunday"
        current_time = now_local.timetz().replace(tzinfo=None)
        if (
            current_time >= self.AMI_ALERT_QUIET_START
            or current_time < self.AMI_ALERT_QUIET_END
        ):
            return "quiet_hours"
        return None

    @staticmethod
    def _build_dropped_peers(
        *,
        previous_snapshot: dict | None,
        current_connected_peers: list[object],
    ) -> list[dict]:
        if previous_snapshot is None:
            return []
        previous_peers = previous_snapshot.get("connected_peers") or []
        if not isinstance(previous_peers, list) or not previous_peers:
            return []
        current_names = {
            str(getattr(peer, "name", "")).strip()
            for peer in current_connected_peers
            if str(getattr(peer, "name", "")).strip()
        }
        dropped: list[dict] = []
        for peer in previous_peers:
            if not isinstance(peer, dict):
                continue
            name = str(peer.get("name") or "").strip()
            if not name or name in current_names:
                continue
            ip = str(peer.get("ip") or "").strip()
            port = peer.get("port")
            last_ip = ip
            if ip and port not in (None, ""):
                last_ip = f"{ip}:{port}"
            dropped.append(
                {
                    "name": name,
                    "last_ip": last_ip or "-",
                    "status": str(peer.get("status") or "").strip() or None,
                }
            )
        dropped.sort(
            key=lambda item: (
                0 if str(item["name"]).isdigit() else 1,
                int(item["name"]) if str(item["name"]).isdigit() else str(item["name"]),
            )
        )
        return dropped

    @staticmethod
    def _build_ami_drop_details(
        *,
        online_count: int,
        offline_count: int,
        diff_online_prev: int | None,
        dropped_peers: list[dict],
    ) -> str:
        lines = [
            "Queda de ramais online detectada",
            f"Online: {online_count}",
            f"Offline: {offline_count}",
            f"Diferenca vs coleta anterior: {diff_online_prev}",
        ]
        if dropped_peers:
            lines.append("Ramais que sairam do online:")
            for peer in dropped_peers:
                line = f"- {peer['name']} | ultimo IP: {peer['last_ip']}"
                if peer.get("status"):
                    line += f" | status: {peer['status']}"
                lines.append(line)
        else:
            lines.append("Detalhes dos ramais indisponiveis nesta comparacao.")
        return "\n".join(lines)

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
