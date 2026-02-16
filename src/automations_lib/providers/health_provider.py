from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter

import httpx


@dataclass(frozen=True)
class HealthProbe:
    source: str
    url: str
    ok: bool
    status_code: int | None
    latency_ms: int | None
    error: str | None


class HealthProvider:
    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    async def fetch_health(self, probes: list[tuple[str, str]]) -> list[HealthProbe]:
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
        ) as client:
            results = await asyncio.gather(
                *(self._run_single_probe(client, source, url) for source, url in probes)
            )
        return list(results)

    async def _run_single_probe(
        self,
        client: httpx.AsyncClient,
        source: str,
        url: str,
    ) -> HealthProbe:
        start = perf_counter()
        try:
            response = await client.get(url)
            elapsed_ms = int((perf_counter() - start) * 1000)
            return HealthProbe(
                source=source,
                url=url,
                ok=200 <= response.status_code < 400,
                status_code=int(response.status_code),
                latency_ms=elapsed_ms,
                error=None,
            )
        except Exception as exc:
            elapsed_ms = int((perf_counter() - start) * 1000)
            return HealthProbe(
                source=source,
                url=url,
                ok=False,
                status_code=None,
                latency_ms=elapsed_ms,
                error=str(exc),
            )

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)

