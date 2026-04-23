from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.automations_lib.automations.status_trends import StatusTrendsAutomation
from src.automations_lib.models import AutomationContext
from src.automations_lib.providers.trends_provider import TrendsSnapshot
from src.config import Settings


@dataclass
class FakeProvider:
    snapshot: TrendsSnapshot

    async def fetch_top_trends(
        self,
        primary_url: str,
        fallback_url: str,
        limit: int = 10,
    ) -> TrendsSnapshot:
        del primary_url, fallback_url, limit
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
async def test_trends_automation_formats_ranked_list() -> None:
    automation = StatusTrendsAutomation(
        FakeProvider(
            snapshot=TrendsSnapshot(
                source_name="Trends24",
                source_url="https://trends24.in/brazil/",
                trends=["Tema 1", "Tema 2", "Tema 3"],
            )
        )
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "Trending Topics (Brasil)" in result.message
    assert 'href="https://trends24.in/brazil/"' in result.message
    assert "1. Tema 1" in result.message
    assert "3. Tema 3" in result.message
    assert result.source_label == "Trends24"
