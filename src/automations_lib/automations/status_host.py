from __future__ import annotations

from datetime import datetime, timedelta, timezone
import html
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.host_status_provider import (
    HostIncident,
    HostIncidentUpdate,
    HostStatusProvider,
    LocawebReport,
    MetaOrgReport,
    MetaReport,
    UmbrellaReport,
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

    def __init__(self, provider: HostStatusProvider) -> None:
        self._provider = provider

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
        )
        tzinfo = _resolve_timezone(settings.host_report_timezone)
        lines = ["<b>Host Monitoring</b>"]
        sections = [
            self._format_locaweb(snapshot.locaweb, tzinfo),
            self._format_meta(snapshot.meta, tzinfo),
            self._format_umbrella(snapshot.umbrella, tzinfo),
        ]
        for section in sections:
            if not section:
                continue
            lines.append("")
            lines.extend(section)
        return AutomationResult(
            title="Host",
            message="\n".join(lines).strip(),
            source_label="Locaweb | Meta | Cisco Umbrella",
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

    def _format_umbrella(
        self, report: UmbrellaReport, tzinfo: timezone | ZoneInfo
    ) -> list[str]:
        if report.error:
            return [
                "<b>Cisco Umbrella</b>",
                f"Falha ao consultar fonte: {html.escape(report.error)}"
            ]

        lines: list[str] = []
        for component, human in report.component_statuses_human.items():
            raw = report.component_statuses.get(component, "unknown")
            if raw.lower() == "operational" and human.lower() == "normal":
                continue
            if not lines:
                lines.append("<b>Cisco Umbrella</b>")
                lines.append("Saude: ALERTA")
            safe_component = html.escape(component)
            safe_human = html.escape(human)
            safe_raw = html.escape(raw)
            lines.append(f"- {safe_component}: {safe_human} ({safe_raw})")
        if report.incidents_active_or_today and not lines:
            lines.append("<b>Cisco Umbrella</b>")
        lines.extend(
            self._format_incidents(
                "Incidentes ativos/hoje",
                report.incidents_active_or_today,
                tzinfo,
                title_bold=True,
                max_body_chars=170,
            )
        )
        return lines

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
            f"  Inicio: {started}",
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
        status = html.escape(update.status) or "Unknown"
        display_at = self._format_datetime(update.display_at, tzinfo)
        raw_body = update.body if update.body else "Sem detalhes."
        if max_body_chars is not None:
            raw_body = self._truncate_chars(raw_body, max_body_chars)
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

    @staticmethod
    def _format_datetime(
        dt: datetime | None, tzinfo: timezone | ZoneInfo
    ) -> str:
        if dt is None:
            return "horario indisponivel"
        return dt.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M")
