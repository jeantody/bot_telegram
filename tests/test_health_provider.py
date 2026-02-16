from __future__ import annotations

import httpx
import pytest

from src.automations_lib.providers.health_provider import HealthProvider


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class FakeAsyncClient:
    def __init__(self, responses: dict[str, object], **kwargs) -> None:
        del kwargs
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    async def get(self, url: str, **kwargs):
        del kwargs
        item = self._responses[url]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_fetch_health_reports_ok_and_failure(monkeypatch) -> None:
    responses = {
        "https://ok.example": FakeResponse(200),
        "https://fail.example": httpx.ConnectError("down"),
    }
    monkeypatch.setattr(
        "src.automations_lib.providers.health_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient(responses, **kwargs),
    )
    provider = HealthProvider(timeout_seconds=5)
    probes = [("A", "https://ok.example"), ("B", "https://fail.example")]
    report = await provider.fetch_health(probes)

    assert len(report) == 2
    assert report[0].ok is True
    assert report[0].status_code == 200
    assert report[1].ok is False
    assert report[1].status_code is None
    assert report[1].error is not None

