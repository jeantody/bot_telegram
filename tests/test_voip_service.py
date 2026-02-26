from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.automations_lib.providers.voip_probe_provider import VoipProbeResult
from src.config import Settings
from src.state_store import BotStateStore
from src.voip_probe_service import VoipProbeService


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return None


class FakeApp:
    def __init__(self, bot) -> None:
        self.bot = bot


class FakeVoipProvider:
    def __init__(self, result: VoipProbeResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error

    async def run_once(self) -> VoipProbeResult:
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


def build_settings() -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_id=123,
        request_timeout_seconds=20,
        automation_timeout_seconds=30,
        weather_timezone="America/Sao_Paulo",
        weather_city_name="Sao Paulo",
        trends_primary_url="https://getdaytrends.com/brazil/",
        trends_fallback_url="https://trends24.in/brazil/",
        finance_awesomeapi_url="https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        finance_yahoo_b3_url="https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&range=1d",
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
        voip_probe_enabled=True,
        voip_probe_interval_seconds=3600,
        voip_latency_alert_ms=1500,
    )


@pytest.mark.asyncio
async def test_voip_service_no_alert_on_success(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeVoipProvider(
        result=VoipProbeResult(
            ok=True,
            completed_call=True,
            no_issues=True,
            target_number="1102",
            hold_seconds=5,
            setup_latency_ms=800,
            total_duration_ms=6000,
            sip_final_code=200,
            error=None,
            started_at_utc="2026-02-16T10:00:00+00:00",
            finished_at_utc="2026-02-16T10:00:06+00:00",
        )
    )
    service = VoipProbeService(
        application=FakeApp(bot),
        settings=build_settings(),
        state_store=store,
        provider=provider,  # type: ignore[arg-type]
    )
    await service._run_probe_once()

    assert len(bot.messages) == 0
    events = store.list_audit_events(limit=5)
    assert events[0]["event_type"] == "voip_probe_tick"
    assert events[0]["status"] == "ok"


@pytest.mark.asyncio
async def test_voip_service_alerts_on_failure(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeVoipProvider(
        result=VoipProbeResult(
            ok=False,
            completed_call=False,
            no_issues=False,
            target_number="1102",
            hold_seconds=5,
            setup_latency_ms=None,
            total_duration_ms=1000,
            sip_final_code=486,
            error="busy",
            started_at_utc="2026-02-16T10:00:00+00:00",
            finished_at_utc="2026-02-16T10:00:01+00:00",
        )
    )
    service = VoipProbeService(
        application=FakeApp(bot),
        settings=build_settings(),
        state_store=store,
        provider=provider,  # type: ignore[arg-type]
    )
    await service._run_probe_once()

    assert len(bot.messages) == 1
    assert "Alerta VoIP" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_voip_service_alerts_on_high_latency(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeVoipProvider(
        result=VoipProbeResult(
            ok=True,
            completed_call=True,
            no_issues=True,
            target_number="1102",
            hold_seconds=5,
            setup_latency_ms=2200,
            total_duration_ms=7200,
            sip_final_code=200,
            error=None,
            started_at_utc="2026-02-16T10:00:00+00:00",
            finished_at_utc="2026-02-16T10:00:07+00:00",
        )
    )
    service = VoipProbeService(
        application=FakeApp(bot),
        settings=build_settings(),
        state_store=store,
        provider=provider,  # type: ignore[arg-type]
    )
    await service._run_probe_once()

    assert len(bot.messages) == 1
    assert "LATENCIA ALTA" in bot.messages[0]["text"]


@pytest.mark.asyncio
async def test_voip_service_alerts_on_baseline_deviation(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeVoipProvider(
        result=VoipProbeResult(
            ok=True,
            completed_call=True,
            no_issues=True,
            target_number="1102",
            hold_seconds=5,
            setup_latency_ms=900,
            total_duration_ms=6400,
            sip_final_code=200,
            error=None,
            started_at_utc="2026-02-16T10:00:00+00:00",
            finished_at_utc="2026-02-16T10:00:06+00:00",
            summary={
                "deviation_alert": True,
                "deviation_reasons": ["latencia acima do baseline em 1102: 900ms"],
            },
        )
    )
    service = VoipProbeService(
        application=FakeApp(bot),
        settings=build_settings(),
        state_store=store,
        provider=provider,  # type: ignore[arg-type]
    )
    await service._run_probe_once()

    assert len(bot.messages) == 1
    assert "DESVIO BASELINE" in bot.messages[0]["text"]
