from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.automations_lib.providers.issabel_ami_provider import ConnectedVoipSipPeer
from src.config import Settings
from src.handlers import BotHandlers


class DummyOrchestrator:
    async def run_trigger(self, trigger: str, context):
        del trigger, context
        return []


@dataclass
class FakeChat:
    id: int


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[dict] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append({"text": text, "kwargs": kwargs})


class FakeUpdate:
    def __init__(self, text: str, chat_id: int) -> None:
        self.effective_chat = FakeChat(chat_id)
        self.effective_message = FakeMessage(text)
        self.message = self.effective_message
        self.effective_user = None


class FakeIssabelProvider:
    def __init__(self, peers: list[ConnectedVoipSipPeer] | None = None, error: Exception | None = None) -> None:
        self._peers = peers or []
        self._error = error
        self.called = False

    async def list_connected_voips(self) -> list[ConnectedVoipSipPeer]:
        self.called = True
        if self._error is not None:
            raise self._error
        return list(self._peers)


def build_settings(allowed_chat_id: int | None) -> Settings:
    return Settings(
        telegram_bot_token="token",
        telegram_allowed_chat_id=allowed_chat_id,
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


@pytest.mark.asyncio
async def test_voips_handler_lists_connected_peers() -> None:
    peers = [
        ConnectedVoipSipPeer(name="1001", ip="10.0.0.1", port=5060, status="OK (12 ms)"),
        ConnectedVoipSipPeer(name="1002", ip="10.0.0.2", port=None, status=None),
    ]
    provider = FakeIssabelProvider(peers=peers)
    handlers = BotHandlers(
        settings=build_settings(allowed_chat_id=123),
        orchestrator=DummyOrchestrator(),
        issabel_provider=provider,  # type: ignore[arg-type]
    )
    update = FakeUpdate(text="/voips", chat_id=123)

    await handlers.voips_handler(update, context=None)  # type: ignore[arg-type]

    assert provider.called is True
    combined = "\n".join(item["text"] for item in update.message.replies)
    assert "VoIPs conectados (SIP)" in combined
    assert "Total: <b>2</b>" in combined
    assert "- 1001: 10.0.0.1:5060 | OK (12 ms)" in combined
    assert "- 1002: 10.0.0.2" in combined


@pytest.mark.asyncio
async def test_voips_handler_blocks_unauthorized_chat() -> None:
    provider = FakeIssabelProvider(peers=[])
    handlers = BotHandlers(
        settings=build_settings(allowed_chat_id=123),
        orchestrator=DummyOrchestrator(),
        issabel_provider=provider,  # type: ignore[arg-type]
    )
    update = FakeUpdate(text="/voips", chat_id=999)

    await handlers.voips_handler(update, context=None)  # type: ignore[arg-type]

    assert provider.called is False
    assert any("Acesso nao autorizado" in item["text"] for item in update.message.replies)


@pytest.mark.asyncio
async def test_voips_handler_not_configured_returns_friendly_message() -> None:
    provider = FakeIssabelProvider(error=ValueError("ISSABEL AMI nao configurado"))
    handlers = BotHandlers(
        settings=build_settings(allowed_chat_id=123),
        orchestrator=DummyOrchestrator(),
        issabel_provider=provider,  # type: ignore[arg-type]
    )
    update = FakeUpdate(text="/voips", chat_id=123)

    await handlers.voips_handler(update, context=None)  # type: ignore[arg-type]

    assert provider.called is True
    combined = "\n".join(item["text"] for item in update.message.replies)
    assert "ISSABEL AMI nao configurado" in combined

