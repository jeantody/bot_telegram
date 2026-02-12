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
        lines = [
            "<b>Host Monitoring</b>",
            "",
            *self._format_locaweb(snapshot.locaweb, tzinfo),
            "",
            *self._format_meta(snapshot.meta, tzinfo),
            "",
            *self._format_umbrella(snapshot.umbrella, tzinfo),
        ]
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
        lines = ["<b>Locaweb</b>"]
        if report.error:
            lines.append(
                f"Falha ao consultar fonte: {html.escape(report.error)}"
            )
            return lines

        lines.append(f"Saude: {'OK' if report.all_operational else 'ALERTA'}")
        for component, status in report.component_statuses.items():
            safe_component = html.escape(component)
            safe_status = html.escape(status)
            lines.append(f"- {safe_component}: {safe_status}")
        lines.extend(self._format_incidents("Incidentes de hoje", report.incidents_today, tzinfo))
        return lines

    def _format_meta(self, report: MetaReport, tzinfo: timezone | ZoneInfo) -> list[str]:
        lines = ["<b>Meta</b>"]
        if report.error:
            lines.append(
                f"Falha ao consultar fonte: {html.escape(report.error)}"
            )
            return lines

        all_ok = len(report.orgs) > 0 and all(item.all_no_known_issues for item in report.orgs)
        lines.append(f"Saude: {'OK' if all_ok else 'ALERTA'}")
        for org in report.orgs:
            lines.append(self._format_meta_org(org))

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
        lines = ["<b>Cisco Umbrella</b>"]
        if report.error:
            lines.append(
                f"Falha ao consultar fonte: {html.escape(report.error)}"
            )
            return lines

        lines.append(f"Saude: {'OK' if report.all_operational else 'ALERTA'}")
        for component, human in report.component_statuses_human.items():
            raw = report.component_statuses.get(component, "unknown")
            safe_component = html.escape(component)
            safe_human = html.escape(human)
            safe_raw = html.escape(raw)
            lines.append(f"- {safe_component}: {safe_human} ({safe_raw})")
        lines.extend(
            self._format_incidents(
                "Incidentes ativos/hoje",
                report.incidents_active_or_today,
                tzinfo,
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
    ) -> list[str]:
        if not incidents:
            return []

        lines = [f"<i>{html.escape(title)}</i>"]
        for incident in incidents:
            lines.extend(self._format_single_incident(incident, tzinfo))
        return lines

    def _format_single_incident(
        self, incident: HostIncident, tzinfo: timezone | ZoneInfo
    ) -> list[str]:
        started = self._format_datetime(incident.started_at, tzinfo)
        lines = [
            f"- {html.escape(incident.title)}",
            f"  Status: {html.escape(incident.status)}",
            f"  Inicio: {started}",
        ]
        for update in incident.updates:
            lines.extend(self._format_incident_update(update, tzinfo))
        return lines

    def _format_incident_update(
        self, update: HostIncidentUpdate, tzinfo: timezone | ZoneInfo
    ) -> list[str]:
        status = html.escape(update.status) or "Unknown"
        display_at = self._format_datetime(update.display_at, tzinfo)
        body = html.escape(update.body) if update.body else "Sem detalhes."
        return [f"  - {status} | {display_at}", f"    {body}"]

    @staticmethod
    def _format_datetime(
        dt: datetime | None, tzinfo: timezone | ZoneInfo
    ) -> str:
        if dt is None:
            return "horario indisponivel"
        return dt.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M")
