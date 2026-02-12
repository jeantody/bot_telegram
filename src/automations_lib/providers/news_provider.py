from __future__ import annotations

from dataclasses import dataclass
import html
import asyncio

import feedparser
import httpx


@dataclass(frozen=True)
class NewsItem:
    title: str
    link: str


@dataclass(frozen=True)
class NewsBundle:
    g1: list[NewsItem]
    tecmundo: list[NewsItem]
    boletimsec: list[NewsItem]


class NewsProvider:
    G1_FEED = "https://g1.globo.com/rss/g1/"
    TECMUNDO_FEED = "https://rss.tecmundo.com.br/feed"
    BOLETIMSEC_FEED = "https://boletimsec.com/feed/"

    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    async def fetch_news(self) -> NewsBundle:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            responses = await asyncio.gather(
                client.get(self.G1_FEED),
                client.get(self.TECMUNDO_FEED),
                client.get(self.BOLETIMSEC_FEED),
            )
            for response in responses:
                response.raise_for_status()

        g1_items = self.parse_feed_items(responses[0].text, limit=10)
        tecmundo_items = self.parse_feed_items(responses[1].text, limit=10)
        boletimsec_items = self.parse_feed_items(responses[2].text, limit=5)
        return NewsBundle(g1=g1_items, tecmundo=tecmundo_items, boletimsec=boletimsec_items)

    @staticmethod
    def parse_feed_items(feed_xml: str, limit: int) -> list[NewsItem]:
        parsed = feedparser.parse(feed_xml)
        items: list[NewsItem] = []
        for entry in parsed.entries[:limit]:
            title = html.unescape(getattr(entry, "title", "")).strip()
            link = getattr(entry, "link", "").strip()
            if not title or not link:
                continue
            items.append(NewsItem(title=title, link=link))
        return items
