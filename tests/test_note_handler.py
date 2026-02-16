from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.config import Settings
from src.handlers import BotHandlers
from src.state_store import BotStateStore


@dataclass
class FakeChat:
    id: int


class FakeMessage:
    def __init__(self, text: str) -> None:
        self.text = text
        self.replies: list[str] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        del kwargs
        self.replies.append(text)


class FakeUser:
    def __init__(self, user_id: int = 1, username: str = "tester") -> None:
        self.id = user_id
        self.username = username


class FakeUpdate:
    def __init__(self, text: str, chat_id: int = 123) -> None:
        self.effective_chat = FakeChat(chat_id)
        self.effective_message = FakeMessage(text)
        self.message = self.effective_message
        self.effective_user = FakeUser()


class FakeSent:
    def __init__(self, message_id: int) -> None:
        self.message_id = message_id


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        return FakeSent(message_id=10)


class FailingBot(FakeBot):
    async def send_message(self, **kwargs):
        del kwargs
        raise RuntimeError("Chat not found")


class FakeContext:
    def __init__(self, args: list[str], bot: FakeBot) -> None:
        self.args = args
        self.bot = bot


class FakeOrchestrator:
    async def run_trigger(self, trigger: str, context):
        del trigger, context
        return []


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
        note_tab_chat_ids=(("estudos", -1001),),
    )


@pytest.mark.asyncio
async def test_note_handler_with_title_and_body(tmp_path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    handlers = BotHandlers(
        settings=build_settings(),
        orchestrator=FakeOrchestrator(),
        state_store=store,
    )
    update = FakeUpdate("/note estudos /reuniao definir pauta")
    bot = FakeBot()
    context = FakeContext(args=["estudos", "/reuniao", "definir", "pauta"], bot=bot)

    await handlers.note_handler(update, context)

    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == -1001
    assert "reuniao" in bot.sent[0]["text"]
    assert any("Nota salva em estudos" in reply for reply in update.message.replies)


@pytest.mark.asyncio
async def test_note_handler_simple_note(tmp_path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    handlers = BotHandlers(
        settings=build_settings(),
        orchestrator=FakeOrchestrator(),
        state_store=store,
    )
    update = FakeUpdate("/note estudos revisar contrato")
    bot = FakeBot()
    context = FakeContext(args=["estudos", "revisar", "contrato"], bot=bot)

    await handlers.note_handler(update, context)

    assert len(bot.sent) == 1
    assert "revisar contrato" in bot.sent[0]["text"]


@pytest.mark.asyncio
async def test_note_handler_missing_tab_mapping_shows_loaded_tabs(tmp_path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    settings = build_settings()
    settings = Settings(**{**settings.__dict__, "note_tab_chat_ids": (("estudos", -1001), ("geral", -1002))})
    handlers = BotHandlers(
        settings=settings,
        orchestrator=FakeOrchestrator(),
        state_store=store,
    )
    update = FakeUpdate("/note life /titulo texto")
    bot = FakeBot()
    context = FakeContext(args=["life", "/titulo", "texto"], bot=bot)

    await handlers.note_handler(update, context)

    assert len(bot.sent) == 0
    assert any("sem mapeamento para aba 'life'" in reply for reply in update.message.replies)
    assert any("Abas carregadas: estudos, geral" in reply for reply in update.message.replies)


@pytest.mark.asyncio
async def test_note_handler_chat_not_found_returns_user_friendly_message(tmp_path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    handlers = BotHandlers(
        settings=build_settings(),
        orchestrator=FakeOrchestrator(),
        state_store=store,
    )
    update = FakeUpdate("/note estudos /titulo texto")
    bot = FailingBot()
    context = FakeContext(args=["estudos", "/titulo", "texto"], bot=bot)

    await handlers.note_handler(update, context)

    assert any("Falha ao enviar para aba 'estudos'" in reply for reply in update.message.replies)
    assert any(
        "Verifique NOTE_TAB_CHAT_IDS_JSON com IDs reais." in reply
        for reply in update.message.replies
    )
