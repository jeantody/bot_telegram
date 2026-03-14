from __future__ import annotations

from dataclasses import dataclass
import asyncio
import html
import logging
from pathlib import Path

from bs4 import BeautifulSoup
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
    tecnoblog: list[NewsItem]
    tecnoblog_popular: list[NewsItem]
    boletimsec: list[NewsItem]
    g1: list[NewsItem]
    tecmundo: list[NewsItem]


class NewsProvider:
    TECNOBLOG_FEED = "https://tecnoblog.net/noticias/feed/"
    TECNOBLOG_HOME = "https://tecnoblog.net/"
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
                client.get(self.TECNOBLOG_FEED),
                client.get(self.TECNOBLOG_HOME),
                client.get(self.BOLETIMSEC_FEED),
                client.get(self.G1_FEED),
                client.get(self.TECMUNDO_FEED),
                return_exceptions=True,
            )

        tecnoblog_feed_response = self._require_response(
            responses[0],
            url=self.TECNOBLOG_FEED,
        )
        boletimsec_response = self._require_response(
            responses[2],
            url=self.BOLETIMSEC_FEED,
        )
        g1_response = self._require_response(
            responses[3],
            url=self.G1_FEED,
        )
        tecmundo_response = self._require_response(
            responses[4],
            url=self.TECMUNDO_FEED,
        )

        tecnoblog_items = self.parse_feed_items(
            tecnoblog_feed_response.text,
            limit=10,
            blocked_terms=blocked_terms,
        )
        tecnoblog_popular_items = self._parse_tecnoblog_popular_response(
            responses[1],
            blocked_terms=blocked_terms,
        )
        boletimsec_items = self.parse_feed_items(
            boletimsec_response.text,
            limit=5,
            blocked_terms=blocked_terms,
        )
        g1_items = self.parse_feed_items(
            g1_response.text,
            limit=10,
            blocked_terms=blocked_terms,
        )
        tecmundo_items = self.parse_feed_items(
            tecmundo_response.text,
            limit=10,
            blocked_terms=blocked_terms,
        )
        return NewsBundle(
            tecnoblog=tecnoblog_items,
            tecnoblog_popular=tecnoblog_popular_items,
            boletimsec=boletimsec_items,
            g1=g1_items,
            tecmundo=tecmundo_items,
        )

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

    @classmethod
    def parse_tecnoblog_popular_items(
        cls,
        html_text: str,
        limit: int,
        blocked_terms: tuple[str, ...] | None = None,
    ) -> list[NewsItem]:
        soup = BeautifulSoup(html_text, "html.parser")
        items: list[NewsItem] = []
        seen_links: set[str] = set()
        selectors = (
            "div.populares.populares__home a.populares-link[href]",
            "div.populares-wrapper a.populares-link[href]",
        )
        for selector in selectors:
            for link_tag in soup.select(selector):
                link = link_tag.get("href", "").strip()
                if not link or "/noticias/" not in link or link in seen_links:
                    continue
                title = html.unescape(
                    (link_tag.get("title") or link_tag.get_text(" ", strip=True))
                ).strip()
                if not title:
                    continue
                if cls._is_blocked_title(title, blocked_terms or ()):
                    continue
                seen_links.add(link)
                items.append(NewsItem(title=title, link=link))
                if len(items) >= limit:
                    return items
            if items:
                return items
        return items

    @staticmethod
    def _is_blocked_title(title: str, blocked_terms: tuple[str, ...]) -> bool:
        if not blocked_terms:
            return False
        normalized_title = title.casefold()
        return any(term and term in normalized_title for term in blocked_terms)

    @staticmethod
    def _require_response(
        response_or_error: httpx.Response | Exception,
        *,
        url: str,
    ) -> httpx.Response:
        if isinstance(response_or_error, Exception):
            raise RuntimeError(f"failed to fetch news source: {url}") from response_or_error
        response_or_error.raise_for_status()
        return response_or_error

    @classmethod
    def _parse_tecnoblog_popular_response(
        cls,
        response_or_error: httpx.Response | Exception,
        *,
        blocked_terms: tuple[str, ...],
    ) -> list[NewsItem]:
        if isinstance(response_or_error, Exception):
            logger.warning(
                "failed to fetch tecnoblog popular news",
                extra={
                    "event": "tecnoblog_popular_fetch_error",
                    "url": cls.TECNOBLOG_HOME,
                },
                exc_info=(
                    type(response_or_error),
                    response_or_error,
                    response_or_error.__traceback__,
                ),
            )
            return []
        try:
            response_or_error.raise_for_status()
        except httpx.HTTPError:
            logger.warning(
                "tecnoblog popular source returned error",
                extra={
                    "event": "tecnoblog_popular_http_error",
                    "url": cls.TECNOBLOG_HOME,
                    "status_code": response_or_error.status_code,
                },
                exc_info=True,
            )
            return []
        return cls.parse_tecnoblog_popular_items(
            response_or_error.text,
            limit=10,
            blocked_terms=blocked_terms,
        )
