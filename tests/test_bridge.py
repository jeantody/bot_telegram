from __future__ import annotations

import json

import httpx
import pytest

from src.bridge import BridgeNotifier, discord_text_from_telegram_html
from src.config import Settings


class FakeTelegramMessage:
    def __init__(self) -> None:
        self.replies: list[dict] = []

    async def reply_text(self, text: str, **kwargs) -> None:
        self.replies.append({"text": text, "kwargs": kwargs})


class FakeTelegramBot:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send_message(self, **kwargs) -> None:
        self.messages.append(kwargs)


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
    )
    base.update(kwargs)
    return Settings(**base)


def _make_async_client_factory(handler):
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_async_client(*args, transport=transport, **kwargs)

    return factory


def test_discord_text_from_telegram_html_converts_common_markup() -> None:
    assert discord_text_from_telegram_html(
        '<b>Status</b> <code>abc</code> <a href="https://example.com">site</a>'
    ) == "**Status** `abc` site (https://example.com)"


@pytest.mark.asyncio
async def test_reply_from_telegram_mirrors_to_discord(monkeypatch) -> None:
    seen_payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_payloads.append(json.loads(request.read().decode("utf-8")))
        return httpx.Response(204, request=request)

    monkeypatch.setattr(
        "src.bridge.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    notifier = BridgeNotifier(build_settings())
    message = FakeTelegramMessage()

    await notifier.reply(message, "<b>OK</b>")

    assert message.replies[0]["text"] == "<b>OK</b>"
    assert seen_payloads[0]["content"] == "**OK**"


@pytest.mark.asyncio
async def test_discord_incoming_mirrors_to_telegram_without_loop() -> None:
    bot = FakeTelegramBot()
    notifier = BridgeNotifier(build_settings())
    notifier.set_telegram_bot(bot)

    await notifier.mirror_incoming_discord(text="/status", username="ana")

    assert bot.messages == [
        {
            "chat_id": 123,
            "text": "<b>Discord @ana</b>\n/status",
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
    ]
