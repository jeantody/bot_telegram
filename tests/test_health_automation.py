from __future__ import annotations

import pytest

from src.automations_lib.automations.status_health import StatusHealthAutomation
from src.automations_lib.models import AutomationContext
from src.automations_lib.providers.health_provider import HealthProbe
from src.config import Settings


class FakeProvider:
    async def fetch_health(self, probes):
        del probes
        return [
            HealthProbe(
                source="A",
                url="https://ok.example",
                ok=True,
                status_code=200,
                latency_ms=23,
                error=None,
            ),
            HealthProbe(
                source="B",
                url="https://fail.example",
                ok=False,
                status_code=None,
                latency_ms=55,
                error="timeout",
            ),
        ]


def build_context() -> AutomationContext:
    settings = Settings(
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
    return AutomationContext(settings=settings, trace_id="trace-health")


@pytest.mark.asyncio
async def test_health_automation_formats_report() -> None:
    automation = StatusHealthAutomation(provider=FakeProvider())
    result = await automation.run(build_context())

    assert result.ok is False
    assert result.severity == "alerta"
    assert "Health Check" in result.message
    assert "trace-health" in result.message
    assert "Falhas por fonte" in result.message
    assert "timeout" in result.message
