from __future__ import annotations

from pathlib import Path

import pytest

from src.automations_lib.automations.status_news import StatusNewsAutomation
from src.automations_lib.providers import news_provider as news_provider_module
from src.automations_lib.providers.news_provider import NewsBundle, NewsItem, NewsProvider


def build_rss(count: int, *, title_prefix: str = "Titulo") -> str:
    items = []
    for idx in range(1, count + 1):
        items.append(
            "<item>"
            f"<title>{title_prefix} {idx}</title>"
            f"<link>https://example.com/{title_prefix.lower()}/{idx}</link>"
            "</item>"
        )
    return (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        + "".join(items)
        + "</channel></rss>"
    )


def build_tecnoblog_popular_html(items: list[tuple[str, str]]) -> str:
    articles = []
    for title, link in items:
        articles.append(
            "<article class='populares-item'>"
            f"<a class='populares-link' href='{link}' title='{title}'>"
            f"<h3><span class='count'></span>{title}</h3>"
            "</a>"
            "</article>"
        )
    return (
        "<html><body>"
        "<div class='populares populares__home'>"
        "<h2>Mais Populares</h2>"
        "<div class='populares-wrapper'>"
        + "".join(articles)
        + "</div></div>"
        "</body></html>"
    )


def test_parse_feed_items_applies_limit() -> None:
    xml = build_rss(12)
    items = NewsProvider.parse_feed_items(xml, limit=10)

    assert len(items) == 10
    assert items[0].title == "Titulo 1"
    assert items[9].link == "https://example.com/titulo/10"


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


def test_parse_tecnoblog_popular_items_filters_before_limit_and_ignores_non_news() -> None:
    html = build_tecnoblog_popular_html(
        [
            ("Golpe com PIX", "https://tecnoblog.net/noticias/golpe-com-pix/"),
            ("Titulo 2", "https://tecnoblog.net/noticias/titulo-2/"),
            ("Casa de Aposta em alta", "https://tecnoblog.net/noticias/casa-de-aposta/"),
            ("Titulo 4", "https://tecnoblog.net/noticias/titulo-4/"),
            ("Achados 5", "https://tecnoblog.net/achados/promocao-5/"),
        ]
    )

    items = NewsProvider.parse_tecnoblog_popular_items(
        html,
        limit=2,
        blocked_terms=("golpe", "casa de aposta"),
    )

    assert [item.title for item in items] == ["Titulo 2", "Titulo 4"]


def test_parse_tecnoblog_popular_items_applies_limit_of_ten() -> None:
    html = build_tecnoblog_popular_html(
        [
            (
                f"Popular {idx}",
                f"https://tecnoblog.net/noticias/popular-{idx}/",
            )
            for idx in range(1, 13)
        ]
    )

    items = NewsProvider.parse_tecnoblog_popular_items(html, limit=10)

    assert len(items) == 10
    assert items[0].title == "Popular 1"
    assert items[-1].title == "Popular 10"


def test_status_news_format_shows_sections_in_requested_order() -> None:
    automation = StatusNewsAutomation(provider=object())  # type: ignore[arg-type]

    message = automation._format_message(  # noqa: SLF001
        NewsBundle(
            tecnoblog=[NewsItem(title="Tecnoblog 1", link="https://example.com/tb-1")],
            tecnoblog_popular=[
                NewsItem(title="Popular 1", link="https://example.com/pop-1")
            ],
            boletimsec=[NewsItem(title="Boletim 1", link="https://example.com/bs-1")],
            g1=[NewsItem(title="G1 1", link="https://example.com/g1-1")],
            tecmundo=[NewsItem(title="TecMundo 1", link="https://example.com/tm-1")],
        )
    )

    assert "Top 10 Tecnoblog" in message
    assert "Top 10 Mais Populares Tecnoblog" in message
    assert "Ultimas 5 BoletimSec" in message
    assert "Top 10 G1" in message
    assert "Top 10 TecMundo" in message
    assert message.index("Top 10 Tecnoblog") < message.index(
        "Top 10 Mais Populares Tecnoblog"
    )
    assert message.index("Top 10 Mais Populares Tecnoblog") < message.index(
        "Ultimas 5 BoletimSec"
    )
    assert message.index("Ultimas 5 BoletimSec") < message.index("Top 10 G1")
    assert message.index("Top 10 G1") < message.index("Top 10 TecMundo")


def test_status_news_format_shows_sem_itens_quando_fonte_fica_vazia() -> None:
    automation = StatusNewsAutomation(provider=object())  # type: ignore[arg-type]

    message = automation._format_message(  # noqa: SLF001
        NewsBundle(
            tecnoblog=[],
            tecnoblog_popular=[],
            boletimsec=[],
            g1=[],
            tecmundo=[],
        )
    )

    assert message.count("Sem itens no momento.") == 5


@pytest.mark.asyncio
async def test_fetch_news_reloads_blocklist_on_each_call(
    tmp_path: Path, monkeypatch
) -> None:
    block_file = tmp_path / "block.md"
    block_file.write_text("golpe\n", encoding="utf-8")

    xml_with_blocked = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        "<item><title>Golpe com PIX</title><link>https://example.com/1</link></item>"
        "<item><title>Titulo 2</title><link>https://example.com/2</link></item>"
        "</channel></rss>"
    )
    tecnoblog_popular_html = build_tecnoblog_popular_html(
        [
            ("Golpe em alta", "https://tecnoblog.net/noticias/golpe-em-alta/"),
            ("Popular 2", "https://tecnoblog.net/noticias/popular-2/"),
        ]
    )

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text
            self.status_code = 200

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
            if url == NewsProvider.TECNOBLOG_HOME:
                return FakeResponse(tecnoblog_popular_html)
            return FakeResponse(xml_with_blocked)

    monkeypatch.setattr(news_provider_module.httpx, "AsyncClient", FakeAsyncClient)

    provider = NewsProvider(timeout_seconds=5, blocklist_path=block_file)

    first_bundle = await provider.fetch_news()
    assert [item.title for item in first_bundle.tecnoblog] == ["Titulo 2"]
    assert [item.title for item in first_bundle.tecnoblog_popular] == ["Popular 2"]
    assert [item.title for item in first_bundle.g1] == ["Titulo 2"]

    block_file.write_text("titulo 2\npopular 2\n", encoding="utf-8")

    second_bundle = await provider.fetch_news()
    assert [item.title for item in second_bundle.tecnoblog] == ["Golpe com PIX"]
    assert [item.title for item in second_bundle.tecnoblog_popular] == ["Golpe em alta"]
