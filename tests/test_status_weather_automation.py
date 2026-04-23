from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.automations_lib.automations.status_weather import StatusWeatherAutomation
from src.automations_lib.models import AutomationContext
from src.automations_lib.providers.weather_provider import WeatherSnapshot
from src.config import Settings


@dataclass
class FakeProvider:
    snapshot: WeatherSnapshot

    async def fetch_weather(self, city_name: str, timezone_name: str) -> WeatherSnapshot:
        del city_name, timezone_name
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
async def test_weather_automation_formats_snapshot() -> None:
    automation = StatusWeatherAutomation(
        FakeProvider(
            snapshot=WeatherSnapshot(
                current_temperature_c=25.2,
                temperature_12_c=24.0,
                temperature_19_c=22.5,
                temperature_21_c=21.0,
                rain_probability_avg_1700_1900=48.0,
                rain_probability_peak_1700_1900=67.0,
                generated_at_local=datetime.now(timezone.utc),
            )
        )
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "Clima - Sao Paulo (capital)" in result.message
    assert "Agora: <b>25.2C</b>" in result.message
    assert "media <b>48%</b>, pico <b>67%</b>" in result.message
    assert result.source_label == "Open-Meteo"
