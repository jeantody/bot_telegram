from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from src.automations_lib.models import AutomationResult
from src.config import Settings
from src.handlers import BotHandlers
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


class FakeUser:
    id = 1
    username = "tester"


class FakeUpdate:
    def __init__(self, text: str, chat_id: int = 123) -> None:
        self.message = FakeMessage(text)
        self.effective_message = self.message
        self.effective_chat = FakeChat(chat_id)
        self.effective_user = FakeUser()


class FakeBot:
    username = "bot_teste"


class FakeContext:
    def __init__(self) -> None:
        self.bot = FakeBot()
        self.args = []


class FakeOrchestrator:
    def __init__(self, results_by_trigger: dict[str, list[AutomationResult]]) -> None:
        self._results_by_trigger = results_by_trigger
        self.called_triggers: list[str] = []

    async def run_trigger(self, trigger: str, context):
        del context
        self.called_triggers.append(trigger)
        return self._results_by_trigger.get(trigger, [])


def result(text: str) -> AutomationResult:
    return AutomationResult(
        title="t",
        message=text,
        source_label="s",
        generated_at=datetime.now(timezone.utc),
        ok=True,
    )


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
    )


@pytest.mark.asyncio
async def test_all_includes_today_and_tomorrow_reminders(tmp_path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    now = datetime.now(timezone.utc)
    store.create_reminder(
        chat_id=123,
        user_id=1,
        username="tester",
        text="hoje",
        remind_at_utc=now,
        timezone_name="UTC",
    )
    store.create_reminder(
        chat_id=123,
        user_id=1,
        username="tester",
        text="amanha",
        remind_at_utc=now + timedelta(days=1),
        timezone_name="UTC",
    )
    orchestrator = FakeOrchestrator({"status": [result("s1")], "host": [result("h1")]})
    handlers = BotHandlers(
        settings=build_settings(),
        orchestrator=orchestrator,
        state_store=store,
    )
    update = FakeUpdate("/all")

    await handlers.all_handler(update, FakeContext())

    replies = [item["text"] for item in update.message.replies]
    assert replies[0] == "s1"
    assert replies[1] == "h1"
    assert any(line.startswith("<b>Lembretes de hoje (") for line in replies)
    assert any(line.startswith("<b>Lembretes de amanha (") for line in replies)
