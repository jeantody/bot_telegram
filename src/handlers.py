from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from telegram import Message, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes
import uuid

from src.automations_lib.models import AutomationContext
from src.automations_lib.orchestrator import StatusOrchestrator
from src.automations_lib.providers.ami_client import AmiError
from src.automations_lib.providers.cep_provider import CepProvider
from src.automations_lib.providers.issabel_ami_provider import IssabelAmiProvider
from src.automations_lib.providers.network_diagnostics_provider import (
    NetworkDiagnosticsProvider,
)
from src.automations_lib.providers.ssl_provider import SslProvider
from src.automations_lib.providers.voip_probe_provider import (
    VoipProbeProvider,
)
from src.automations_lib.providers.whois_provider import WhoisProvider
from src.config import Settings
from src.message_utils import split_message
from src.state_store import BotStateStore


logger = logging.getLogger(__name__)


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


def is_health_command(text: str, bot_username: str | None = None) -> bool:
    return _is_named_command(text=text, command="health", bot_username=bot_username)


class BotHandlers:
    BLOCKED_MESSAGE = "Acesso nao autorizado para este chat."
    TAB_ALIAS = {"estudo": "estudos"}
    TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")

    def __init__(
        self,
        settings: Settings,
        orchestrator: StatusOrchestrator,
        state_store: BotStateStore | None = None,
        whois_provider: WhoisProvider | None = None,
        cep_provider: CepProvider | None = None,
        network_provider: NetworkDiagnosticsProvider | None = None,
        ssl_provider: SslProvider | None = None,
        voip_provider: VoipProbeProvider | None = None,
        issabel_provider: IssabelAmiProvider | None = None,
    ) -> None:
        self._settings = settings
        self._orchestrator = orchestrator
        self._state_store = state_store
        self._whois_provider = whois_provider or WhoisProvider(
            timeout_seconds=settings.request_timeout_seconds,
            global_template=settings.whois_rdap_global_url_template,
            br_template=settings.whois_rdap_br_url_template,
        )
        self._cep_provider = cep_provider or CepProvider(
            timeout_seconds=settings.request_timeout_seconds,
            url_template=settings.viacep_url_template,
        )
        self._network_provider = network_provider or NetworkDiagnosticsProvider(
            ping_count=settings.ping_count,
            ping_timeout_seconds=settings.ping_timeout_seconds,
            traceroute_max_hops=settings.traceroute_max_hops,
            traceroute_timeout_seconds=settings.traceroute_timeout_seconds,
        )
        self._ssl_provider = ssl_provider or SslProvider(
            timeout_seconds=settings.ssl_timeout_seconds,
            alert_days=settings.ssl_alert_days,
            critical_days=settings.ssl_critical_days,
        )
        voip_timeout_seconds = max(
            90,
            (settings.voip_call_timeout_seconds * 7) + 20,
        )
        self._voip_provider = voip_provider or VoipProbeProvider(
            timeout_seconds=voip_timeout_seconds,
        )
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
        self._note_tab_map = {key: value for key, value in settings.note_tab_chat_ids}
        self._tzinfo = _resolve_timezone(settings.bot_timezone)

    async def start_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text(
            "Bot online. Use /status, /host, /health, /whois, /cep, /ping, /ssl, "
            "/voips, /voip, /voip_logs, /note, /lembrete, /logs ou /all."
        )

    async def help_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        if not update.message:
            return
        await update.message.reply_text(
            "Comandos: /start, /help, status, /status, /host, /health, /whois, "
            "/cep, /ping, /ssl, /voips, /voip, /voip_logs, /note, /lembrete, /logs, /all"
        )

    async def status_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._run_single_trigger(update, context, trigger="status")

    async def host_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._run_single_trigger(update, context, trigger="host")

    async def health_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        await self._run_single_trigger(update, context, trigger="health")

    async def whois_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/whois")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        raw_target = " ".join(context.args).strip()
        if not raw_target:
            await message.reply_text("Uso: /whois dominio.com")
            return
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/whois",
            context=automation_context,
            status="start",
            severity="info",
            payload={"target": raw_target},
        )
        try:
            result = await self._whois_provider.lookup(raw_target)
            if result.owner or result.owner_c or result.tech_c:
                lines = [
                    "<b>WHOIS</b>",
                    f"domain:      {html.escape(result.domain)}",
                    f"owner:       {html.escape(result.owner or 'indisponivel')}",
                    f"owner-c:     {html.escape(result.owner_c or 'indisponivel')}",
                    f"tech-c:      {html.escape(result.tech_c or 'indisponivel')}",
                ]
                for nserver, nsstat, nslastaa in (result.ns_pairs or []):
                    lines.append(f"nserver:     {html.escape(nserver)}")
                    lines.append(f"nsstat:      {html.escape(nsstat or '-')}")
                    lines.append(f"nslastaa:    {html.escape(nslastaa or '-')}")
                if result.dsrecord:
                    lines.append(f"dsrecord:    {html.escape(result.dsrecord)}")
                if result.dsstatus:
                    lines.append(f"dsstatus:    {html.escape(result.dsstatus)}")
                if result.dslastok:
                    lines.append(f"dslastok:    {html.escape(result.dslastok)}")
                if result.saci:
                    lines.append(f"saci:        {html.escape(result.saci)}")
                lines.append(f"created:     {html.escape(result.created_label or '-')}")
                lines.append(f"changed:     {html.escape(result.changed_label or '-')}")
                lines.append(f"expires:     {html.escape(result.expires_label or '-')}")
                lines.append(f"status:      {html.escape(result.status_label or '-')}")
                lines.append("")
                if result.nic_hdl_br:
                    lines.append(f"nic-hdl-br:  {html.escape(result.nic_hdl_br)}")
                lines.append(f"person:      {html.escape(result.person or result.owner or 'indisponivel')}")
                lines.append(f"created:     {html.escape(result.nic_created or '-')}")
                lines.append(f"changed:     {html.escape(result.nic_changed or '-')}")
            else:
                lines = [
                    "<b>WHOIS/RDAP</b>",
                    f"Dominio: <b>{html.escape(result.domain)}</b>",
                    f"Registrar: {html.escape(result.registrar or 'indisponivel')}",
                    f"Status: {html.escape(', '.join(result.statuses) if result.statuses else 'indisponivel')}",
                    f"Criado em: {html.escape(_format_datetime(result.created_at, self._tzinfo))}",
                    f"Atualizado em: {html.escape(_format_datetime(result.updated_at, self._tzinfo))}",
                    f"Expira em: {html.escape(_format_datetime(result.expires_at, self._tzinfo))}",
                    f"NS: {html.escape(', '.join(result.nameservers) if result.nameservers else 'indisponivel')}",
                ]
            await self._reply_chunks(message, "\n".join(lines))
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/whois",
                context=automation_context,
                status="ok",
                severity="info",
                payload={"domain": result.domain},
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /whois: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/whois",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )

    async def cep_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/cep")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        raw_cep = " ".join(context.args).strip()
        if not raw_cep:
            await message.reply_text("Uso: /cep 01001000")
            return
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/cep",
            context=automation_context,
            status="start",
            severity="info",
            payload={"cep": raw_cep},
        )
        try:
            info = await self._cep_provider.lookup(raw_cep)
            lines = [
                "<b>CEP</b>",
                f"CEP: {html.escape(info.cep)}",
                f"Endereco: {html.escape(info.logradouro or '-')}",
                f"Complemento: {html.escape(info.complemento or '-')}",
                f"Bairro: {html.escape(info.bairro or '-')}",
                f"Cidade/UF: {html.escape((info.localidade or '-') + '/' + (info.uf or '-'))}",
                f"IBGE: {html.escape(info.ibge or '-')}",
            ]
            await self._reply_chunks(message, "\n".join(lines))
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/cep",
                context=automation_context,
                status="ok",
                severity="info",
                payload={"cep": info.cep},
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /cep: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/cep",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )

    async def ping_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/ping")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        target = " ".join(context.args).strip()
        if not target:
            await message.reply_text("Uso: /ping host")
            return
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/ping",
            context=automation_context,
            status="start",
            severity="info",
            payload={"host": target},
        )
        try:
            diag = await self._network_provider.run(target)
            ping_status = "OK" if diag.ping.ok else "FALHA"
            trace_status = "OK" if diag.traceroute.ok else "FALHA"
            ping_stats = (
                f"loss={diag.ping.packet_loss_pct}% "
                f"min/med/max={diag.ping.min_ms}/{diag.ping.avg_ms}/{diag.ping.max_ms}ms"
            )
            hops = diag.traceroute.hops[: self._settings.traceroute_max_hops]
            lines = [
                "<b>Diagnostico de Rede</b>",
                f"Host: <b>{html.escape(diag.host)}</b>",
                f"Ping: {ping_status} | {html.escape(ping_stats)}",
                f"Traceroute: {trace_status}",
            ]
            if hops:
                lines.append("<b>Hops</b>")
                for hop in hops:
                    lines.append(html.escape(hop))
            if diag.ping.error:
                lines.append(f"Erro ping: {html.escape(diag.ping.error)}")
            if diag.traceroute.error:
                lines.append(f"Erro traceroute: {html.escape(diag.traceroute.error)}")
            await self._reply_chunks(message, "\n".join(lines))
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/ping",
                context=automation_context,
                status="ok",
                severity="info" if diag.ping.ok and diag.traceroute.ok else "alerta",
                payload={"host": diag.host, "ping_ok": diag.ping.ok, "trace_ok": diag.traceroute.ok},
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /ping: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/ping",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )

    async def ssl_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/ssl")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        target = " ".join(context.args).strip()
        if not target:
            await message.reply_text("Uso: /ssl dominio.com ou /ssl dominio.com:443")
            return
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/ssl",
            context=automation_context,
            status="start",
            severity="info",
            payload={"target": target},
        )
        try:
            info = await self._ssl_provider.check(target)
            lines = [
                "<b>SSL Check</b>",
                f"Host: <b>{html.escape(info.host)}</b>",
                f"Porta: {info.port}",
                f"Subject CN: {html.escape(info.subject_cn or 'indisponivel')}",
                f"Issuer CN: {html.escape(info.issuer_cn or 'indisponivel')}",
                f"Expira em: {html.escape(_format_datetime(info.not_after, self._tzinfo))}",
                f"Dias restantes: <b>{info.days_remaining}</b>",
                f"Severidade: <b>{html.escape(info.severity.upper())}</b>",
            ]
            await self._reply_chunks(message, "\n".join(lines))
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/ssl",
                context=automation_context,
                status="ok",
                severity=info.severity,
                payload={"host": info.host, "days_remaining": info.days_remaining},
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /ssl: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/ssl",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )

    async def voips_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        prepared = await self._prepare_command(update, command="/voips")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/voips",
            context=automation_context,
            status="start",
            severity="info",
            payload=None,
        )
        ami_transport = self._issabel_provider.transport_name()
        ami_endpoint = self._issabel_provider.endpoint_label()
        self._record_audit(
            trace_id=trace_id,
            event_type="ami_query_start",
            command="/voips",
            context=automation_context,
            status="start",
            severity="info",
            payload={"transport": ami_transport, "endpoint": ami_endpoint},
        )
        try:
            peers = await self._issabel_provider.list_connected_voips()
            lines = [
                "<b>VoIPs conectados (SIP)</b>",
                f"Trace: <code>{html.escape(trace_id)}</code>",
                f"Total: <b>{len(peers)}</b>",
            ]
            if not peers:
                lines.append("Sem ramais conectados.")
            else:
                for peer in peers:
                    addr = f"{peer.ip}:{peer.port}" if peer.port is not None else peer.ip
                    line = f"- {html.escape(peer.name)}: {html.escape(addr)}"
                    if peer.status:
                        line += f" | {html.escape(peer.status)}"
                    lines.append(line)
            await self._reply_chunks(message, "\n".join(lines))
            self._record_audit(
                trace_id=trace_id,
                event_type="ami_query_end",
                command="/voips",
                context=automation_context,
                status="ok",
                severity="info",
                payload={"transport": ami_transport, "peer_count": len(peers)},
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voips",
                context=automation_context,
                status="ok",
                severity="info",
                payload={"count": len(peers)},
            )
        except ValueError:
            await message.reply_text(
                "ISSABEL AMI nao configurado. Configure "
                "ISSABEL_AMI_RAWMAN_URL ou ISSABEL_AMI_HOST + usuario/secret."
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="ami_query_end",
                command="/voips",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={
                    "transport": ami_transport,
                    "error": "not_configured",
                    "phase": "connect",
                },
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voips",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": "not_configured"},
            )
        except AmiError as exc:
            await message.reply_text(f"Falha no /voips: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="ami_query_end",
                command="/voips",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={
                    "transport": ami_transport,
                    "error": str(exc),
                    "phase": self._detect_ami_phase(str(exc)),
                },
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voips",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /voips: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="ami_query_end",
                command="/voips",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={
                    "transport": ami_transport,
                    "error": str(exc),
                    "phase": self._detect_ami_phase(str(exc)),
                },
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voips",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )

    async def voip_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        prepared = await self._prepare_command(update, command="/voip")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/voip",
            context=automation_context,
            status="start",
            severity="info",
            payload=None,
        )
        try:
            result = await self._voip_provider.run_once()
            await self._reply_chunks(message, self._build_voip_message(result))
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voip",
                context=automation_context,
                status="ok" if result.ok else "error",
                severity=(
                    "critico"
                    if not result.ok
                    else (
                        "alerta"
                        if (
                            (
                                isinstance(result.summary, dict)
                                and bool(result.summary.get("deviation_alert"))
                            )
                            or (
                            result.setup_latency_ms is not None
                            and result.setup_latency_ms > self._settings.voip_latency_alert_ms
                            )
                        )
                        else "info"
                    )
                ),
                payload={
                    "target_number": result.target_number,
                    "setup_latency_ms": result.setup_latency_ms,
                    "sip_final_code": result.sip_final_code,
                    "error": result.error,
                    "category": result.category,
                    "deviation_alert": (
                        bool(result.summary.get("deviation_alert"))
                        if isinstance(result.summary, dict)
                        else False
                    ),
                },
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /voip: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voip",
                context=automation_context,
                status="error",
                severity="critico",
                payload={"error": str(exc)},
            )

    def _build_voip_message(self, result) -> str:
        started = _format_datetime(_parse_iso_datetime(result.started_at_utc), self._tzinfo)
        finished = _format_datetime(_parse_iso_datetime(result.finished_at_utc), self._tzinfo)
        lines = [
            "<b>VoIP Probe</b>",
            f"Destino: <b>{html.escape(result.target_number)}</b>",
            f"Status: <b>{'OK' if result.ok else 'FALHA'}</b>",
            f"Chamada completada: {'sim' if result.completed_call else 'nao'}",
            f"Sem problemas: {'sim' if result.no_issues else 'nao'}",
            (
                f"Latencia setup: {result.setup_latency_ms} ms"
                if result.setup_latency_ms is not None
                else "Latencia setup: indisponivel"
            ),
            f"Duracao total: {result.total_duration_ms} ms",
            (
                f"Codigo SIP final: {result.sip_final_code}"
                if result.sip_final_code is not None
                else "Codigo SIP final: indisponivel"
            ),
            f"Inicio: {html.escape(started)}",
            f"Fim: {html.escape(finished)}",
            f"Erro: {html.escape(result.error or '-')}",
        ]
        lines.extend(self._format_voip_matrix_lines(result))
        failure_human = self._build_voip_failure_human(result)
        if failure_human:
            lines.append(f"Falha: {html.escape(failure_human)}")
        return "\n".join(lines)

    async def voip_logs_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/voip_logs")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        limit = 10
        if context.args:
            try:
                limit = max(1, min(50, int(context.args[0])))
            except ValueError:
                await message.reply_text("Uso: /voip_logs [quantidade]")
                return
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/voip_logs",
            context=automation_context,
            status="start",
            severity="info",
            payload={"limit": limit},
        )
        try:
            rows = await self._voip_provider.list_logs(limit=limit)
            lines = [f"<b>VoIP Logs (ultimos {len(rows)})</b>"]
            if not rows:
                lines.append("Sem registros.")
            for row in rows:
                finished = _format_datetime(
                    _parse_iso_datetime(row.finished_at_utc), self._tzinfo
                )
                status = "OK" if row.ok else "FALHA"
                latency = (
                    f"{row.setup_latency_ms}ms"
                    if row.setup_latency_ms is not None
                    else "-ms"
                )
                sip_code = str(row.sip_final_code) if row.sip_final_code is not None else "-"
                destination = (
                    row.failure_destination_number
                    if row.failure_destination_number
                    else (row.target_number or "-")
                )
                line = (
                    f"{html.escape(finished)} | <b>{status}</b> | "
                    f"lat={html.escape(latency)} | sip={html.escape(sip_code)} | "
                    f"dest={html.escape(destination)}"
                )
                if row.error:
                    line += f" | erro={html.escape(row.error[:260])}"
                if row.failure_stage:
                    line += f" | stage={html.escape(row.failure_stage)}"
                if row.category:
                    line += f" | cat={html.escape(self._voip_category_label(row.category))}"
                if row.reason and (row.reason.strip() != (row.error or "").strip()):
                    line += f" | motivo={html.escape(row.reason[:220])}"
                lines.append(line)
            await self._reply_chunks(message, "\n".join(lines))
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voip_logs",
                context=automation_context,
                status="ok",
                severity="info",
                payload={"limit": limit, "returned": len(rows)},
            )
        except Exception as exc:
            await message.reply_text(f"Falha no /voip_logs: {exc}")
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/voip_logs",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={"error": str(exc)},
            )

    async def note_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/note")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        if not context.args or len(context.args) < 2:
            await message.reply_text(
                "Uso: /note <aba> /<titulo> <texto> ou /note <aba> <texto>"
            )
            return
        raw_tab = context.args[0].strip().lower()
        tab = self._normalize_tab(raw_tab)
        if tab not in {"estudos", "dinheiro", "trabalho", "life", "geral"}:
            await message.reply_text("Aba invalida. Use: estudos, dinheiro, trabalho, life, geral.")
            return
        target_chat_id = self._note_tab_map.get(tab)
        if target_chat_id is None:
            configured = ", ".join(sorted(self._note_tab_map.keys())) or "(nenhuma)"
            await message.reply_text(
                f"NOTE_TAB_CHAT_IDS_JSON sem mapeamento para aba '{tab}'. "
                f"Abas carregadas: {configured}"
            )
            return

        payload = " ".join(context.args[1:]).strip()
        title, body = self._parse_note_payload(payload)
        if not title:
            await message.reply_text("Nota vazia.")
            return
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/note",
            context=automation_context,
            status="start",
            severity="info",
            payload={"tab": tab, "title": title},
        )
        source = update.effective_user
        source_username = source.username if source else None
        created_local = datetime.now(self._tzinfo)
        note_lines = [
            f"<b>/note ({html.escape(tab)})</b>",
            f"Nota: {html.escape(title)}",
        ]
        if body:
            note_lines.append(f"Texto: {html.escape(body)}")
        note_lines.append(
            f"Horario: {html.escape(created_local.strftime('%d/%m/%Y %H:%M'))}"
        )
        try:
            sent = await context.bot.send_message(
                chat_id=target_chat_id,
                text="\n".join(note_lines),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as exc:
            await message.reply_text(
                f"Falha ao enviar para aba '{tab}': {exc}\n"
                "Verifique NOTE_TAB_CHAT_IDS_JSON com IDs reais."
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="command_end",
                command="/note",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={
                    "tab": tab,
                    "target_chat_id": target_chat_id,
                    "error": str(exc),
                },
            )
            return
        note_id = None
        if self._state_store is not None:
            note_id = self._state_store.create_note(
                tab=tab,
                title=title,
                body=body,
                source_chat_id=automation_context.chat_id,
                source_user_id=automation_context.user_id,
                source_username=automation_context.username,
                target_chat_id=target_chat_id,
                telegram_message_id=getattr(sent, "message_id", None),
            )
        await message.reply_text(
            f"Nota salva em {tab}. ID: {note_id if note_id is not None else '-'}"
        )
        self._record_audit(
            trace_id=trace_id,
            event_type="command_end",
            command="/note",
            context=automation_context,
            status="ok",
            severity="info",
            payload={"tab": tab, "note_id": note_id},
        )

    async def lembrete_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/lembrete")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        if not context.args or len(context.args) < 2:
            await message.reply_text("Uso: /lembrete HH:MM texto")
            return
        match = self.TIME_RE.match(context.args[0].strip())
        if not match:
            await message.reply_text("Horario invalido. Use HH:MM (24h).")
            return
        note_text = " ".join(context.args[1:]).strip()
        if not note_text:
            await message.reply_text("Texto do lembrete nao informado.")
            return
        hour = int(match.group(1))
        minute = int(match.group(2))
        now_local = datetime.now(self._tzinfo)
        remind_local = now_local.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if remind_local <= now_local:
            remind_local += timedelta(days=1)
        remind_utc = remind_local.astimezone(timezone.utc)
        reminder_id = None
        if self._state_store is not None and automation_context.chat_id is not None:
            reminder_id = self._state_store.create_reminder(
                chat_id=automation_context.chat_id,
                user_id=automation_context.user_id,
                username=automation_context.username,
                text=note_text,
                remind_at_utc=remind_utc,
                timezone_name=self._settings.bot_timezone,
            )
        await message.reply_text(
            "Lembrete salvo para "
            f"{remind_local.strftime('%d/%m/%Y %H:%M')} (ID {reminder_id if reminder_id is not None else '-'})"
        )
        self._record_audit(
            trace_id=trace_id,
            event_type="command_end",
            command="/lembrete",
            context=automation_context,
            status="ok",
            severity="info",
            payload={"reminder_id": reminder_id, "at": remind_local.isoformat()},
        )

    async def logs_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        prepared = await self._prepare_command(update, command="/logs")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        if self._state_store is None:
            await message.reply_text("Audit log indisponivel.")
            return
        args = getattr(context, "args", []) or []
        limit = 20
        only_error = False
        only_ami = False
        only_voip = False
        if args:
            first = str(args[0]).strip().lower()
            if first in {"erro", "error"}:
                only_error = True
                if len(args) >= 2:
                    try:
                        limit = max(1, min(100, int(args[1])))
                    except ValueError:
                        await message.reply_text(
                            "Uso: /logs [quantidade], /logs erro [quantidade], "
                            "/logs ami [quantidade] ou /logs voip [quantidade]"
                        )
                        return
            elif first == "ami":
                only_ami = True
                if len(args) >= 2:
                    second = str(args[1]).strip().lower()
                    if second in {"erro", "error"}:
                        only_error = True
                        if len(args) >= 3:
                            try:
                                limit = max(1, min(100, int(args[2])))
                            except ValueError:
                                await message.reply_text("Uso: /logs ami [quantidade] ou /logs ami erro [quantidade]")
                                return
                    else:
                        try:
                            limit = max(1, min(100, int(args[1])))
                        except ValueError:
                            await message.reply_text("Uso: /logs ami [quantidade] ou /logs ami erro [quantidade]")
                            return
            elif first == "voip":
                only_voip = True
                if len(args) >= 2:
                    second = str(args[1]).strip().lower()
                    if second in {"erro", "error"}:
                        only_error = True
                        if len(args) >= 3:
                            try:
                                limit = max(1, min(100, int(args[2])))
                            except ValueError:
                                await message.reply_text(
                                    "Uso: /logs voip [quantidade] ou /logs voip erro [quantidade]"
                                )
                                return
                    else:
                        try:
                            limit = max(1, min(100, int(args[1])))
                        except ValueError:
                            await message.reply_text(
                                "Uso: /logs voip [quantidade] ou /logs voip erro [quantidade]"
                            )
                            return
            else:
                try:
                    limit = max(1, min(100, int(args[0])))
                except ValueError:
                    await message.reply_text(
                        "Uso: /logs [quantidade], /logs erro [quantidade], "
                        "/logs ami [quantidade] ou /logs voip [quantidade]"
                    )
                    return
        fetch_limit = 200 if (only_ami or only_voip) else limit
        events = self._state_store.list_audit_events(limit=fetch_limit, only_error=only_error)
        if only_ami:
            events = [
                item
                for item in events
                if str(item.get("event_type") or "").startswith("ami_")
                or str(item.get("command") or "") == "/voips"
            ][:limit]
        if only_voip:
            events = [
                item
                for item in events
                if str(item.get("command") or "") in {"/voip", "/all"}
                or str(item.get("event_type") or "")
                in {"voip_probe_tick", "all_voip_error", "all_voip_ok"}
            ][:limit]
        scope = "erros" if only_error else "eventos"
        if only_ami:
            scope = f"{scope} AMI"
        if only_voip:
            scope = f"{scope} VoIP"
        lines = [f"<b>Audit Log (ultimos {len(events)} {scope})</b>"]
        if not events:
            lines.append("Sem eventos.")
        else:
            for item in events:
                created = _parse_iso_datetime(item.get("created_at"))
                created_label = _format_datetime(created, self._tzinfo)
                event_type = str(item.get("event_type") or "-")
                command = str(item.get("command") or "-")
                status = str(item.get("status") or "-")
                severity = str(item.get("severity") or "-")
                trace = str(item.get("trace_id") or "-")
                lines.append(
                    f"{html.escape(created_label)} | {html.escape(event_type)} | "
                    f"{html.escape(command)} | {html.escape(status)} | "
                    f"{html.escape(severity)} | trace={html.escape(trace)}"
                    + self._format_log_payload_suffix(item.get("payload"))
                )
        await self._reply_chunks(message, "\n".join(lines))
        self._record_audit(
            trace_id=trace_id,
            event_type="command_end",
            command="/logs",
            context=automation_context,
            status="ok",
            severity="info",
            payload={
                "limit": limit,
                "returned": len(events),
                "only_error": only_error,
                "only_ami": only_ami,
                "only_voip": only_voip,
            },
        )

    async def all_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del context
        prepared = await self._prepare_command(update, command="/all")
        if prepared is None:
            return
        message, chat_id, trace_id, automation_context = prepared
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command="/all",
            context=automation_context,
            status="start",
            severity="info",
            payload=None,
        )
        await self._execute_trigger(message, automation_context, "status")
        await self._execute_trigger(message, automation_context, "host")
        await self._execute_voip_in_all(
            message,
            trace_id=trace_id,
            automation_context=automation_context,
        )
        await self._send_reminder_overview(message, chat_id=chat_id)
        self._record_audit(
            trace_id=trace_id,
            event_type="command_end",
            command="/all",
            context=automation_context,
            status="ok",
            severity="info",
            payload=None,
        )

    async def _execute_voip_in_all(
        self,
        message: Message,
        *,
        trace_id: str,
        automation_context: AutomationContext,
    ) -> None:
        # /all aggregates multiple checks; VoIP errors shouldn't block reminders.
        try:
            result = await self._voip_provider.run_once()
            await self._reply_chunks(message, self._build_voip_message(result))
            self._record_audit(
                trace_id=trace_id,
                event_type="all_voip_ok",
                command="/all",
                context=automation_context,
                status="ok",
                severity="info",
                payload={
                    "stage": "voip_in_all",
                    "target_number": result.target_number,
                    "setup_latency_ms": result.setup_latency_ms,
                    "sip_final_code": result.sip_final_code,
                    "ok": result.ok,
                },
            )
        except Exception as exc:
            error_text = str(exc)
            rc = self._extract_rc_from_text(error_text)
            await self._reply_chunks(
                message,
                f"<b>VoIP Probe</b>\nFalha no /voip: {html.escape(error_text)}",
            )
            self._record_audit(
                trace_id=trace_id,
                event_type="all_voip_error",
                command="/all",
                context=automation_context,
                status="error",
                severity="alerta",
                payload={
                    "stage": "voip_in_all",
                    "error": error_text,
                    "rc": rc,
                },
            )

    async def text_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if not update.message or not update.message.text:
            return
        bot_username = context.bot.username.lower() if context.bot.username else None
        text = update.message.text
        if is_status_command(text, bot_username=bot_username):
            await self._run_single_trigger(update, context, trigger="status")
        elif is_host_command(text, bot_username=bot_username):
            await self._run_single_trigger(update, context, trigger="host")
        elif is_health_command(text, bot_username=bot_username):
            await self._run_single_trigger(update, context, trigger="health")
        elif is_all_command(text, bot_username=bot_username):
            await self.all_handler(update, context)

    async def channel_post_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        del update, context
        return

    async def _run_single_trigger(
        self,
        update: Update,
        context: ContextTypes.DEFAULT_TYPE,
        trigger: str,
    ) -> None:
        del context
        prepared = await self._prepare_command(update, command=f"/{trigger}")
        if prepared is None:
            return
        message, _, trace_id, automation_context = prepared
        self._record_audit(
            trace_id=trace_id,
            event_type="command_start",
            command=f"/{trigger}",
            context=automation_context,
            status="start",
            severity="info",
            payload=None,
        )
        await self._execute_trigger(message, automation_context, trigger)
        self._record_audit(
            trace_id=trace_id,
            event_type="command_end",
            command=f"/{trigger}",
            context=automation_context,
            status="ok",
            severity="info",
            payload=None,
        )

    async def _prepare_command(
        self,
        update: Update,
        command: str,
    ) -> tuple[Message, int, str, AutomationContext] | None:
        message = update.effective_message
        chat = update.effective_chat
        if not message or not chat:
            return None
        trace_id = self._new_trace_id()
        if not self._is_allowed_chat(chat.id):
            await self._handle_unauthorized(update, message.text, trace_id)
            await message.reply_text(self.BLOCKED_MESSAGE)
            return None
        automation_context = self._build_context(update, trace_id, command=command)
        if self._state_store is not None and command in {"/voip", "/ping"}:
            cooldown = (
                self._settings.rate_limit_voip_seconds
                if command == "/voip"
                else self._settings.rate_limit_ping_seconds
            )
            rate_key = f"rate:{chat.id}:{command}"
            allowed, retry_after = self._state_store.consume_rate_limit(
                rate_key, cooldown
            )
            if not allowed:
                await message.reply_text(
                    f"Rate limit: aguarde {retry_after}s para usar {command} novamente."
                )
                self._record_audit(
                    trace_id=trace_id,
                    event_type="command_rate_limited",
                    command=command,
                    context=automation_context,
                    status="denied",
                    severity="info",
                    payload={
                        "command": command,
                        "retry_after_seconds": retry_after,
                        "cooldown_seconds": cooldown,
                    },
                )
                return None
        return message, chat.id, trace_id, automation_context

    async def _execute_trigger(
        self,
        message: Message,
        automation_context: AutomationContext,
        trigger: str,
    ) -> None:
        logger.info(
            "trigger requested by chat",
            extra={
                "event": "trigger_request",
                "trace_id": automation_context.trace_id,
                "trigger": trigger,
                "chat_id": automation_context.chat_id,
                "user_id": automation_context.user_id,
                "username": automation_context.username,
                "command": automation_context.command,
            },
        )
        results = await self._orchestrator.run_trigger(trigger, automation_context)
        if not results:
            await message.reply_text(f"Nenhuma automacao registrada para {trigger}.")
            return
        for result in results:
            await self._reply_chunks(message, result.message)

    async def _send_reminder_overview(self, message: Message, chat_id: int) -> None:
        if self._state_store is None:
            await message.reply_text("<b>Lembretes de hoje</b>\nSem lembretes.", parse_mode=ParseMode.HTML)
            await message.reply_text("<b>Lembretes de amanha</b>\nSem lembretes.", parse_mode=ParseMode.HTML)
            return
        today = datetime.now(self._tzinfo).date()
        tomorrow = today + timedelta(days=1)
        today_rows = self._state_store.list_reminders_by_local_date(
            chat_id=chat_id,
            date_local=today,
            timezone_name=self._settings.bot_timezone,
        )
        tomorrow_rows = self._state_store.list_reminders_by_local_date(
            chat_id=chat_id,
            date_local=tomorrow,
            timezone_name=self._settings.bot_timezone,
        )
        await self._reply_chunks(message, self._format_reminder_lines("hoje", today, today_rows))
        await self._reply_chunks(
            message,
            self._format_reminder_lines("amanha", tomorrow, tomorrow_rows),
        )

    def _format_reminder_lines(self, label: str, day, rows: list[dict]) -> str:
        lines = [f"<b>Lembretes de {label} ({day.strftime('%d/%m')})</b>"]
        if not rows:
            lines.append("Sem lembretes.")
            return "\n".join(lines)
        for item in rows:
            remind_at = _parse_iso_datetime(item.get("remind_at_utc"))
            remind_local = (
                remind_at.astimezone(self._tzinfo).strftime("%H:%M")
                if remind_at is not None
                else "--:--"
            )
            sent_at = _parse_iso_datetime(item.get("sent_at_utc"))
            if sent_at is not None:
                sent_local = sent_at.astimezone(self._tzinfo).strftime("%H:%M")
                status = f"[ENVIADO {sent_local}]"
            else:
                status = "[PENDENTE]"
            lines.append(
                f"{remind_local} | {status} {html.escape(str(item.get('text', '')))}"
            )
        return "\n".join(lines)

    async def _reply_chunks(self, message: Message, content: str) -> None:
        for chunk in split_message(content):
            await message.reply_text(
                chunk,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )

    async def _handle_unauthorized(
        self,
        update: Update,
        command_text: str | None,
        trace_id: str,
    ) -> None:
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        chat_id = getattr(chat, "id", None)
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        logger.warning(
            "unauthorized access attempt",
            extra={
                "event": "unauthorized_attempt",
                "trace_id": trace_id,
                "chat_id": chat_id,
                "user_id": user_id,
                "username": username,
                "command": command_text or "",
            },
        )
        if self._state_store is not None:
            self._state_store.record_unauthorized_attempt(
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                command_text=command_text,
                trace_id=trace_id,
            )
            self._state_store.record_audit_event(
                trace_id=trace_id,
                event_type="unauthorized_attempt",
                command=command_text,
                chat_id=chat_id,
                user_id=user_id,
                username=username,
                status="denied",
                severity="alerta",
                payload=None,
            )

    def _build_context(
        self,
        update: Update,
        trace_id: str,
        command: str,
    ) -> AutomationContext:
        chat = getattr(update, "effective_chat", None)
        user = getattr(update, "effective_user", None)
        chat_id = getattr(chat, "id", None)
        user_id = getattr(user, "id", None)
        username = getattr(user, "username", None)
        return AutomationContext(
            settings=self._settings,
            trace_id=trace_id,
            chat_id=chat_id,
            user_id=user_id,
            username=username,
            command=command,
        )

    def _record_audit(
        self,
        *,
        trace_id: str | None,
        event_type: str,
        command: str,
        context: AutomationContext,
        status: str,
        severity: str,
        payload: dict[str, Any] | None,
    ) -> None:
        if self._state_store is None:
            return
        self._state_store.record_audit_event(
            trace_id=trace_id,
            event_type=event_type,
            command=command,
            chat_id=context.chat_id,
            user_id=context.user_id,
            username=context.username,
            status=status,
            severity=severity,
            payload=payload,
        )

    def _normalize_tab(self, raw_tab: str) -> str:
        normalized = raw_tab.strip().lower()
        return self.TAB_ALIAS.get(normalized, normalized)

    @staticmethod
    def _parse_note_payload(payload: str) -> tuple[str, str]:
        text = payload.strip()
        if not text:
            return "", ""
        first, *rest = text.split(maxsplit=1)
        if first.startswith("/") and len(first) > 1:
            title = first[1:].strip()
            body = rest[0].strip() if rest else ""
            return title, body
        return text, ""

    @staticmethod
    def _new_trace_id() -> str:
        return uuid.uuid4().hex[:12]

    def _is_allowed_chat(self, chat_id: int) -> bool:
        allowed_chat_id = self._settings.telegram_allowed_chat_id
        if allowed_chat_id is None:
            return False
        return chat_id == allowed_chat_id

    def _format_voip_matrix_lines(self, result) -> list[str]:
        destinations = result.destinations if isinstance(result.destinations, list) else []
        if not destinations:
            return []
        lines = ["<b>Matriz</b>"]
        for item in destinations:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "-")
            number = str(item.get("number") or "-")
            status = "OK" if bool(item.get("no_issues")) else "FALHA"
            latency_value = None
            try:
                if item.get("setup_latency_ms") is not None:
                    latency_value = int(item.get("setup_latency_ms"))
            except (TypeError, ValueError):
                latency_value = None
            latency = (
                f"{latency_value}ms"
                if latency_value is not None
                else "-ms"
            )
            options = item.get("options") if isinstance(item.get("options"), dict) else {}
            invite = item.get("invite") if isinstance(item.get("invite"), dict) else {}
            opt_ok = bool(options.get("ok")) if options else False
            opt_code = options.get("sip_status_text") or options.get("sip_final_code") or "-"
            opt_label = f"OK(sip={opt_code})" if opt_ok else f"WARN(sip={opt_code})"
            inv_ok = bool(invite.get("ok")) if invite else False
            inv_code = invite.get("sip_status_text") or invite.get("sip_final_code") or "-"
            inv_label = str(inv_code) if inv_ok else f"FAIL({inv_code})"

            category = self._voip_category_label(str(item.get("category") or ""))
            row = (
                f"- {html.escape(key)} {html.escape(number)} | {status} | "
                f"opt={html.escape(opt_label)} | inv={html.escape(inv_label)} | "
                f"lat={html.escape(latency)}"
            )
            if category != "-":
                row += f" | cat={html.escape(category)}"
            lines.append(row)
        summary = result.summary if isinstance(result.summary, dict) else {}
        if summary:
            total = summary.get("total_destinations")
            failed = summary.get("failed_destinations")
            success = summary.get("successful_destinations")
            if total is not None and failed is not None and success is not None:
                lines.append(f"Resumo: {success}/{total} OK ({failed} falhas)")
        return lines

    def _build_voip_failure_human(self, result) -> str | None:
        destinations = result.destinations if isinstance(result.destinations, list) else []
        failed_items = [item for item in destinations if isinstance(item, dict) and not bool(item.get("no_issues"))]
        if not failed_items:
            return None
        ordered: list[dict] = []
        for key in ("target", "external", "self"):
            for item in failed_items:
                if str(item.get("key") or "") == key:
                    ordered.append(item)
        for item in failed_items:
            if item not in ordered:
                ordered.append(item)
        selected = ordered[0]
        number = str(selected.get("number") or result.target_number or "-")
        category = str(selected.get("category") or result.category or "")
        reason = str(selected.get("reason") or result.reason or selected.get("error") or result.error or "")
        sip_code = selected.get("sip_final_code")
        sip_text = f"{sip_code}" if sip_code is not None else "sem codigo SIP"
        if category == "rota_permissao" and "permissao de discagem" in reason.lower():
            return reason
        if category == "rota_permissao":
            return f"rota/permissao para {number} ({sip_text})."
        if category == "auth":
            return f"autenticacao SIP para {number} ({sip_text})."
        if category == "rede_timeout":
            return f"rede/timeout para {number}."
        if reason:
            return reason
        return f"falha desconhecida para {number} ({sip_text})."

    @staticmethod
    def _voip_category_label(category: str | None) -> str:
        normalized = (category or "").strip().lower()
        if not normalized:
            return "-"
        if normalized == "auth":
            return "auth"
        if normalized == "rota_permissao":
            return "rota/permissao"
        if normalized == "rede_timeout":
            return "rede/timeout"
        return normalized

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

    @staticmethod
    def _extract_rc_from_text(error_text: str | None) -> int | None:
        text = (error_text or "").strip()
        if not text:
            return None
        match = re.search(r"rc=(-?\d+)", text)
        if not match:
            return None
        try:
            return int(match.group(1))
        except ValueError:
            return None

    @staticmethod
    def _format_log_payload_suffix(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        suffix_parts: list[str] = []
        error_text = str(payload.get("error") or "").strip()
        if error_text:
            suffix_parts.append(f"detalhe={html.escape(error_text[:120])}")
        transport = str(payload.get("transport") or "").strip()
        phase = str(payload.get("phase") or "").strip()
        peer_count = payload.get("peer_count")
        rc = payload.get("rc")
        stage = str(payload.get("stage") or "").strip()
        sip_code = payload.get("sip_final_code")
        ami_parts: list[str] = []
        if transport:
            ami_parts.append(transport)
        if phase:
            ami_parts.append(phase)
        if peer_count is not None:
            ami_parts.append(f"peers={peer_count}")
        if ami_parts:
            suffix_parts.append(f"ami={html.escape(' '.join(ami_parts))}")
        if rc is not None:
            suffix_parts.append(f"rc={html.escape(str(rc))}")
        if stage:
            suffix_parts.append(f"stage={html.escape(stage)}")
        if sip_code is not None:
            suffix_parts.append(f"sip={html.escape(str(sip_code))}")
        if not suffix_parts:
            return ""
        return " | " + " | ".join(suffix_parts)


def _resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            return timezone(timedelta(hours=-3))
        return timezone.utc


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_datetime(value: datetime | None, tzinfo) -> str:
    if value is None:
        return "indisponivel"
    return value.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M")
