from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.automations_lib.automations.status_finance import StatusFinanceAutomation
from src.automations_lib.models import AutomationContext
from src.automations_lib.providers.finance_provider import FinanceSnapshot, QuoteValue
from src.config import Settings


@dataclass
class FakeProvider:
    snapshot: FinanceSnapshot

    async def fetch_snapshot(self, awesome_url: str, yahoo_b3_url: str) -> FinanceSnapshot:
        del awesome_url, yahoo_b3_url
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
async def test_finance_automation_formats_values_and_placeholders() -> None:
    automation = StatusFinanceAutomation(
        FakeProvider(
            snapshot=FinanceSnapshot(
                bitcoin=QuoteValue(symbol="BTCBRL", price=343351.94, change_pct=-0.40, updated_at=None),
                usd=QuoteValue(symbol="USDBRL", price=5.1990, change_pct=0.01, updated_at=None),
                eur=QuoteValue(symbol="EURBRL", price=6.1652, change_pct=-0.0, updated_at=None),
                ibov=QuoteValue(symbol="IBOV", price=188233.734375, change_pct=-0.77, updated_at=None),
            )
        )
    )

    result = await automation.run(build_context())

    assert result.ok is True
    assert "Bitcoin (BTC/BRL): R$ 343.351,94 | var: -0.40%" in result.message
    assert "Dolar (USD/BRL): R$ 5.19 | var: +0.01%" in result.message
    assert "Euro (EUR/BRL): R$ 6.16 | var: -0.00%" in result.message
    assert "B3 (IBOV): 188.233,73 pts | var: -0.77%" in result.message
