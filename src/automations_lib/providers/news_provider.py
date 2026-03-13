from __future__ import annotations

from dataclasses import dataclass
import asyncio
import html
import logging
from pathlib import Path

import feedparser
import httpx

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parents[3]
DEFAULT_BLOCKLIST_PATH = ROOT_DIR / "block.md"


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

    def __init__(
        self,
        timeout_seconds: int,
        blocklist_path: str | Path | None = None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._blocklist_path = (
            Path(blocklist_path) if blocklist_path is not None else DEFAULT_BLOCKLIST_PATH
        )

    async def fetch_news(self) -> NewsBundle:
        blocked_terms = self.load_blocked_terms(self._blocklist_path)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            responses = await asyncio.gather(
                client.get(self.G1_FEED),
                client.get(self.TECMUNDO_FEED),
                client.get(self.BOLETIMSEC_FEED),
            )
            for response in responses:
                response.raise_for_status()

        g1_items = self.parse_feed_items(
            responses[0].text, limit=10, blocked_terms=blocked_terms
        )
        tecmundo_items = self.parse_feed_items(
            responses[1].text, limit=10, blocked_terms=blocked_terms
        )
        boletimsec_items = self.parse_feed_items(
            responses[2].text, limit=5, blocked_terms=blocked_terms
        )
        return NewsBundle(g1=g1_items, tecmundo=tecmundo_items, boletimsec=boletimsec_items)

    @staticmethod
    def load_blocked_terms(path: str | Path) -> tuple[str, ...]:
        file_path = Path(path)
        if not file_path.exists():
            return ()
        try:
            raw_text = file_path.read_text(encoding="utf-8")
        except OSError:
            logger.warning(
                "failed to read news blocklist",
                extra={"event": "news_blocklist_read_error", "path": str(file_path)},
                exc_info=True,
            )
            return ()

        terms: list[str] = []
        seen: set[str] = set()
        for raw_line in raw_text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("- ") or line.startswith("* "):
                line = line[2:].strip()
            if not line or line.startswith("#"):
                continue
            normalized = line.casefold()
            if normalized in seen:
                continue
            seen.add(normalized)
            terms.append(normalized)
        return tuple(terms)

    @staticmethod
    def parse_feed_items(
        feed_xml: str,
        limit: int,
        blocked_terms: tuple[str, ...] | None = None,
    ) -> list[NewsItem]:
        parsed = feedparser.parse(feed_xml)
        items: list[NewsItem] = []
        for entry in parsed.entries:
            title = html.unescape(getattr(entry, "title", "")).strip()
            link = getattr(entry, "link", "").strip()
            if not title or not link:
                continue
            if NewsProvider._is_blocked_title(title, blocked_terms or ()):
                continue
            items.append(NewsItem(title=title, link=link))
            if len(items) >= limit:
                break
        return items

    @staticmethod
    def _is_blocked_title(title: str, blocked_terms: tuple[str, ...]) -> bool:
        if not blocked_terms:
            return False
        normalized_title = title.casefold()
        return any(term and term in normalized_title for term in blocked_terms)
