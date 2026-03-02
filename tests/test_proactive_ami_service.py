from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from src.automations_lib.providers.ami_client import AmiError
from src.config import Settings
from src.proactive_service import ProactiveService
from src.state_store import BotStateStore


class FakeBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        self.messages.append(kwargs)
        return None


class FakeApp:
    def __init__(self, bot) -> None:
        self.bot = bot


class DummyOrchestrator:
    async def run_trigger(self, trigger: str, context):
        del trigger, context
        return []


@dataclass
class FakeOverview:
    total_count: int
    online_count: int
    offline_count: int
    connected_peers: list


class FakeIssabelProvider:
    def __init__(self, responses: list[FakeOverview | Exception]) -> None:
        self._responses = list(responses)

    async def list_voip_overview(self):
        if not self._responses:
            raise RuntimeError("no response configured")
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def transport_name(self) -> str:
        return "http_rawman"

    def endpoint_label(self) -> str:
        return "coalapabx.ddns.net:8088/asterisk/rawman"


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
        proactive_enabled=True,
        proactive_check_interval_seconds=300,
    )


@pytest.mark.asyncio
async def test_ami_probe_ok_without_drop_does_not_alert(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeIssabelProvider(
        responses=[
            FakeOverview(total_count=12, online_count=10, offline_count=2, connected_peers=[]),
            FakeOverview(total_count=12, online_count=10, offline_count=2, connected_peers=[]),
        ]
    )
    service = ProactiveService(
        application=FakeApp(bot),
        settings=build_settings(),
        orchestrator=DummyOrchestrator(),
        state_store=store,
        issabel_provider=provider,  # type: ignore[arg-type]
    )

    await service._run_ami_check("trace-1")
    await service._run_ami_check("trace-2")

    assert len(bot.messages) == 0
    events = store.list_audit_events(limit=10)
    ticks = [e for e in events if e["event_type"] == "ami_probe_tick"]
    assert len(ticks) >= 2
    assert all(e["status"] == "ok" for e in ticks[:2])


@pytest.mark.asyncio
async def test_ami_probe_drop_alerts_once(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeIssabelProvider(
        responses=[
            FakeOverview(total_count=12, online_count=10, offline_count=2, connected_peers=[]),
            FakeOverview(total_count=12, online_count=7, offline_count=5, connected_peers=[]),
        ]
    )
    service = ProactiveService(
        application=FakeApp(bot),
        settings=build_settings(),
        orchestrator=DummyOrchestrator(),
        state_store=store,
        issabel_provider=provider,  # type: ignore[arg-type]
    )

    await service._run_ami_check("trace-1")
    await service._run_ami_check("trace-2")

    assert len(bot.messages) == 1
    text = bot.messages[0]["text"]
    assert "Queda de ramais online" in text
    assert "Diferenca vs coleta anterior: -3" in text
    events = store.list_audit_events(limit=10)
    latest_tick = next(e for e in events if e["event_type"] == "ami_probe_tick")
    assert latest_tick["severity"] == "alerta"


@pytest.mark.asyncio
async def test_ami_probe_small_drop_does_not_alert(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeIssabelProvider(
        responses=[
            FakeOverview(total_count=12, online_count=10, offline_count=2, connected_peers=[]),
            FakeOverview(total_count=12, online_count=9, offline_count=3, connected_peers=[]),
        ]
    )
    service = ProactiveService(
        application=FakeApp(bot),
        settings=build_settings(),
        orchestrator=DummyOrchestrator(),
        state_store=store,
        issabel_provider=provider,  # type: ignore[arg-type]
    )

    await service._run_ami_check("trace-1")
    await service._run_ami_check("trace-2")

    assert len(bot.messages) == 0
    events = store.list_audit_events(limit=10)
    latest_tick = next(e for e in events if e["event_type"] == "ami_probe_tick")
    assert latest_tick["severity"] == "info"


@pytest.mark.asyncio
async def test_ami_probe_error_alerts_and_repeated_error_is_deduped(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    bot = FakeBot()
    provider = FakeIssabelProvider(
        responses=[AmiError("timeout"), AmiError("timeout")]
    )
    service = ProactiveService(
        application=FakeApp(bot),
        settings=build_settings(),
        orchestrator=DummyOrchestrator(),
        state_store=store,
        issabel_provider=provider,  # type: ignore[arg-type]
    )

    await service._run_ami_check("trace-1")
    await service._run_ami_check("trace-2")

    assert len(bot.messages) == 1
    assert "Falha AMI: timeout" in bot.messages[0]["text"]
    events = store.list_audit_events(limit=10)
    latest_tick = next(e for e in events if e["event_type"] == "ami_probe_tick")
    assert latest_tick["status"] == "error"
