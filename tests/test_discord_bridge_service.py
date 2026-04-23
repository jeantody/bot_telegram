from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from types import SimpleNamespace

import httpx
import pytest

from src.automations_lib.models import AutomationResult
from src.bridge import BridgeNotifier
from src.config import Settings
from src import discord_bridge_service as discord_bridge_service_module
from src.discord_bridge_service import DiscordBridgeService, _command_args, _command_name
from src.handlers import BotHandlers


@dataclass
class FakeChannel:
    id: int


@dataclass
class FakeAuthor:
    id: int
    name: str
    bot: bool = False
    global_name: str | None = None


@dataclass
class FakeDiscordMessage:
    content: str
    channel: FakeChannel
    author: FakeAuthor
    webhook_id: int | None = None


@dataclass
class FakeDiscordUser:
    id: int
    name: str


@dataclass
class FakeDiscordClient:
    user: FakeDiscordUser


class RecordingHandlers:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, list[str], str | None]] = []
        for name in (
            "start",
            "help",
            "status",
            "host",
            "health",
            "all",
            "whois",
            "cep",
            "ping",
            "ssl",
            "voips",
            "net",
            "zabbixh",
            "voip",
            "call",
            "voip_logs",
            "note",
            "lembrete",
            "logs",
            "text",
        ):
            setattr(self, f"{name}_handler", self._make_handler(name))

    def _make_handler(self, name: str):
        async def _inner(update, context) -> None:
            self.calls.append(
                (
                    name,
                    update.message.text,
                    list(context.args),
                    getattr(context.bot, "username", None),
                )
            )

        return _inner


class FakeTelegramBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.messages.append(kwargs)


class FakeOrchestrator:
    def __init__(self) -> None:
        self.called_triggers: list[str] = []

    async def run_trigger(self, trigger: str, context) -> list[AutomationResult]:
        self.called_triggers.append(trigger)
        return [
            AutomationResult(
                title="Status",
                message="<b>Status</b>\nTudo OK",
                source_label="status",
                generated_at=datetime.now(timezone.utc),
                ok=True,
                severity="info",
            )
        ]


def build_settings(**kwargs) -> Settings:
    base = dict(
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
        discord_bridge_enabled=True,
        discord_bridge_webhook_url="https://discord.com/api/webhooks/1/token",
        discord_bridge_channel_id=456,
    )
    base.update(kwargs)
    return Settings(**base)


def _make_async_client_factory(handler):
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_async_client(*args, transport=transport, **kwargs)

    return factory


def test_command_helpers_parse_slash_commands() -> None:
    assert _command_name("/whois example.com") == "whois"
    assert _command_name("/status@bot_teste") == "status"
    assert _command_name("status") is None
    assert _command_args("/whois example.com") == ["example.com"]
    assert _command_args("status") == []


@pytest.mark.asyncio
async def test_discord_status_message_runs_handler_and_bridges_both_sides(monkeypatch) -> None:
    webhook_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        webhook_payloads.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(204, request=request)

    monkeypatch.setattr(
        "src.bridge.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    settings = build_settings()
    notifier = BridgeNotifier(settings)
    telegram_bot = FakeTelegramBot()
    notifier.set_telegram_bot(telegram_bot)
    orchestrator = FakeOrchestrator()
    handlers = BotHandlers(
        settings=settings,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        bridge_notifier=notifier,
    )
    service = DiscordBridgeService(
        settings=settings,
        handlers=handlers,
        bridge_notifier=notifier,
    )

    await service._on_discord_message(
        FakeDiscordMessage(
            content="status",
            channel=FakeChannel(id=456),
            author=FakeAuthor(id=999, name="ana"),
        ),
        FakeDiscordClient(user=FakeDiscordUser(id=111, name="bot")),
    )

    assert orchestrator.called_triggers == ["status"]
    assert telegram_bot.messages[0]["text"] == "<b>Discord @ana</b>\nstatus"
    assert telegram_bot.messages[1]["text"] == "<b>Status</b>\nTudo OK"
    assert webhook_payloads == [{"content": "**Status**\nTudo OK", "allowed_mentions": {"parse": []}}]


@pytest.mark.asyncio
async def test_discord_bridge_ignores_webhook_messages(monkeypatch) -> None:
    settings = build_settings()
    notifier = BridgeNotifier(settings)
    telegram_bot = FakeTelegramBot()
    notifier.set_telegram_bot(telegram_bot)
    orchestrator = FakeOrchestrator()
    handlers = BotHandlers(
        settings=settings,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        bridge_notifier=notifier,
    )
    service = DiscordBridgeService(
        settings=settings,
        handlers=handlers,
        bridge_notifier=notifier,
    )

    await service._on_discord_message(
        FakeDiscordMessage(
            content="status",
            channel=FakeChannel(id=456),
            author=FakeAuthor(id=999, name="webhook"),
            webhook_id=10,
        ),
        FakeDiscordClient(user=FakeDiscordUser(id=111, name="bot")),
    )

    assert orchestrator.called_triggers == []
    assert telegram_bot.messages == []


@pytest.mark.asyncio
async def test_discord_bridge_routes_slash_command_with_args() -> None:
    settings = build_settings()
    notifier = BridgeNotifier(settings)
    handlers = RecordingHandlers()
    service = DiscordBridgeService(
        settings=settings,
        handlers=handlers,  # type: ignore[arg-type]
        bridge_notifier=notifier,
    )

    await service._on_discord_message(
        FakeDiscordMessage(
            content="/whois example.com",
            channel=FakeChannel(id=456),
            author=FakeAuthor(id=999, name="ana"),
        ),
        FakeDiscordClient(user=FakeDiscordUser(id=111, name="bot")),
    )

    assert handlers.calls == [("whois", "/whois example.com", ["example.com"], "bot")]


@pytest.mark.asyncio
async def test_resolve_channel_id_reads_webhook_metadata(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        return httpx.Response(200, json={"channel_id": "456"}, request=request)

    monkeypatch.setattr(
        "src.discord_bridge_service.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    settings = build_settings(discord_bridge_channel_id=None)
    service = DiscordBridgeService(
        settings=settings,
        handlers=RecordingHandlers(),  # type: ignore[arg-type]
        bridge_notifier=BridgeNotifier(settings),
    )

    assert await service._resolve_channel_id() == 456


@pytest.mark.asyncio
async def test_start_rejects_missing_discord_token() -> None:
    settings = build_settings(discord_bot_token="")
    service = DiscordBridgeService(
        settings=settings,
        handlers=RecordingHandlers(),  # type: ignore[arg-type]
        bridge_notifier=BridgeNotifier(settings),
    )

    with pytest.raises(RuntimeError, match="DISCORD_BOT_TOKEN obrigatorio"):
        await service.start()


@pytest.mark.asyncio
async def test_start_and_stop_manage_discord_client(monkeypatch) -> None:
    created_clients: list[object] = []

    class FakeClient:
        def __init__(self, *, intents) -> None:
            self.intents = intents
            self.started_with: str | None = None
            self.closed = False
            created_clients.append(self)

        def event(self, callback):
            return callback

        async def start(self, token: str) -> None:
            self.started_with = token
            await asyncio.sleep(0)

        async def close(self) -> None:
            self.closed = True

    fake_discord = SimpleNamespace(
        Intents=SimpleNamespace(default=lambda: SimpleNamespace(message_content=False)),
        Client=FakeClient,
    )
    monkeypatch.setattr(discord_bridge_service_module, "discord", fake_discord)

    settings = build_settings(
        discord_bot_token="discord-token",
        discord_bridge_channel_id=456,
    )
    service = DiscordBridgeService(
        settings=settings,
        handlers=RecordingHandlers(),  # type: ignore[arg-type]
        bridge_notifier=BridgeNotifier(settings),
    )

    await service.start()
    await asyncio.sleep(0)

    fake_client = created_clients[0]
    assert fake_client.started_with == "discord-token"
    assert fake_client.intents.message_content is True

    await service.stop()

    assert fake_client.closed is True
    assert service._client is None
    assert service._task is None
