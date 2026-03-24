from __future__ import annotations

from dataclasses import dataclass
import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import html
import logging
from pathlib import Path
from time import struct_time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
    published_at: datetime | None = None


@dataclass(frozen=True)
class NewsBundle:
    tecnoblog: list[NewsItem]
    tecnoblog_popular: list[NewsItem]
    hackread_today: list[NewsItem]
    hackread_yesterday: list[NewsItem]
    boletimsec: list[NewsItem]
    g1: list[NewsItem]
    tecmundo: list[NewsItem]


class NewsProvider:
    TECNOBLOG_FEED = "https://tecnoblog.net/noticias/feed/"
    TECNOBLOG_HOME = "https://tecnoblog.net/"
    HACKREAD_FEED = "https://hackread.com/feed/"
    G1_FEED = "https://g1.globo.com/rss/g1/"
    TECMUNDO_FEED = "https://rss.tecmundo.com.br/feed"
    BOLETIMSEC_FEED = "https://boletimsec.com/feed/"
    BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(
        self,
        timeout_seconds: int,
        blocklist_path: str | Path | None = None,
        translator=None,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._blocklist_path = (
            Path(blocklist_path) if blocklist_path is not None else DEFAULT_BLOCKLIST_PATH
        )
        self._translator = translator
        self._translation_cache: dict[str, str] = {}

    async def fetch_news(self, *, timezone_name: str = "America/Sao_Paulo") -> NewsBundle:
        blocked_terms = self.load_blocked_terms(self._blocklist_path)
        self._translation_cache = {}
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            headers=self.BROWSER_HEADERS,
            follow_redirects=True,
        ) as client:
            responses = await asyncio.gather(
                client.get(self.TECNOBLOG_FEED),
                client.get(self.TECNOBLOG_HOME),
                client.get(self.HACKREAD_FEED),
                client.get(self.BOLETIMSEC_FEED),
                client.get(self.G1_FEED),
                client.get(self.TECMUNDO_FEED),
                return_exceptions=True,
            )

        tecnoblog_feed_response = self._require_response(
            responses[0],
            url=self.TECNOBLOG_FEED,
        )
        hackread_feed_response = self._require_response(
            responses[2],
            url=self.HACKREAD_FEED,
        )
        boletimsec_response = self._require_response(
            responses[3],
            url=self.BOLETIMSEC_FEED,
        )
        g1_response = self._require_response(
            responses[4],
            url=self.G1_FEED,
        )
        tecmundo_response = self._require_response(
            responses[5],
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
        hackread_items = self.parse_feed_items(
            hackread_feed_response.text,
            limit=None,
        )
        hackread_today_items, hackread_yesterday_items = (
            await self._translate_and_filter_hackread_items(
                hackread_items,
                blocked_terms=blocked_terms,
                timezone_name=timezone_name,
            )
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
            hackread_today=hackread_today_items,
            hackread_yesterday=hackread_yesterday_items,
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
        limit: int | None,
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
            items.append(
                NewsItem(
                    title=title,
                    link=link,
                    published_at=NewsProvider._extract_published_at(entry),
                )
            )
            if limit is not None and len(items) >= limit:
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

    async def _translate_and_filter_hackread_items(
        self,
        items: list[NewsItem],
        *,
        blocked_terms: tuple[str, ...],
        timezone_name: str,
    ) -> tuple[list[NewsItem], list[NewsItem]]:
        tzinfo = self._resolve_timezone(timezone_name)
        today = self._now_in_timezone(tzinfo).date()
        yesterday = today - timedelta(days=1)
        today_items: list[NewsItem] = []
        yesterday_items: list[NewsItem] = []

        for item in items:
            if item.published_at is None:
                continue
            published_local = item.published_at.astimezone(tzinfo).date()
            if published_local not in {today, yesterday}:
                continue
            translated_title = await self._translate_text(item.title)
            if self._is_blocked_title(item.title, blocked_terms):
                continue
            if self._is_blocked_title(translated_title, blocked_terms):
                continue
            translated_item = NewsItem(
                title=translated_title,
                link=item.link,
                published_at=item.published_at,
            )
            if published_local == today:
                today_items.append(translated_item)
            else:
                yesterday_items.append(translated_item)

        return today_items, yesterday_items

    async def _translate_text(self, text: str) -> str:
        normalized = text.strip()
        if not normalized:
            return text
        cached = self._translation_cache.get(normalized)
        if cached is not None:
            return cached

        translator = self._get_translator()
        if translator is None:
            self._translation_cache[normalized] = text
            return text

        try:
            translated = await asyncio.to_thread(
                translator.translate,
                normalized,
                dest="pt",
            )
            if asyncio.iscoroutine(translated):
                translated = await translated
            translated_text = (getattr(translated, "text", "") or "").strip() or text
        except Exception:
            translated_text = text

        self._translation_cache[normalized] = translated_text
        return translated_text

    def _get_translator(self):
        if self._translator is not None:
            return self._translator
        try:
            from googletrans import Translator
        except Exception:
            return None
        self._translator = Translator()
        return self._translator

    @staticmethod
    def _extract_published_at(entry) -> datetime | None:
        for attr_name in ("published", "updated"):
            raw_value = getattr(entry, attr_name, "")
            if raw_value:
                try:
                    published = parsedate_to_datetime(raw_value)
                except (TypeError, ValueError, IndexError):
                    published = None
                if published is not None:
                    if published.tzinfo is None:
                        published = published.replace(tzinfo=timezone.utc)
                    return published.astimezone(timezone.utc)

        for attr_name in ("published_parsed", "updated_parsed"):
            raw_value = getattr(entry, attr_name, None)
            if isinstance(raw_value, struct_time):
                return datetime(*raw_value[:6], tzinfo=timezone.utc)
        return None

    @staticmethod
    def _resolve_timezone(timezone_name: str) -> timezone | ZoneInfo:
        try:
            return ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            if timezone_name == "America/Sao_Paulo":
                return timezone(timedelta(hours=-3))
            return timezone.utc

    @staticmethod
    def _now_in_timezone(tzinfo: timezone | ZoneInfo) -> datetime:
        return datetime.now(tzinfo)

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
