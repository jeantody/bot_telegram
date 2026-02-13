from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import html
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.host_status_provider import (
    HostingerReport,
    HostIncident,
    HostIncidentUpdate,
    HostMaintenance,
    HostStatusProvider,
    LocawebReport,
    MetaOrgReport,
    MetaReport,
    UmbrellaReport,
    WebsiteChecksReport,
)


def _resolve_timezone(timezone_name: str) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            return timezone(timedelta(hours=-3))
        return timezone.utc


class StatusHostAutomation:
    name = "status_host"
    trigger = "host"

    def __init__(self, provider: HostStatusProvider, translator=None) -> None:
        self._provider = provider
        self._translator = translator
        self._translation_cache: dict[str, str] = {}

    async def run(self, context: AutomationContext) -> AutomationResult:
        settings = context.settings
        snapshot = await self._provider.fetch_snapshot(
            locaweb_components_url=settings.locaweb_components_url,
            locaweb_incidents_url=settings.locaweb_incidents_url,
            meta_orgs_url=settings.meta_orgs_url,
            meta_outages_url_template=settings.meta_outages_url_template,
            meta_metrics_url_template=settings.meta_metrics_url_template,
            umbrella_summary_url=settings.umbrella_summary_url,
            umbrella_incidents_url=settings.umbrella_incidents_url,
            hostinger_summary_url=settings.hostinger_summary_url,
            hostinger_components_url=settings.hostinger_components_url,
            hostinger_incidents_url=settings.hostinger_incidents_url,
            hostinger_status_page_url=settings.hostinger_status_page_url,
        )
        self._translation_cache = {}
        tzinfo = _resolve_timezone(settings.host_report_timezone)
        lines = ["<b>Host Monitoring</b>"]
        umbrella_section = await self._format_umbrella(snapshot.umbrella, tzinfo)
        sections = [
            self._format_locaweb(snapshot.locaweb, tzinfo),
            self._format_meta(snapshot.meta, tzinfo),
            self._format_hostinger(snapshot.hostinger, tzinfo),
            self._format_websites(snapshot.websites),
            umbrella_section,
        ]
        for section in sections:
            if not section:
                continue
            lines.append("")
            lines.extend(section)
        return AutomationResult(
            title="Host",
            message="\n".join(lines).strip(),
            source_label="Locaweb | Meta | Cisco Umbrella | Hostinger | Site Checks",
            generated_at=context.utc_now().astimezone(timezone.utc),
            ok=True,
        )

    def _format_locaweb(
        self, report: LocawebReport, tzinfo: timezone | ZoneInfo
    ) -> list[str]:
        if report.error:
            return [
                "<b>Locaweb</b>",
                f"Falha ao consultar fonte: {html.escape(report.error)}"
            ]

        lines: list[str] = []
        for component, status in report.component_statuses.items():
            if status.lower() == "operational":
                continue
            if not lines:
                lines.append("<b>Locaweb</b>")
                lines.append("Saude: ALERTA")
            safe_component = html.escape(component)
            safe_status = html.escape(status)
            lines.append(f"- {safe_component}: {safe_status}")
        if not lines:
            lines = ["<b>Locaweb</b>", "Saude: OK"]
        if report.incidents_today and not lines:
            lines.append("<b>Locaweb</b>")
        lines.extend(
            self._format_incidents("Incidentes de hoje", report.incidents_today, tzinfo)
        )
        return lines

    def _format_hostinger(
        self, report: HostingerReport, tzinfo: timezone | ZoneInfo
    ) -> list[str]:
        lines = ["<b>Hostinger</b>"]
        if report.error:
            lines.append(f"Falha ao consultar fonte: {html.escape(report.error)}")
            return lines

        lines.append("Saude: OK" if report.overall_ok else "Saude: ALERTA")
        for component, status in report.vps_components_non_operational.items():
            lines.append(f"- {html.escape(component)}: {html.escape(status)}")
        lines.extend(
            self._format_incidents(
                "Incidentes (hoje/ontem com impacto)",
                report.incidents_active_recent,
                tzinfo,
                title_bold=True,
                max_body_chars=170,
            )
        )
        if report.upcoming_maintenances:
            lines.append("<b>Manutencoes futuras</b>")
            for item in report.upcoming_maintenances:
                lines.append(self._format_maintenance(item, tzinfo))
        return lines

    def _format_websites(self, report: WebsiteChecksReport) -> list[str]:
        total = len(report.checks)
        up_count = sum(1 for check in report.checks if check.is_up)
        lines = ["<b>Sites Monitorados</b>", f"Sites OK: {up_count}/{total}"]
        for check in report.checks:
            if check.is_up:
                continue
            lines.append(f"- {html.escape(check.label)}: DOWN")
        return lines

    def _format_meta(self, report: MetaReport, tzinfo: timezone | ZoneInfo) -> list[str]:
        lines = ["<b>Meta</b>"]
        if report.error:
            lines.append(
                f"Falha ao consultar fonte: {html.escape(report.error)}"
            )
            return lines

        problem_org_lines: list[str] = []
        for org in report.orgs:
            if org.statuses and all(
                self._is_no_known_issue(status) for status in org.statuses
            ):
                continue
            problem_org_lines.append(self._format_meta_org(org))

        if problem_org_lines:
            lines.append("Saude: ALERTA")
            lines.extend(problem_org_lines)

        if report.whatsapp_availability is None:
            lines.append("- WhatsApp Availability: indisponivel no momento")
        else:
            lines.append(
                f"- WhatsApp Availability: {report.whatsapp_availability:.2f}%"
            )

        if report.whatsapp_latency_p90_ms is None or report.whatsapp_latency_p99_ms is None:
            lines.append("- WhatsApp Latency: indisponivel no momento")
        else:
            lines.append(
                "- WhatsApp Latency: "
                f"P90 {report.whatsapp_latency_p90_ms:.0f} ms, "
                f"P99 {report.whatsapp_latency_p99_ms:.0f} ms (last 31 days)"
            )

        lines.extend(
            self._format_incidents(
                "Incidentes de hoje (WhatsApp Business API)",
                report.incidents_today,
                tzinfo,
            )
        )
        return lines

    async def _format_umbrella(
        self, report: UmbrellaReport, tzinfo: timezone | ZoneInfo
    ) -> list[str]:
        if report.error:
            title = await self._translate_text("Cisco Umbrella")
            return [
                f"<b>{html.escape(title)}</b>",
                html.escape(
                    await self._translate_text(
                        f"Falha ao consultar fonte: {report.error}"
                    )
                ),
            ]

        lines: list[str] = []
        for component, human in report.component_statuses_human.items():
            raw = report.component_statuses.get(component, "unknown")
            if raw.lower() == "operational" and human.lower() == "normal":
                continue
            if not lines:
                title = await self._translate_text("Cisco Umbrella")
                lines.append(f"<b>{html.escape(title)}</b>")
                lines.append(html.escape(await self._translate_text("Saude: ALERTA")))
            safe_component = html.escape(await self._translate_text(component))
            safe_human = html.escape(await self._translate_text(human))
            safe_raw = html.escape(await self._translate_text(raw))
            lines.append(f"- {safe_component}: {safe_human} ({safe_raw})")
        if report.incidents_active_or_today and not lines:
            title = await self._translate_text("Cisco Umbrella")
            lines.append(f"<b>{html.escape(title)}</b>")
        lines.extend(
            await self._format_incidents_translated(
                await self._translate_text("Incidentes ativos/hoje"),
                report.incidents_active_or_today,
                tzinfo,
                title_bold=True,
                max_body_chars=170,
            )
        )
        return lines

    def _format_maintenance(
        self, maintenance: HostMaintenance, tzinfo: timezone | ZoneInfo
    ) -> str:
        name = html.escape(maintenance.name)
        scheduled_for = self._format_datetime(maintenance.scheduled_for, tzinfo)
        scheduled_until = self._format_datetime(maintenance.scheduled_until, tzinfo)
        return (
            f"- {name} | inicio: {html.escape(scheduled_for)} | "
            f"fim: {html.escape(scheduled_until)}"
        )

    @staticmethod
    def _format_meta_org(org: MetaOrgReport) -> str:
        state = "OK" if org.all_no_known_issues else "ALERTA"
        statuses = ", ".join(html.escape(status) for status in org.statuses) if org.statuses else "unknown"
        return f"- {html.escape(org.display_name)}: {state} ({statuses})"

    def _format_incidents(
        self,
        title: str,
        incidents: list[HostIncident],
        tzinfo: timezone | ZoneInfo,
        title_bold: bool = False,
        max_body_chars: int | None = None,
    ) -> list[str]:
        if not incidents:
            return []

        wrapper_start = "<b>" if title_bold else "<i>"
        wrapper_end = "</b>" if title_bold else "</i>"
        lines = [f"{wrapper_start}{html.escape(title)}{wrapper_end}"]
        for incident in incidents:
            lines.extend(
                self._format_single_incident(
                    incident=incident,
                    tzinfo=tzinfo,
                    max_body_chars=max_body_chars,
                )
            )
        return lines

    def _format_single_incident(
        self,
        incident: HostIncident,
        tzinfo: timezone | ZoneInfo,
        max_body_chars: int | None = None,
    ) -> list[str]:
        started = self._format_datetime(incident.started_at, tzinfo)
        lines = [
            f"- {html.escape(incident.title)}",
            f"  Status: {html.escape(incident.status)}",
            f"  Inicio: {html.escape(started)}",
        ]
        for update in incident.updates:
            lines.extend(
                self._format_incident_update(
                    update=update,
                    tzinfo=tzinfo,
                    max_body_chars=max_body_chars,
                )
            )
        return lines

    def _format_incident_update(
        self,
        update: HostIncidentUpdate,
        tzinfo: timezone | ZoneInfo,
        max_body_chars: int | None = None,
    ) -> list[str]:
        raw_status = update.status if update.status else "Unknown"
        status = html.escape(raw_status) or "Unknown"
        display_at = self._format_datetime(update.display_at, tzinfo)
        raw_body = update.body if update.body else "Sem detalhes."
        if max_body_chars is not None:
            raw_body = self._truncate_chars(raw_body, max_body_chars)
        body_lines = self._truncate_lines(raw_body, max_lines=3)
        body_lines = [f"    {html.escape(line)}" for line in body_lines]
        return [f"  - {status} | {display_at}", *body_lines]

    async def _format_incidents_translated(
        self,
        title: str,
        incidents: list[HostIncident],
        tzinfo: timezone | ZoneInfo,
        title_bold: bool = False,
        max_body_chars: int | None = None,
    ) -> list[str]:
        if not incidents:
            return []
        wrapper_start = "<b>" if title_bold else "<i>"
        wrapper_end = "</b>" if title_bold else "</i>"
        lines = [f"{wrapper_start}{html.escape(title)}{wrapper_end}"]
        for incident in incidents:
            lines.extend(
                await self._format_single_incident_translated(
                    incident=incident,
                    tzinfo=tzinfo,
                    max_body_chars=max_body_chars,
                )
            )
        return lines

    async def _format_single_incident_translated(
        self,
        incident: HostIncident,
        tzinfo: timezone | ZoneInfo,
        max_body_chars: int | None = None,
    ) -> list[str]:
        started = self._format_datetime(incident.started_at, tzinfo)
        title = await self._translate_text(incident.title)
        status = await self._translate_text(incident.status)
        status_label = await self._translate_text("Status")
        start_label = await self._translate_text("Inicio")
        lines = [
            f"- {html.escape(title)}",
            f"  {html.escape(status_label)}: {html.escape(status)}",
            f"  {html.escape(start_label)}: {html.escape(started)}",
        ]
        for update in incident.updates:
            lines.extend(
                await self._format_incident_update_translated(
                    update=update,
                    tzinfo=tzinfo,
                    max_body_chars=max_body_chars,
                )
            )
        return lines

    async def _format_incident_update_translated(
        self,
        update: HostIncidentUpdate,
        tzinfo: timezone | ZoneInfo,
        max_body_chars: int | None = None,
    ) -> list[str]:
        raw_status = update.status if update.status else "Unknown"
        raw_status = await self._translate_text(raw_status)
        status = html.escape(raw_status) or "Unknown"
        display_at = self._format_datetime(update.display_at, tzinfo)
        raw_body = update.body if update.body else "Sem detalhes."
        if max_body_chars is not None:
            raw_body = self._truncate_chars(raw_body, max_body_chars)
        raw_body = await self._translate_text(raw_body)
        body_lines = self._truncate_lines(raw_body, max_lines=3)
        body_lines = [f"    {html.escape(line)}" for line in body_lines]
        return [f"  - {status} | {display_at}", *body_lines]

    @staticmethod
    def _truncate_lines(text: str, max_lines: int) -> list[str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return ["Sem detalhes."]
        if len(lines) <= max_lines:
            return lines
        return lines[: max_lines - 1] + [f"{lines[max_lines - 1]} ..."]

    @staticmethod
    def _truncate_chars(text: str, max_chars: int) -> str:
        compact = " ".join(part.strip() for part in text.splitlines() if part.strip())
        if len(compact) <= max_chars:
            return compact
        return compact[:max_chars].rstrip()

    @staticmethod
    def _is_no_known_issue(status: str) -> bool:
        return status.strip().lower() == "no known issues"

    async def _translate_text(self, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            return text
        cached = self._translation_cache.get(normalized)
        if cached is not None:
            return cached
        translator = self._get_translator()
        if translator is None:
            self._translation_cache[normalized] = text
            return text
        try:
            translated = translator.translate(normalized, dest="pt")
            if asyncio.iscoroutine(translated):
                translated = await translated
            translated_text = getattr(translated, "text", "") or text
        except Exception:
            translated_text = text
        self._translation_cache[normalized] = translated_text
        return translated_text

    def _get_translator(self):
        if self._translator is not None:
            return self._translator
        try:
            from googletrans import Translator
        except Exception:
            return None
        self._translator = Translator()
        return self._translator

    @staticmethod
    def _format_datetime(
        dt: datetime | None, tzinfo: timezone | ZoneInfo
    ) -> str:
        if dt is None:
            return "horario indisponivel"
        return dt.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M")
