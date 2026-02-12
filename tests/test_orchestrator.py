from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.orchestrator import StatusOrchestrator
from src.automations_lib.registry import AutomationRegistry
from src.config import Settings


def settings() -> Settings:
    return Settings(
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


@dataclass
class SuccessAutomation:
    name: str = "success"
    trigger: str = "status"

    async def run(self, context: AutomationContext) -> AutomationResult:
        del context
        return AutomationResult(
            title="ok",
            message="ok",
            source_label="success",
            generated_at=datetime.now(timezone.utc),
            ok=True,
        )


@dataclass
class FailingAutomation:
    name: str = "failing"
    trigger: str = "status"

    async def run(self, context: AutomationContext) -> AutomationResult:
        del context
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_orchestrator_continues_after_failure() -> None:
    registry = AutomationRegistry()
    registry.register(FailingAutomation())
    registry.register(SuccessAutomation())
    orchestrator = StatusOrchestrator(registry, timeout_seconds=5)

    results = await orchestrator.run_trigger(
        "status",
        AutomationContext(settings=settings()),
    )

    assert len(results) == 2
    assert results[0].ok is False
    assert "Falha ao executar automação" in results[0].message
    assert results[1].ok is True
    assert results[1].message == "ok"
