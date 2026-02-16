from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.automations_lib.models import AutomationResult
from src.config import Settings
from src.handlers import (
    BotHandlers,
    is_all_command,
    is_health_command,
    is_host_command,
    is_status_command,
)
from src.state_store import BotStateStore


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
        self.message = FakeMessage(text)
        self.effective_message = self.message
        self.effective_chat = FakeChat(chat_id)
        self.channel_post = None


class FakeChannelUpdate:
    def __init__(self, text: str, chat_id: int) -> None:
        self.channel_post = FakeMessage(text)
        self.effective_message = self.channel_post
        self.effective_chat = FakeChat(chat_id)
        self.message = None


class FakeBot:
    def __init__(self, username: str = "bot_teste") -> None:
        self.username = username


class FakeContext:
    def __init__(self, username: str = "bot_teste", args: list[str] | None = None) -> None:
        self.bot = FakeBot(username=username)
        self.args = args or []


class FakeOrchestrator:
    def __init__(self, results_by_trigger: dict[str, list[AutomationResult]]) -> None:
        self._results_by_trigger = results_by_trigger
        self.called_triggers: list[str] = []

    async def run_trigger(self, trigger: str, context) -> list[AutomationResult]:
        del context
        self.called_triggers.append(trigger)
        return self._results_by_trigger.get(trigger, [])


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


def result(text: str) -> AutomationResult:
    return AutomationResult(
        title="t",
        message=text,
        source_label="s",
        generated_at=datetime.now(timezone.utc),
        ok=True,
    )


def test_is_status_command_variants() -> None:
    assert is_status_command("status")
    assert is_status_command("  /status ")
    assert is_status_command("/status@bot_teste", bot_username="bot_teste")
    assert not is_status_command("/status@outro_bot", bot_username="bot_teste")
    assert not is_status_command("hello")


def test_is_host_command_variants() -> None:
    assert is_host_command("host")
    assert is_host_command("/host")
    assert is_host_command("/host@bot_teste", bot_username="bot_teste")
    assert not is_host_command("/host@outro_bot", bot_username="bot_teste")


def test_is_all_command_variants() -> None:
    assert is_all_command("all")
    assert is_all_command("/all")
    assert is_all_command("/all@bot_teste", bot_username="bot_teste")
    assert not is_all_command("/all@outro_bot", bot_username="bot_teste")


def test_is_health_command_variants() -> None:
    assert is_health_command("health")
    assert is_health_command("/health")
    assert is_health_command("/health@bot_teste", bot_username="bot_teste")
    assert not is_health_command("/health@outro_bot", bot_username="bot_teste")


@pytest.mark.asyncio
async def test_status_text_sends_four_messages() -> None:
    orchestrator = FakeOrchestrator(
        {"status": [result("m1"), result("m2"), result("m3"), result("m4")]}
    )
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="status", chat_id=123)

    await handlers.text_handler(update, FakeContext())

    assert orchestrator.called_triggers == ["status"]
    assert [r["text"] for r in update.message.replies] == ["m1", "m2", "m3", "m4"]


@pytest.mark.asyncio
async def test_status_blocks_unauthorized_chat() -> None:
    orchestrator = FakeOrchestrator(
        {"status": [result("m1"), result("m2"), result("m3"), result("m4")]}
    )
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="/status", chat_id=999)

    await handlers.status_handler(update, FakeContext())

    assert orchestrator.called_triggers == []
    assert len(update.message.replies) == 1
    assert "Acesso nao autorizado" in update.message.replies[0]["text"]


@pytest.mark.asyncio
async def test_host_command_sends_single_report_message() -> None:
    orchestrator = FakeOrchestrator({"host": [result("host-report")]})
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="/host", chat_id=123)

    await handlers.host_handler(update, FakeContext())

    assert orchestrator.called_triggers == ["host"]
    assert [r["text"] for r in update.message.replies] == ["host-report"]


@pytest.mark.asyncio
async def test_all_command_runs_status_then_host() -> None:
    orchestrator = FakeOrchestrator(
        {
            "status": [result("s1"), result("s2"), result("s3"), result("s4")],
            "host": [result("h1")],
        }
    )
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="/all", chat_id=123)

    await handlers.all_handler(update, FakeContext())

    assert orchestrator.called_triggers == ["status", "host"]
    assert [r["text"] for r in update.message.replies[:5]] == [
        "s1",
        "s2",
        "s3",
        "s4",
        "h1",
    ]
    assert update.message.replies[5]["text"].startswith("<b>Lembretes de hoje")
    assert update.message.replies[6]["text"].startswith("<b>Lembretes de amanha")


@pytest.mark.asyncio
async def test_health_command_sends_single_report_message() -> None:
    orchestrator = FakeOrchestrator({"health": [result("health-report")]})
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="/health", chat_id=123)

    await handlers.health_handler(update, FakeContext())

    assert orchestrator.called_triggers == ["health"]
    assert [r["text"] for r in update.message.replies] == ["health-report"]


@pytest.mark.asyncio
async def test_logs_command_returns_audit_events(tmp_path) -> None:
    orchestrator = FakeOrchestrator({})
    store = BotStateStore(str(tmp_path / "state.db"))
    store.record_audit_event(
        trace_id="t1",
        event_type="command_end",
        command="/status",
        chat_id=123,
        user_id=1,
        username="tester",
        status="ok",
        severity="info",
        payload={"x": 1},
    )
    handlers = BotHandlers(
        settings=build_settings(allowed_chat_id=123),
        orchestrator=orchestrator,
        state_store=store,
    )
    update = FakeUpdate(text="/logs", chat_id=123)

    await handlers.logs_handler(update, FakeContext(args=["5"]))

    assert any("Audit Log (ultimos" in item["text"] for item in update.message.replies)
    assert any("/status" in item["text"] for item in update.message.replies)


@pytest.mark.asyncio
async def test_logs_command_error_filter_returns_only_error_events(tmp_path) -> None:
    orchestrator = FakeOrchestrator({})
    store = BotStateStore(str(tmp_path / "state.db"))
    store.record_audit_event(
        trace_id="t1",
        event_type="command_end",
        command="/status",
        chat_id=123,
        user_id=1,
        username="tester",
        status="ok",
        severity="info",
        payload=None,
    )
    store.record_audit_event(
        trace_id="t2",
        event_type="command_end",
        command="/host",
        chat_id=123,
        user_id=1,
        username="tester",
        status="error",
        severity="alerta",
        payload=None,
    )
    handlers = BotHandlers(
        settings=build_settings(allowed_chat_id=123),
        orchestrator=orchestrator,
        state_store=store,
    )
    update = FakeUpdate(text="/logs erro 5", chat_id=123)

    await handlers.logs_handler(update, FakeContext(args=["erro", "5"]))

    combined = "\n".join(item["text"] for item in update.message.replies)
    assert "ultimos 1 erros" in combined
    assert "/host" in combined
    assert "/status" not in combined
