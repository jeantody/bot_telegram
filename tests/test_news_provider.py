from __future__ import annotations

from src.automations_lib.providers.news_provider import NewsProvider


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

