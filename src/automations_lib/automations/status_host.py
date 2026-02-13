from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import html
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

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
    _PT_FALLBACK_EXACT = {
        "resolved": "Resolvido",
        "identified": "Identificado",
        "investigating": "Investigando",
        "monitoring": "Monitorando",
        "status": "Status",
        "inicio": "Inicio",
        "incidentes ativos/hoje": "Incidentes ativos/hoje",
        "cisco umbrella": "Cisco Umbrella",
        "degraded performance": "Desempenho degradado",
        "degraded_performance": "Desempenho degradado",
        "partial outage": "Indisponibilidade parcial",
        "partial_outage": "Indisponibilidade parcial",
        "major outage": "Indisponibilidade critica",
        "major_outage": "Indisponibilidade critica",
    }
    _PT_FALLBACK_REPLACEMENTS = (
        (
            "All policy files have now been processed and the queue is clear.",
            "Todos os arquivos de politica foram processados e a fila esta normal.",
        ),
        (
            "Policy generation is functioning as expected",
            "A geracao de politicas esta funcionando como esperado",
        ),
        (
            "with new policies being applied promptly after configuration",
            "com novas politicas aplicadas rapidamente apos a configuracao",
        ),
        (
            "Policy generation is functioning as expected, with new policies being applied promptly after configuration.",
            "A geracao de politicas esta funcionando como esperado, com novas politicas aplicadas rapidamente apos a configuracao.",
        ),
        (
            "Verification confirms that policies are being delivered efficiently, and all policy translation tests are passing.",
            "A verificacao confirma que as politicas estao sendo entregues com eficiencia e todos os testes de traducao de politicas estao passando.",
        ),
        (
            "We are continuing to process the remaining policy updates",
            "Seguimos processando as atualizacoes de politica restantes",
        ),
        (
            "and are making steady progress toward full resolution",
            "e avancando de forma consistente para a resolucao completa",
        ),
        (
            "We are continuing to process the remaining policy updates and are making steady progress toward full resolution.",
            "Seguimos processando as atualizacoes de politica restantes e avancando de forma consistente para a resolucao completa.",
        ),
        (
            "We are very close to moving into a monitoring state",
            "Estamos muito perto de entrar em monitoramento",
        ),
        (
            "expect normal policy update functionality to be restored soon",
            "e esperamos restaurar em breve o funcionamento normal das atualizacoes de politica",
        ),
        (
            "We are very close to moving into a monitoring state and expect normal policy update functionality to be restored soon.",
            "Estamos muito perto de entrar em monitoramento e esperamos restaurar em breve o funcionamento normal das atualizacoes de politica.",
        ),
        (
            "Further updates will be provided as we confirm resolution.",
            "Novas atualizacoes serao publicadas conforme confirmarmos a resolucao.",
        ),
        (
            "We appreciate your patience and understanding as we work to restore optimal service.",
            "Agradecemos a paciencia e a compreensao enquanto trabalhamos para restaurar o servico ideal.",
        ),
    )

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
            lines.extend(
                self._format_hostinger_maintenances(
                    report.upcoming_maintenances,
                    tzinfo,
                )
            )
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
            title = await self._translate_text("Cisco Umbrella", critical=True)
            return [
                f"<b>{html.escape(title)}</b>",
                html.escape(
                    await self._translate_text(
                        f"Falha ao consultar fonte: {report.error}",
                        critical=True,
                    )
                ),
            ]

        lines: list[str] = []
        for component, human in report.component_statuses_human.items():
            raw = report.component_statuses.get(component, "unknown")
            if raw.lower() == "operational" and human.lower() == "normal":
                continue
            if not lines:
                title = await self._translate_text("Cisco Umbrella", critical=True)
                lines.append(f"<b>{html.escape(title)}</b>")
                lines.append(
                    html.escape(
                        await self._translate_text("Saude: ALERTA", critical=True)
                    )
                )
            safe_component = html.escape(
                await self._translate_text(component, critical=True)
            )
            safe_human = html.escape(await self._translate_text(human, critical=True))
            safe_raw = html.escape(await self._translate_text(raw, critical=True))
            lines.append(f"- {safe_component}: {safe_human} ({safe_raw})")
        if report.incidents_active_or_today and not lines:
            title = await self._translate_text("Cisco Umbrella", critical=True)
            lines.append(f"<b>{html.escape(title)}</b>")
        lines.extend(
            await self._format_incidents_translated(
                await self._translate_text("Incidentes ativos/hoje", critical=True),
                report.incidents_active_or_today,
                tzinfo,
                title_bold=True,
                max_body_chars=170,
            )
        )
        return lines

    def _format_hostinger_maintenances(
        self,
        maintenances: list[HostMaintenance],
        tzinfo: timezone | ZoneInfo,
    ) -> list[str]:
        grouped_pve: dict[tuple[str, str, str], set[str]] = {}
        other_lines: list[str] = []
        for maintenance in maintenances:
            node = self._extract_pve_node_token(maintenance.name)
            scheduled_for = self._format_datetime(maintenance.scheduled_for, tzinfo)
            scheduled_until = self._format_datetime(maintenance.scheduled_until, tzinfo)
            if node:
                base_name = self._normalize_maintenance_base_name(maintenance.name)
                key = (base_name, scheduled_for, scheduled_until)
                grouped_pve.setdefault(key, set()).add(node)
                continue
            short_name = self._normalize_maintenance_base_name(maintenance.name)
            other_lines.append(
                f"- {html.escape(short_name)} | inicio: {html.escape(scheduled_for)} | "
                f"fim: {html.escape(scheduled_until)}"
            )

        lines: list[str] = []
        for base_name, scheduled_for, scheduled_until in sorted(grouped_pve.keys()):
            lines.append(
                f"{html.escape(base_name)} | inicio: {html.escape(scheduled_for)} | "
                f"fim: {html.escape(scheduled_until)}"
            )
            for node in sorted(grouped_pve[(base_name, scheduled_for, scheduled_until)]):
                lines.append(f"- {html.escape(node)}")
        lines.extend(other_lines)
        return lines

    @staticmethod
    def _extract_pve_node_token(name: str) -> str | None:
        match = re.search(r"\bpve-node-?(\d+)\b", name, flags=re.IGNORECASE)
        if not match:
            return None
        return f"pve-node{match.group(1)}"

    def _normalize_maintenance_base_name(self, name: str) -> str:
        cleaned = re.sub(r"\bpve-node-?\d+\b", "", name, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -")
        if not cleaned:
            return "Server maintenance"
        compact = self._truncate_chars(cleaned, max_chars=70)
        lowered = compact.lower()
        if lowered.startswith("server") and lowered.endswith("maintenance"):
            return "Server maintenance"
        return compact

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
        title = await self._translate_text(incident.title, critical=True)
        status = await self._translate_text(incident.status, critical=True)
        status_label = await self._translate_text("Status", critical=True)
        start_label = await self._translate_text("Inicio", critical=True)
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
        raw_status = await self._translate_text(raw_status, critical=True)
        status = html.escape(raw_status) or "Unknown"
        display_at = self._format_datetime(update.display_at, tzinfo)
        raw_body = update.body if update.body else "Sem detalhes."
        raw_body = await self._translate_text(raw_body, critical=True)
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

    async def _translate_text(self, text: str, critical: bool = False) -> str:
        normalized = text.strip()
        if not normalized:
            return text
        cache_key = f"{int(critical)}:{normalized}"
        cached = self._translation_cache.get(cache_key)
        if cached is not None:
            return cached

        fallback_text = self._apply_pt_fallback(normalized)
        translator = self._get_translator()
        if translator is None:
            resolved = text
            if critical:
                resolved = await self._translate_text_via_google_http(normalized)
                if self._looks_untranslated(normalized, resolved):
                    resolved = fallback_text
            self._translation_cache[cache_key] = resolved
            return resolved

        try:
            translated = translator.translate(normalized, dest="pt")
            if asyncio.iscoroutine(translated):
                translated = await translated
            translated_text = (getattr(translated, "text", "") or "").strip() or text
        except Exception:
            translated_text = text

        if critical and self._looks_untranslated(normalized, translated_text):
            if self._can_use_http_translation(translator):
                translated_text = await self._translate_text_via_google_http(normalized)
        if critical and self._looks_untranslated(normalized, translated_text):
            translated_text = fallback_text

        self._translation_cache[cache_key] = translated_text
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

    @classmethod
    def _apply_pt_fallback(cls, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            return text
        exact = cls._PT_FALLBACK_EXACT.get(normalized.lower())
        if exact is not None:
            return exact

        translated = normalized
        for source, target in cls._PT_FALLBACK_REPLACEMENTS:
            translated = re.sub(
                re.escape(source),
                target,
                translated,
                flags=re.IGNORECASE,
            )

        return translated

    @staticmethod
    def _looks_untranslated(original: str, translated: str) -> bool:
        def normalize(value: str) -> str:
            return re.sub(r"[^a-z0-9]+", "", value.lower())

        return normalize(original) == normalize(translated)

    @staticmethod
    def _can_use_http_translation(translator) -> bool:
        module_name = getattr(translator.__class__, "__module__", "")
        return module_name.startswith("googletrans")

    async def _translate_text_via_google_http(self, text: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=8, follow_redirects=True) as client:
                response = await client.get(
                    "https://translate.googleapis.com/translate_a/single",
                    params={
                        "client": "gtx",
                        "sl": "auto",
                        "tl": "pt",
                        "dt": "t",
                        "q": text,
                    },
                )
            response.raise_for_status()
            payload = response.json()
            segments = payload[0] if isinstance(payload, list) and payload else []
            translated = "".join(
                str(item[0]) for item in segments if isinstance(item, list) and item
            ).strip()
            return translated or text
        except Exception:
            return text

    @staticmethod
    def _format_datetime(
        dt: datetime | None, tzinfo: timezone | ZoneInfo
    ) -> str:
        if dt is None:
            return "horario indisponivel"
        return dt.astimezone(tzinfo).strftime("%d/%m/%Y %H:%M")
