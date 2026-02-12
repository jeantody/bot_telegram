from __future__ import annotations

import pytest

from src.automations_lib.providers.trends_provider import TrendsProvider


def test_parse_getdaytrends_top10() -> None:
    rows = []
    for idx in range(1, 13):
        rows.append(
            "<tr><td class='main'>"
            f"<a href='/brazil/trend/Tema{idx}/'>Tema {idx}</a>"
            "</td></tr>"
        )
    html = "<table class='trends'><tbody>" + "".join(rows) + "</tbody></table>"

    trends = TrendsProvider.parse_getdaytrends(html, limit=10)
    assert len(trends) == 10
    assert trends[0] == "Tema 1"
    assert trends[-1] == "Tema 10"


def test_parse_trends24_top10() -> None:
    list_items = []
    for idx in range(1, 11):
        list_items.append(
            "<li><div class='trend-name'>"
            f"<a href='/trend/{idx}'>Assunto {idx}</a>"
            "</div></li>"
        )
    html = "<ol class='trend-card__list'>" + "".join(list_items) + "</ol>"

    trends = TrendsProvider.parse_trends24(html, limit=10)
    assert len(trends) == 10
    assert trends[0] == "Assunto 1"
    assert trends[-1] == "Assunto 10"


@pytest.mark.asyncio
async def test_fetch_top_trends_fallback_when_primary_fails(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, text: str) -> None:
            self.text = text

        def raise_for_status(self) -> None:
            return None

    class FakeClient:
        def __init__(self, responses: list[FakeResponse]) -> None:
            self._responses = responses

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def get(self, url: str):
            del url
            return self._responses.pop(0)

    call = {"idx": 0}
    clients = [
        FakeClient([FakeResponse("<html>primary</html>")]),
        FakeClient(
            [
                FakeResponse(
                    "<ol class='trend-card__list'>"
                    + "".join(
                        f"<li><div class='trend-name'><a>T {i}</a></div></li>"
                        for i in range(1, 11)
                    )
                    + "</ol>"
                )
            ]
        ),
    ]

    def fake_async_client(*args, **kwargs):
        del args, kwargs
        idx = call["idx"]
        call["idx"] += 1
        return clients[idx]

    monkeypatch.setattr(
        "src.automations_lib.providers.trends_provider.httpx.AsyncClient",
        fake_async_client,
    )
    monkeypatch.setattr(
        TrendsProvider,
        "parse_getdaytrends",
        staticmethod(lambda content, limit=10: (_ for _ in ()).throw(ValueError("fail"))),
    )

    provider = TrendsProvider(timeout_seconds=5)
    snapshot = await provider.fetch_top_trends(
        primary_url="https://primary.example",
        fallback_url="https://fallback.example",
        limit=10,
    )

    assert snapshot.source_name == "Trends24"
    assert len(snapshot.trends) == 10
    assert snapshot.trends[0] == "T 1"

