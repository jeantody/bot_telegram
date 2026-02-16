from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.config import Settings
from src.reminder_service import ReminderService
from src.state_store import BotStateStore


class FakeBot:
    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.messages: list[dict] = []

    async def send_message(self, **kwargs):
        if self.fail:
            raise RuntimeError("send fail")
        self.messages.append(kwargs)
        return None


class FakeApp:
    def __init__(self, bot) -> None:
        self.bot = bot


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
async def test_dispatch_due_reminders_success(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    reminder_id = store.create_reminder(
        chat_id=123,
        user_id=1,
        username="u",
        text="teste",
        remind_at_utc=datetime.now(timezone.utc) - timedelta(minutes=1),
        timezone_name="America/Sao_Paulo",
    )
    bot = FakeBot(fail=False)
    service = ReminderService(
        application=FakeApp(bot),
        settings=build_settings(),
        state_store=store,
    )
    await service._dispatch_due_reminders()

    assert len(bot.messages) == 1
    rows = store.list_due_reminders(
        now_utc=datetime.now(timezone.utc),
        retry_limit=3,
        limit=10,
    )
    assert all(item["id"] != reminder_id for item in rows)


@pytest.mark.asyncio
async def test_dispatch_due_reminders_failure_increments_attempt(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    reminder_id = store.create_reminder(
        chat_id=123,
        user_id=1,
        username="u",
        text="teste",
        remind_at_utc=datetime.now(timezone.utc) - timedelta(minutes=1),
        timezone_name="America/Sao_Paulo",
    )
    bot = FakeBot(fail=True)
    service = ReminderService(
        application=FakeApp(bot),
        settings=build_settings(),
        state_store=store,
    )
    await service._dispatch_due_reminders()

    rows = store.list_due_reminders(
        now_utc=datetime.now(timezone.utc),
        retry_limit=3,
        limit=10,
    )
    assert rows[0]["id"] == reminder_id
    assert rows[0]["send_attempts"] == 1
