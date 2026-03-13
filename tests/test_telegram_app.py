from __future__ import annotations

from dataclasses import dataclass

import pytest
from telegram.ext import CommandHandler, MessageHandler

from src import telegram_app
from src.config import Settings


def build_settings(*, voip_call_timeout_seconds: int = 30) -> Settings:
    return Settings(
        telegram_bot_token="token-123",
        telegram_allowed_chat_id=123,
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
        voip_call_timeout_seconds=voip_call_timeout_seconds,
    )


class FakeApplication:
    def __init__(self) -> None:
        self.bot_data: dict[str, object] = {}
        self.handlers: list[object] = []
        self.error_handlers: list[object] = []

    def add_handler(self, handler) -> None:
        self.handlers.append(handler)

    def add_error_handler(self, handler) -> None:
        self.error_handlers.append(handler)


class FakeBuilder:
    def __init__(self, application: FakeApplication) -> None:
        self._application = application
        self.token_value: str | None = None
        self.post_init_callback = None
        self.post_shutdown_callback = None
        self.build_called = False

    def token(self, token: str):
        self.token_value = token
        return self

    def post_init(self, callback):
        self.post_init_callback = callback
        return self

    def post_shutdown(self, callback):
        self.post_shutdown_callback = callback
        return self

    def build(self) -> FakeApplication:
        self.build_called = True
        return self._application


class FakeRegistry:
    def __init__(self) -> None:
        self.registered: list[object] = []

    def register(self, automation: object) -> None:
        self.registered.append(automation)


class FakeStatusOrchestrator:
    def __init__(self, registry: FakeRegistry, timeout_seconds: int) -> None:
        self.registry = registry
        self.timeout_seconds = timeout_seconds


class FakeVoipProbeProvider:
    def __init__(self, timeout_seconds: int) -> None:
        self.timeout_seconds = timeout_seconds


class FakeStateStore:
    def __init__(self, path: str) -> None:
        self.path = path
        self.closed = False

    def close(self) -> None:
        self.closed = True


class FakeBotHandlers:
    last_instance = None

    def __init__(self, **kwargs) -> None:
        type(self).last_instance = self
        self.kwargs = kwargs
        self.start_handler = self._callback("start")
        self.help_handler = self._callback("help")
        self.status_handler = self._callback("status")
        self.host_handler = self._callback("host")
        self.health_handler = self._callback("health")
        self.all_handler = self._callback("all")
        self.whois_handler = self._callback("whois")
        self.cep_handler = self._callback("cep")
        self.ping_handler = self._callback("ping")
        self.ssl_handler = self._callback("ssl")
        self.voips_handler = self._callback("voips")
        self.voip_handler = self._callback("voip")
        self.call_handler = self._callback("call")
        self.voip_logs_handler = self._callback("voip_logs")
        self.note_handler = self._callback("note")
        self.lembrete_handler = self._callback("lembrete")
        self.logs_handler = self._callback("logs")
        self.text_handler = self._callback("text")
        self.channel_post_handler = self._callback("channel_post")

    @staticmethod
    def _callback(name: str):
        async def _inner(*args, **kwargs) -> None:
            del args, kwargs, name

        return _inner


class FakeService:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.started = False
        self.stopped = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class FakeProvider:
    def __init__(self, *args, **kwargs) -> None:
        self.args = args
        self.kwargs = kwargs


class FakeAutomation:
    def __init__(self, provider: object) -> None:
        self.provider = provider


@dataclass
class LifecycleApplication:
    bot_data: dict[str, object]


def test_build_application_registers_handlers_and_services(monkeypatch) -> None:
    settings = build_settings(voip_call_timeout_seconds=11)
    application = FakeApplication()
    builder = FakeBuilder(application)
    created: dict[str, object] = {}

    monkeypatch.setattr(telegram_app, "ApplicationBuilder", lambda: builder)
    monkeypatch.setattr(telegram_app, "BotStateStore", FakeStateStore)
    monkeypatch.setattr(telegram_app, "AutomationRegistry", FakeRegistry)
    monkeypatch.setattr(telegram_app, "StatusOrchestrator", FakeStatusOrchestrator)
    monkeypatch.setattr(telegram_app, "VoipProbeProvider", FakeVoipProbeProvider)
    monkeypatch.setattr(telegram_app, "BotHandlers", FakeBotHandlers)
    monkeypatch.setattr(telegram_app, "NewsProvider", FakeProvider)
    monkeypatch.setattr(telegram_app, "WeatherProvider", FakeProvider)
    monkeypatch.setattr(telegram_app, "TrendsProvider", FakeProvider)
    monkeypatch.setattr(telegram_app, "FinanceProvider", FakeProvider)
    monkeypatch.setattr(telegram_app, "HealthProvider", FakeProvider)
    monkeypatch.setattr(telegram_app, "HostStatusProvider", FakeProvider)
    monkeypatch.setattr(telegram_app, "StatusNewsAutomation", FakeAutomation)
    monkeypatch.setattr(telegram_app, "StatusWeatherAutomation", FakeAutomation)
    monkeypatch.setattr(telegram_app, "StatusTrendsAutomation", FakeAutomation)
    monkeypatch.setattr(telegram_app, "StatusFinanceAutomation", FakeAutomation)
    monkeypatch.setattr(telegram_app, "StatusHealthAutomation", FakeAutomation)
    monkeypatch.setattr(telegram_app, "StatusHostAutomation", FakeAutomation)

    def make_service(label: str):
        def factory(**kwargs):
            service = FakeService(**kwargs)
            created[label] = service
            return service

        return factory

    monkeypatch.setattr(telegram_app, "ProactiveService", make_service("proactive"))
    monkeypatch.setattr(telegram_app, "ReminderService", make_service("reminder"))
    monkeypatch.setattr(telegram_app, "VoipProbeService", make_service("voip_probe"))

    built_application = telegram_app.build_application(settings)

    assert built_application is application
    assert builder.token_value == "token-123"
    assert builder.post_init_callback is telegram_app._post_init
    assert builder.post_shutdown_callback is telegram_app._post_shutdown
    assert builder.build_called is True

    command_names = [
        next(iter(handler.commands))
        for handler in application.handlers
        if isinstance(handler, CommandHandler)
    ]
    assert command_names == [
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
        "voip",
        "call",
        "voip_logs",
        "note",
        "lembrete",
        "logs",
    ]
    assert len(
        [handler for handler in application.handlers if isinstance(handler, MessageHandler)]
    ) == 2
    assert application.error_handlers == [telegram_app._error_handler]

    assert "state_store" in application.bot_data
    assert "proactive_service" in application.bot_data
    assert "reminder_service" in application.bot_data
    assert "voip_probe_service" in application.bot_data

    state_store = application.bot_data["state_store"]
    assert isinstance(state_store, FakeStateStore)
    assert state_store.path == settings.state_db_path

    assert isinstance(application.bot_data["proactive_service"], FakeService)
    assert isinstance(application.bot_data["reminder_service"], FakeService)
    assert isinstance(application.bot_data["voip_probe_service"], FakeService)
    assert application.bot_data["proactive_service"] is created["proactive"]
    assert application.bot_data["reminder_service"] is created["reminder"]
    assert application.bot_data["voip_probe_service"] is created["voip_probe"]

    voip_provider = application.bot_data["voip_probe_service"].kwargs["provider"]
    assert isinstance(voip_provider, FakeVoipProbeProvider)
    assert voip_provider.timeout_seconds == 97
    assert FakeBotHandlers.last_instance.kwargs["state_store"] is state_store
    assert FakeBotHandlers.last_instance.kwargs["voip_provider"] is voip_provider


@pytest.mark.asyncio
async def test_post_init_starts_available_services() -> None:
    proactive = FakeService()
    reminder = FakeService()
    voip_probe = FakeService()
    application = LifecycleApplication(
        bot_data={
            "proactive_service": proactive,
            "reminder_service": reminder,
            "voip_probe_service": voip_probe,
        }
    )

    await telegram_app._post_init(application)

    assert proactive.started is True
    assert reminder.started is True
    assert voip_probe.started is True


@pytest.mark.asyncio
async def test_post_init_tolerates_missing_services() -> None:
    application = LifecycleApplication(bot_data={})

    await telegram_app._post_init(application)

    assert application.bot_data == {}


@pytest.mark.asyncio
async def test_post_shutdown_stops_services_and_closes_state_store() -> None:
    proactive = FakeService()
    reminder = FakeService()
    voip_probe = FakeService()
    state_store = FakeStateStore("data/state.db")
    application = LifecycleApplication(
        bot_data={
            "proactive_service": proactive,
            "reminder_service": reminder,
            "voip_probe_service": voip_probe,
            "state_store": state_store,
        }
    )

    await telegram_app._post_shutdown(application)

    assert proactive.stopped is True
    assert reminder.stopped is True
    assert voip_probe.stopped is True
    assert state_store.closed is True


@pytest.mark.asyncio
async def test_post_shutdown_tolerates_missing_services() -> None:
    application = LifecycleApplication(bot_data={})

    await telegram_app._post_shutdown(application)

    assert application.bot_data == {}


@pytest.mark.asyncio
async def test_post_shutdown_tolerates_state_store_close_error(caplog) -> None:
    class BrokenStateStore:
        def close(self) -> None:
            raise RuntimeError("boom")

    application = LifecycleApplication(bot_data={"state_store": BrokenStateStore()})

    with caplog.at_level("WARNING", logger=telegram_app.logger.name):
        await telegram_app._post_shutdown(application)

    assert "failed to close state store" in caplog.text
