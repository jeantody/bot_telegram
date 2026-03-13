from __future__ import annotations

from pathlib import Path

import pytest

from src.automations_lib.automations.status_news import StatusNewsAutomation
from src.automations_lib.providers import news_provider as news_provider_module
from src.automations_lib.providers.news_provider import NewsProvider
from src.automations_lib.providers.news_provider import NewsBundle


def build_rss(count: int) -> str:
    items = []
    for idx in range(1, count + 1):
        items.append(
            "<item>"
            f"<title>Titulo {idx}</title>"
            f"<link>https://example.com/{idx}</link>"
            "</item>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        + "".join(items)
        + "</channel></rss>"
    )


def test_parse_feed_items_applies_limit() -> None:
    xml = build_rss(12)
    items = NewsProvider.parse_feed_items(xml, limit=10)

    assert len(items) == 10
    assert items[0].title == "Titulo 1"
    assert items[9].link == "https://example.com/10"


def test_load_blocked_terms_ignores_markdown_noise(tmp_path: Path) -> None:
    block_file = tmp_path / "block.md"
    block_file.write_text(
        "\n".join(
            [
                "# cabecalho",
                "",
                "golpe",
                "- ransomware",
                "* Casa de Aposta",
                "golpe",
            ]
        ),
        encoding="utf-8",
    )

    terms = NewsProvider.load_blocked_terms(block_file)

    assert terms == ("golpe", "ransomware", "casa de aposta")


def test_parse_feed_items_filters_before_limit_and_case_insensitive() -> None:
    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        "<item><title>Golpe com PIX 1</title><link>https://example.com/1</link></item>"
        "<item><title>Titulo 2</title><link>https://example.com/2</link></item>"
        "<item><title>Casa de Aposta em alta</title><link>https://example.com/3</link></item>"
        "<item><title>Titulo 4</title><link>https://example.com/4</link></item>"
        "</channel></rss>"
    )

    items = NewsProvider.parse_feed_items(
        xml,
        limit=2,
        blocked_terms=("golpe", "casa de aposta"),
    )

    assert [item.title for item in items] == ["Titulo 2", "Titulo 4"]


def test_status_news_format_shows_sem_itens_quando_fonte_fica_vazia() -> None:
    automation = StatusNewsAutomation(provider=object())  # type: ignore[arg-type]

    message = automation._format_message(  # noqa: SLF001
        NewsBundle(
            g1=[],
            tecmundo=[],
            boletimsec=[],
        )
    )

    assert message.count("Sem itens no momento.") == 3


@pytest.mark.asyncio
async def test_fetch_news_reloads_blocklist_on_each_call(
    tmp_path: Path, monkeypatch
) -> None:
    block_file = tmp_path / "block.md"
    block_file.write_text("golpe\n", encoding="utf-8")

    xml = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        "<item><title>Golpe com PIX</title><link>https://example.com/1</link></item>"
        "<item><title>Titulo 2</title><link>https://example.com/2</link></item>"
        "</channel></rss>"
    )

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, timeout: int) -> None:
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> FakeResponse:
            del url
            return FakeResponse(xml)

    monkeypatch.setattr(news_provider_module.httpx, "AsyncClient", FakeAsyncClient)

    provider = NewsProvider(timeout_seconds=5, blocklist_path=block_file)

    first_bundle = await provider.fetch_news()
    assert [item.title for item in first_bundle.g1] == ["Titulo 2"]

    block_file.write_text("titulo 2\n", encoding="utf-8")

    second_bundle = await provider.fetch_news()
    assert [item.title for item in second_bundle.g1] == ["Golpe com PIX"]
