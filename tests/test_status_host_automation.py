from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.automations_lib.automations.status_host import StatusHostAutomation
from src.automations_lib.models import AutomationContext
from src.automations_lib.providers.host_status_provider import (
    HostIncident,
    HostIncidentUpdate,
    HostSnapshot,
    LocawebReport,
    MetaOrgReport,
    MetaReport,
    UmbrellaReport,
)
from src.config import Settings


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
    ) -> HostSnapshot:
        del (
            locaweb_components_url,
            locaweb_incidents_url,
            meta_orgs_url,
            meta_outages_url_template,
            meta_metrics_url_template,
            umbrella_summary_url,
            umbrella_incidents_url,
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
            host_report_timezone="America/Sao_Paulo",
        )
    )


@pytest.mark.asyncio
async def test_status_host_formats_consolidated_report() -> None:
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
            )
        )
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "<b>Locaweb</b>" in result.message
    assert "<b>Meta</b>" in result.message
    assert "<b>Cisco Umbrella</b>" in result.message
    assert "WhatsApp Availability: 99.98%" in result.message
    assert "P90 1397 ms, P99 2891 ms (last 31 days)" in result.message
    assert "Meta Admin Center" not in result.message
    assert "Umbrella Global: Normal (operational)" not in result.message
    assert "<b>Incidentes ativos/hoje</b>" in result.message
    assert (
        "All policy files have now been processed and the queue is clear."
        in result.message
    )
    assert "Policy generation is functioning as expected" in result.message
    assert "applied promptly after configuration" not in result.message
    assert "policies are being delivered efficiently." not in result.message
    assert "Incidentes de hoje" in result.message


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
            )
        )
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "<b>Locaweb</b>" in result.message
    assert "Saude: OK" in result.message
    assert "<b>Cisco Umbrella</b>" not in result.message
    assert "Incidentes de hoje" not in result.message
    assert "Incidentes ativos/hoje" not in result.message
