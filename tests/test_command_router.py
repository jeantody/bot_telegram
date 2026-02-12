from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pytest

from src.automations_lib.models import AutomationResult
from src.config import Settings
from src.handlers import BotHandlers, is_status_command


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


class FakeBot:
    def __init__(self, username: str = "bot_teste") -> None:
        self.username = username


class FakeContext:
    def __init__(self, username: str = "bot_teste") -> None:
        self.bot = FakeBot(username=username)


class FakeOrchestrator:
    def __init__(self, results: list[AutomationResult]) -> None:
        self._results = results
        self.called_trigger: str | None = None

    async def run_trigger(self, trigger: str, context) -> list[AutomationResult]:
        del context
        self.called_trigger = trigger
        return self._results


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


@pytest.mark.asyncio
async def test_status_text_sends_three_messages() -> None:
    orchestrator = FakeOrchestrator([result("m1"), result("m2"), result("m3")])
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="status", chat_id=123)

    await handlers.text_handler(update, FakeContext())

    assert orchestrator.called_trigger == "status"
    assert [r["text"] for r in update.message.replies] == ["m1", "m2", "m3"]


@pytest.mark.asyncio
async def test_status_blocks_unauthorized_chat() -> None:
    orchestrator = FakeOrchestrator([result("m1"), result("m2"), result("m3")])
    handlers = BotHandlers(settings=build_settings(allowed_chat_id=123), orchestrator=orchestrator)
    update = FakeUpdate(text="/status", chat_id=999)

    await handlers.status_handler(update, FakeContext())

    assert orchestrator.called_trigger is None
    assert len(update.message.replies) == 1
    assert "Acesso nao autorizado" in update.message.replies[0]["text"]

