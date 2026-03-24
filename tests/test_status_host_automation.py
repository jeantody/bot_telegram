from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.automations_lib.automations.status_host import StatusHostAutomation
from src.automations_lib.models import AutomationContext
from src.automations_lib.providers.host_status_provider import (
    HostingerReport,
    HostMaintenance,
    HostIncident,
    HostIncidentUpdate,
    HostSnapshot,
    LocawebReport,
    MetaOrgReport,
    MetaReport,
    UmbrellaReport,
    WebsiteCheckResult,
    WebsiteChecksReport,
)
from src.config import Settings


@dataclass
class FakeTranslationResult:
    text: str


class FakeTranslator:
    def translate(self, text: str, dest: str = "pt") -> FakeTranslationResult:
        del dest
        return FakeTranslationResult(text=f"PT::{text}")


class FailingTranslator:
    def translate(self, text: str, dest: str = "pt"):
        del text, dest
        raise RuntimeError("translation down")


@dataclass
class FakeProvider:
    snapshot: HostSnapshot

    async def fetch_snapshot(
        self,
        locaweb_components_url: str,
        locaweb_incidents_url: str,
        meta_orgs_url: str,
        meta_outages_url_template: str,
        meta_metrics_url_template: str,
        umbrella_summary_url: str,
        umbrella_incidents_url: str,
        hostinger_summary_url: str,
        hostinger_components_url: str,
        hostinger_incidents_url: str,
        hostinger_status_page_url: str,
    ) -> HostSnapshot:
        del (
            locaweb_components_url,
            locaweb_incidents_url,
            meta_orgs_url,
            meta_outages_url_template,
            meta_metrics_url_template,
            umbrella_summary_url,
            umbrella_incidents_url,
            hostinger_summary_url,
            hostinger_components_url,
            hostinger_incidents_url,
            hostinger_status_page_url,
        )
        return self.snapshot


def build_context() -> AutomationContext:
    return AutomationContext(
        settings=Settings(
            telegram_bot_token="token",
            telegram_allowed_chat_id=1,
            request_timeout_seconds=20,
            automation_timeout_seconds=30,
            weather_timezone="America/Sao_Paulo",
            weather_city_name="Sao Paulo",
            trends_primary_url="https://getdaytrends.com/brazil/",
            trends_fallback_url="https://trends24.in/brazil/",
            finance_awesomeapi_url=(
                "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL"
            ),
            finance_yahoo_b3_url=(
                "https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&range=1d"
            ),
            locaweb_summary_url="https://statusblog.locaweb.com.br/api/v2/summary.json",
            locaweb_components_url="https://statusblog.locaweb.com.br/api/v2/components.json",
            locaweb_incidents_url="https://statusblog.locaweb.com.br/api/v2/incidents.json",
            meta_orgs_url="https://metastatus.com/data/orgs.json",
            meta_outages_url_template="https://metastatus.com/data/outages/{org}.history.json",
            meta_metrics_url_template="https://metastatus.com/metrics/{org}/{metric}.json",
            umbrella_summary_url="https://status.umbrella.com/api/v2/summary.json",
            umbrella_incidents_url="https://status.umbrella.com/api/v2/incidents.json",
            hostinger_summary_url="https://statuspage.hostinger.com/api/v2/summary.json",
            hostinger_components_url="https://statuspage.hostinger.com/api/v2/components.json",
            hostinger_incidents_url="https://statuspage.hostinger.com/api/v2/incidents.json",
            hostinger_status_page_url="https://statuspage.hostinger.com/",
            host_report_timezone="America/Sao_Paulo",
        )
    )


@pytest.mark.asyncio
async def test_status_host_formats_consolidated_report() -> None:
    maintenance_start = datetime(2026, 2, 13, 4, 0, tzinfo=timezone.utc)
    maintenance_end = datetime(2026, 2, 13, 5, 0, tzinfo=timezone.utc)
    code_maintenance_start = datetime(2026, 2, 13, 6, 0, tzinfo=timezone.utc)
    code_maintenance_end = datetime(2026, 2, 13, 8, 0, tzinfo=timezone.utc)
    code_maintenance_start_2 = datetime(2026, 2, 13, 16, 0, tzinfo=timezone.utc)
    code_maintenance_end_2 = datetime(2026, 2, 13, 18, 0, tzinfo=timezone.utc)
    short_incident = HostIncident(
        source_id="1",
        title="Falha no acesso",
        status="Resolved",
        started_at=None,
        updates=[HostIncidentUpdate(status="Identified", body="Em analise", display_at=None)],
    )
    umbrella_incident = HostIncident(
        source_id="2",
        title="[Umbrella/Secure Connect] Policy Enforcement service is delayed processing globally",
        status="Resolved",
        started_at=None,
        updates=[
            HostIncidentUpdate(
                status="Identified",
                body=(
                    "All policy files have now been processed and the queue is clear. "
                    "Policy generation is functioning as expected, with new policies being "
                    "applied promptly after configuration. Verification confirms that "
                    "policies are being delivered efficiently."
                ),
                display_at=None,
            )
        ],
    )
    automation = StatusHostAutomation(
        FakeProvider(
            snapshot=HostSnapshot(
                locaweb=LocawebReport(
                    component_statuses={
                        "Hospedagem": "operational",
                        "Email": "operational",
                        "Central do Cliente": "operational",
                        "Outros...": "operational",
                    },
                    all_operational=True,
                    incidents_today=[short_incident],
                    error=None,
                ),
                meta=MetaReport(
                    orgs=[
                        MetaOrgReport(
                            org_id="admin-center",
                            display_name="Meta Admin Center",
                            statuses=["No known issues"],
                            all_no_known_issues=True,
                        )
                    ],
                    whatsapp_availability=99.98,
                    whatsapp_latency_p90_ms=1397,
                    whatsapp_latency_p99_ms=2891,
                    incidents_today=[short_incident],
                    error=None,
                ),
                umbrella=UmbrellaReport(
                    component_statuses={
                        "Umbrella Global": "operational",
                        "Umbrella South America": "degraded_performance",
                    },
                    component_statuses_human={
                        "Umbrella Global": "Normal",
                        "Umbrella South America": "Lento",
                    },
                    all_operational=False,
                    incidents_active_or_today=[umbrella_incident],
                    error=None,
                ),
                hostinger=HostingerReport(
                    overall_ok=False,
                    vps_components_non_operational={"VPS node": "major_outage"},
                    incidents_active_recent=[short_incident],
                    upcoming_maintenances=[
                        HostMaintenance(
                            name="Server pve-node241 maintenance",
                            scheduled_for=maintenance_start,
                            scheduled_until=maintenance_end,
                        ),
                        HostMaintenance(
                            name="Server pve-node234 maintenance",
                            scheduled_for=maintenance_start,
                            scheduled_until=maintenance_end,
                        ),
                        HostMaintenance(
                            name="Database migration window",
                            scheduled_for=maintenance_start,
                            scheduled_until=maintenance_end,
                        ),
                        HostMaintenance(
                            name="Server US-1818 maintenance",
                            scheduled_for=code_maintenance_start,
                            scheduled_until=code_maintenance_end,
                        ),
                        HostMaintenance(
                            name="Server SG-600 maintenance",
                            scheduled_for=code_maintenance_start_2,
                            scheduled_until=code_maintenance_end_2,
                        ),
                    ],
                    error=None,
                ),
                websites=WebsiteChecksReport(
                    checks=[
                        WebsiteCheckResult(
                            label="MV",
                            url="https://site01.test/",
                            is_up=True,
                            final_status_code=200,
                            error=None,
                        ),
                        WebsiteCheckResult(
                            label="Chat Accbook",
                            url="https://site07.test/login",
                            is_up=False,
                            final_status_code=502,
                            error="HTTP 502",
                        ),
                    ]
                ),
            )
        ),
        translator=FakeTranslator(),
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "<b>Locaweb</b>" in result.message
    assert "<b>Meta</b>" in result.message
    assert "<b>Hostinger</b>" in result.message
    assert "<b>Sites Monitorados</b>" in result.message
    assert "<b>Cisco Umbrella</b>" in result.message
    assert "<b>PT::Cisco Umbrella</b>" not in result.message
    assert "WhatsApp Availability: 99.98%" in result.message
    assert "P90 1397 ms, P99 2891 ms (last 31 days)" in result.message
    assert "Meta Admin Center" not in result.message
    assert "Umbrella Global: Normal (operational)" not in result.message
    assert "<b>PT::Incidentes ativos/hoje</b>" in result.message
    assert "PT::All policy files have now been processed" in result.message
    assert "Incidentes de hoje" in result.message
    assert "Sites OK: 1/2" in result.message
    assert "- Chat Accbook: DOWN" in result.message
    assert "HTTP 502" not in result.message
    assert "- VPS node: major_outage" in result.message
    assert "<b>Manutenções futuras</b>" in result.message
    assert "Server maintenance | inicio: 13/02/2026 | fim: 13/02/2026" in result.message
    assert "01:00 --- 02:00 | pve-node | (234) | (241)" in result.message
    assert "03:00 --- 05:00 | US-1818" in result.message
    assert "13:00 --- 15:00 | SG-600" in result.message
    assert "01:00 --- 02:00 | Database migration window" in result.message
    assert result.message.rfind("Cisco") > result.message.rfind("Sites Monitorados")


@pytest.mark.asyncio
async def test_status_host_hides_incident_sections_when_empty() -> None:
    automation = StatusHostAutomation(
        FakeProvider(
            snapshot=HostSnapshot(
                locaweb=LocawebReport(
                    component_statuses={"Hospedagem": "operational"},
                    all_operational=True,
                    incidents_today=[],
                    error=None,
                ),
                meta=MetaReport(
                    orgs=[],
                    whatsapp_availability=None,
                    whatsapp_latency_p90_ms=None,
                    whatsapp_latency_p99_ms=None,
                    incidents_today=[],
                    error=None,
                ),
                umbrella=UmbrellaReport(
                    component_statuses={"Umbrella Global": "operational"},
                    component_statuses_human={"Umbrella Global": "Normal"},
                    all_operational=True,
                    incidents_active_or_today=[],
                    error=None,
                ),
                hostinger=HostingerReport(
                    overall_ok=True,
                    vps_components_non_operational={},
                    incidents_active_recent=[],
                    upcoming_maintenances=[],
                    error=None,
                ),
                websites=WebsiteChecksReport(
                    checks=[
                        WebsiteCheckResult(
                            label="MV",
                            url="https://site01.test/",
                            is_up=True,
                            final_status_code=200,
                            error=None,
                        )
                    ]
                ),
            )
        )
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "<b>Locaweb</b>" in result.message
    assert "Saude: OK" in result.message
    assert "<b>Cisco Umbrella</b>" not in result.message
    assert "<b>Hostinger</b>" in result.message
    assert "<b>Sites Monitorados</b>" in result.message
    assert "Sites OK: 1/1" in result.message
    assert "Incidentes de hoje" not in result.message
    assert "Incidentes ativos/hoje" not in result.message


@pytest.mark.asyncio
async def test_status_host_cisco_translation_fallback_when_translator_fails() -> None:
    umbrella_incident = HostIncident(
        source_id="umb-1",
        title="[Umbrella/Secure Connect] Policy Enforcement service is delayed processing globally",
        status="Resolved",
        started_at=None,
        updates=[
            HostIncidentUpdate(
                status="Resolved",
                body=(
                    "All policy files have now been processed and the queue is clear. "
                    "Policy generation is functioning as expected, with new policies being "
                    "applied promptly after configuration."
                ),
                display_at=None,
            )
        ],
    )
    automation = StatusHostAutomation(
        FakeProvider(
            snapshot=HostSnapshot(
                locaweb=LocawebReport(
                    component_statuses={"Hospedagem": "operational"},
                    all_operational=True,
                    incidents_today=[],
                    error=None,
                ),
                meta=MetaReport(
                    orgs=[],
                    whatsapp_availability=None,
                    whatsapp_latency_p90_ms=None,
                    whatsapp_latency_p99_ms=None,
                    incidents_today=[],
                    error=None,
                ),
                umbrella=UmbrellaReport(
                    component_statuses={"Umbrella Global": "major_outage"},
                    component_statuses_human={"Umbrella Global": "Major Outage"},
                    all_operational=False,
                    incidents_active_or_today=[umbrella_incident],
                    error=None,
                ),
                hostinger=HostingerReport(
                    overall_ok=True,
                    vps_components_non_operational={},
                    incidents_active_recent=[],
                    upcoming_maintenances=[],
                    error=None,
                ),
                websites=WebsiteChecksReport(
                    checks=[
                        WebsiteCheckResult(
                            label="MV",
                            url="https://site01.test/",
                            is_up=True,
                            final_status_code=200,
                            error=None,
                        )
                    ]
                ),
            )
        ),
        translator=FailingTranslator(),
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "<b>Cisco Umbrella</b>" in result.message
    assert "<b>Incidentes ativos/hoje</b>" in result.message
    assert "Resolvido" in result.message
    assert "Todos os arquivos de politica foram processados e a fila esta normal." in result.message
    assert "All policy files have now been processed" not in result.message


@pytest.mark.asyncio
async def test_status_host_cisco_shows_only_first_update_per_incident() -> None:
    umbrella_incident = HostIncident(
        source_id="umb-only-first",
        title="[Umbrella/Secure Connect] Policy Enforcement service is delayed processing globally",
        status="Resolved",
        started_at=None,
        updates=[
            HostIncidentUpdate(
                status="Resolved",
                body="All policy files have now been processed and the queue is clear.",
                display_at=None,
            ),
            HostIncidentUpdate(
                status="Identified",
                body="We are continuing to process the remaining policy updates.",
                display_at=None,
            ),
        ],
    )
    automation = StatusHostAutomation(
        FakeProvider(
            snapshot=HostSnapshot(
                locaweb=LocawebReport(
                    component_statuses={"Hospedagem": "operational"},
                    all_operational=True,
                    incidents_today=[],
                    error=None,
                ),
                meta=MetaReport(
                    orgs=[],
                    whatsapp_availability=None,
                    whatsapp_latency_p90_ms=None,
                    whatsapp_latency_p99_ms=None,
                    incidents_today=[],
                    error=None,
                ),
                umbrella=UmbrellaReport(
                    component_statuses={"Umbrella Global": "major_outage"},
                    component_statuses_human={"Umbrella Global": "Major Outage"},
                    all_operational=False,
                    incidents_active_or_today=[umbrella_incident],
                    error=None,
                ),
                hostinger=HostingerReport(
                    overall_ok=True,
                    vps_components_non_operational={},
                    incidents_active_recent=[],
                    upcoming_maintenances=[],
                    error=None,
                ),
                websites=WebsiteChecksReport(
                    checks=[
                        WebsiteCheckResult(
                            label="MV",
                            url="https://site01.test/",
                            is_up=True,
                            final_status_code=200,
                            error=None,
                        )
                    ]
                ),
            )
        ),
        translator=FailingTranslator(),
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "Resolvido |" in result.message
    assert "Identificado |" not in result.message
