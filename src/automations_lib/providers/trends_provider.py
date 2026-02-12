from __future__ import annotations

from dataclasses import dataclass
import html
import re

from bs4 import BeautifulSoup
import httpx


@dataclass(frozen=True)
class TrendsSnapshot:
    source_name: str
    source_url: str
    trends: list[str]


class TrendsProvider:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    async def fetch_top_trends(
        self, primary_url: str, fallback_url: str, limit: int = 10
    ) -> TrendsSnapshot:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(primary_url)
                response.raise_for_status()
            trends = self.parse_getdaytrends(response.text, limit=limit)
            return TrendsSnapshot(
                source_name="GetDayTrends",
                source_url=primary_url,
                trends=trends,
            )
        except Exception:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.get(fallback_url)
                response.raise_for_status()
            trends = self.parse_trends24(response.text, limit=limit)
            return TrendsSnapshot(
                source_name="Trends24",
                source_url=fallback_url,
                trends=trends,
            )

    @staticmethod
    def parse_getdaytrends(content: str, limit: int = 10) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        anchors = soup.select("table.trends tbody tr td.main a")
        result: list[str] = []
        seen: set[str] = set()
        for anchor in anchors:
            name = html.unescape(anchor.get_text(" ", strip=True))
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
            if len(result) >= limit:
                break
        if len(result) < limit:
            raise ValueError("Falha ao extrair trends do GetDayTrends")
        return result

    @staticmethod
    def parse_trends24(content: str, limit: int = 10) -> list[str]:
        soup = BeautifulSoup(content, "html.parser")
        anchors = soup.select(".trend-card__list li .trend-name a")
        result: list[str] = []
        seen: set[str] = set()
        for anchor in anchors:
            name = html.unescape(anchor.get_text(" ", strip=True))
            if not name or name in seen:
                continue
            seen.add(name)
            result.append(name)
            if len(result) >= limit:
                break

        if len(result) >= limit:
            return result

        meta = soup.select_one("meta[name='description']")
        if meta and meta.get("content"):
            matches = re.search(r":\s*(.+?)\.", meta.get("content", ""))
            if matches:
                candidates = [c.strip() for c in matches.group(1).split(",")]
                for candidate in candidates:
                    if not candidate or candidate in seen:
                        continue
                    seen.add(candidate)
                    result.append(candidate)
                    if len(result) >= limit:
                        break

        if len(result) < limit:
            raise ValueError("Falha ao extrair trends do Trends24")
        return result

