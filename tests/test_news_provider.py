from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

from src.automations_lib.models import AutomationContext
from src.automations_lib.automations.status_news import StatusNewsAutomation
from src.automations_lib.providers import news_provider as news_provider_module
from src.automations_lib.providers.news_provider import NewsBundle, NewsItem, NewsProvider
from src.config import Settings


def build_rss(
    count: int,
    *,
    title_prefix: str = "Titulo",
    published_dates: list[str] | None = None,
) -> str:
    items = []
    for idx in range(1, count + 1):
        published = ""
        if published_dates is not None:
            published = f"<pubDate>{published_dates[idx - 1]}</pubDate>"
        items.append(
            "<item>"
            f"<title>{title_prefix} {idx}</title>"
            f"<link>https://example.com/{title_prefix.lower()}/{idx}</link>"
            f"{published}"
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


def build_settings() -> Settings:
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
        bot_timezone="America/Sao_Paulo",
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
            hackread_today=[NewsItem(title="Hackread Hoje", link="https://example.com/hr-1")],
            hackread_yesterday=[
                NewsItem(title="Hackread Ontem", link="https://example.com/hr-2")
            ],
            boletimsec=[NewsItem(title="Boletim 1", link="https://example.com/bs-1")],
            g1=[NewsItem(title="G1 1", link="https://example.com/g1-1")],
            tecmundo=[NewsItem(title="TecMundo 1", link="https://example.com/tm-1")],
        )
    )

    assert "Top 10 Tecnoblog" in message
    assert "Top 10 Mais Populares Tecnoblog" in message
    assert "Hackread Hoje" in message
    assert "Hackread Ontem" in message
    assert "Ultimas 5 BoletimSec" in message
    assert "Top 10 G1" in message
    assert "Top 10 TecMundo" in message
    assert message.index("Top 10 Tecnoblog") < message.index(
        "Top 10 Mais Populares Tecnoblog"
    )
    assert message.index("Top 10 Mais Populares Tecnoblog") < message.index(
        "Hackread Hoje"
    )
    assert message.index("Hackread Hoje") < message.index("Hackread Ontem")
    assert message.index("Hackread Ontem") < message.index(
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
            hackread_today=[],
            hackread_yesterday=[],
            boletimsec=[],
            g1=[],
            tecmundo=[],
        )
    )

    assert message.count("Sem itens no momento.") == 7


@pytest.mark.asyncio
async def test_status_news_run_updates_source_label_with_hackread() -> None:
    bundle = NewsBundle(
        tecnoblog=[],
        tecnoblog_popular=[],
        hackread_today=[],
        hackread_yesterday=[],
        boletimsec=[],
        g1=[],
        tecmundo=[],
    )

    class FakeProvider:
        def __init__(self) -> None:
            self.timezone_name = None

        async def fetch_news(self, *, timezone_name: str = "America/Sao_Paulo"):
            self.timezone_name = timezone_name
            return bundle

    provider = FakeProvider()
    automation = StatusNewsAutomation(provider=provider)  # type: ignore[arg-type]

    result = await automation.run(AutomationContext(settings=build_settings()))

    assert provider.timezone_name == "America/Sao_Paulo"
    assert result.source_label == "Tecnoblog | Hackread | BoletimSec | G1 | TecMundo"


@pytest.mark.asyncio
async def test_fetch_news_includes_hackread_today_and_yesterday_with_translation(
    tmp_path: Path, monkeypatch
) -> None:
    block_file = tmp_path / "block.md"
    block_file.write_text("", encoding="utf-8")

    fixed_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        NewsProvider,
        "_now_in_timezone",
        staticmethod(lambda tzinfo: fixed_now.astimezone(tzinfo)),
    )

    hackread_feed = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        f"<item><title>Attack Today</title><link>https://hackread.com/today</link><pubDate>{format_datetime(datetime(2026, 3, 14, 12, 37, tzinfo=timezone.utc))}</pubDate></item>"
        f"<item><title>Attack Yesterday</title><link>https://hackread.com/yesterday</link><pubDate>{format_datetime(datetime(2026, 3, 13, 20, 37, tzinfo=timezone.utc))}</pubDate></item>"
        f"<item><title>Old Story</title><link>https://hackread.com/old</link><pubDate>{format_datetime(datetime(2026, 3, 12, 12, 0, tzinfo=timezone.utc))}</pubDate></item>"
        "</channel></rss>"
    )
    normal_feed = build_rss(2)
    tecnoblog_popular_html = build_tecnoblog_popular_html(
        [("Popular 1", "https://tecnoblog.net/noticias/popular-1/")]
    )

    class FakeTranslator:
        def translate(self, text: str, dest: str):
            del dest

            class Result:
                def __init__(self, value: str) -> None:
                    self.text = value

            return Result(f"PT: {text}")

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> FakeResponse:
            if url == NewsProvider.TECNOBLOG_HOME:
                return FakeResponse(tecnoblog_popular_html)
            if url == NewsProvider.HACKREAD_FEED:
                return FakeResponse(hackread_feed)
            return FakeResponse(normal_feed)

    monkeypatch.setattr(news_provider_module.httpx, "AsyncClient", FakeAsyncClient)

    provider = NewsProvider(
        timeout_seconds=5,
        blocklist_path=block_file,
        translator=FakeTranslator(),
    )

    bundle = await provider.fetch_news(timezone_name="America/Sao_Paulo")

    assert [item.title for item in bundle.hackread_today] == ["PT: Attack Today"]
    assert [item.title for item in bundle.hackread_yesterday] == [
        "PT: Attack Yesterday"
    ]


@pytest.mark.asyncio
async def test_fetch_news_filters_hackread_by_original_and_translated_title(
    tmp_path: Path, monkeypatch
) -> None:
    block_file = tmp_path / "block.md"
    block_file.write_text("brecha\nattack yesterday\n", encoding="utf-8")

    fixed_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        NewsProvider,
        "_now_in_timezone",
        staticmethod(lambda tzinfo: fixed_now.astimezone(tzinfo)),
    )

    hackread_feed = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        f"<item><title>Attack Today</title><link>https://hackread.com/today</link><pubDate>{format_datetime(datetime(2026, 3, 14, 12, 37, tzinfo=timezone.utc))}</pubDate></item>"
        f"<item><title>Attack Yesterday</title><link>https://hackread.com/yesterday</link><pubDate>{format_datetime(datetime(2026, 3, 13, 20, 37, tzinfo=timezone.utc))}</pubDate></item>"
        "</channel></rss>"
    )
    normal_feed = build_rss(1)
    tecnoblog_popular_html = build_tecnoblog_popular_html(
        [("Popular 1", "https://tecnoblog.net/noticias/popular-1/")]
    )

    class FakeTranslator:
        def translate(self, text: str, dest: str):
            del dest

            class Result:
                def __init__(self, value: str) -> None:
                    self.text = value

            if text == "Attack Today":
                return Result("Brecha hoje")
            return Result(f"PT: {text}")

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> FakeResponse:
            if url == NewsProvider.TECNOBLOG_HOME:
                return FakeResponse(tecnoblog_popular_html)
            if url == NewsProvider.HACKREAD_FEED:
                return FakeResponse(hackread_feed)
            return FakeResponse(normal_feed)

    monkeypatch.setattr(news_provider_module.httpx, "AsyncClient", FakeAsyncClient)

    provider = NewsProvider(
        timeout_seconds=5,
        blocklist_path=block_file,
        translator=FakeTranslator(),
    )

    bundle = await provider.fetch_news(timezone_name="America/Sao_Paulo")

    assert bundle.hackread_today == []
    assert bundle.hackread_yesterday == []


@pytest.mark.asyncio
async def test_fetch_news_keeps_hackread_original_title_when_translation_fails(
    tmp_path: Path, monkeypatch
) -> None:
    block_file = tmp_path / "block.md"
    block_file.write_text("", encoding="utf-8")

    fixed_now = datetime(2026, 3, 14, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(
        NewsProvider,
        "_now_in_timezone",
        staticmethod(lambda tzinfo: fixed_now.astimezone(tzinfo)),
    )

    hackread_feed = (
        "<?xml version='1.0' encoding='UTF-8'?>"
        "<rss version='2.0'><channel>"
        f"<item><title>Fallback Story</title><link>https://hackread.com/fallback</link><pubDate>{format_datetime(datetime(2026, 3, 14, 12, 37, tzinfo=timezone.utc))}</pubDate></item>"
        "</channel></rss>"
    )
    normal_feed = build_rss(1)
    tecnoblog_popular_html = build_tecnoblog_popular_html(
        [("Popular 1", "https://tecnoblog.net/noticias/popular-1/")]
    )

    class BrokenTranslator:
        def translate(self, text: str, dest: str):
            del text, dest
            raise RuntimeError("translator down")

    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text
            self.status_code = 200

        def raise_for_status(self) -> None:
            return None

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            del args, kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> FakeResponse:
            if url == NewsProvider.TECNOBLOG_HOME:
                return FakeResponse(tecnoblog_popular_html)
            if url == NewsProvider.HACKREAD_FEED:
                return FakeResponse(hackread_feed)
            return FakeResponse(normal_feed)

    monkeypatch.setattr(news_provider_module.httpx, "AsyncClient", FakeAsyncClient)

    provider = NewsProvider(
        timeout_seconds=5,
        blocklist_path=block_file,
        translator=BrokenTranslator(),
    )

    bundle = await provider.fetch_news(timezone_name="America/Sao_Paulo")

    assert [item.title for item in bundle.hackread_today] == ["Fallback Story"]


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
        def __init__(self, *args, **kwargs) -> None:
            self.timeout = kwargs.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        async def get(self, url: str) -> FakeResponse:
            if url == NewsProvider.TECNOBLOG_HOME:
                return FakeResponse(tecnoblog_popular_html)
            if url == NewsProvider.HACKREAD_FEED:
                return FakeResponse(build_rss(1, title_prefix="Hackread"))
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
