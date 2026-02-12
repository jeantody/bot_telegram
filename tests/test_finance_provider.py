from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.automations_lib.providers.finance_provider import FinanceProvider


def test_parse_awesome_quotes() -> None:
    payload = {
        "BTCBRL": {"bid": "344492", "pctChange": "0.094", "timestamp": "1770914189"},
        "USDBRL": {"bid": "5.18594", "pctChange": "-0.243485", "timestamp": "1770914180"},
        "EURBRL": {"bid": "6.1578", "pctChange": "-0.120511", "timestamp": "1770914180"},
    }

    parsed = FinanceProvider._parse_awesome(payload)

    assert parsed["BTCBRL"].price == 344492.0
    assert parsed["USDBRL"].change_pct == -0.243485
    assert parsed["EURBRL"].updated_at == datetime.fromtimestamp(1770914180, tz=timezone.utc)


def test_parse_yahoo_ibov_quote() -> None:
    payload = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "regularMarketPrice": 188233.73,
                        "chartPreviousClose": 189699.12,
                        "regularMarketTime": 1770913770,
                    }
                }
            ]
        }
    }

    quote = FinanceProvider._parse_yahoo_b3(payload)

    assert quote.symbol == "IBOV"
    assert quote.price == 188233.73
    assert quote.change_pct == pytest.approx(-0.7725, rel=1e-3)
    assert quote.updated_at == datetime.fromtimestamp(1770913770, tz=timezone.utc)


@pytest.mark.asyncio
async def test_fetch_snapshot_keeps_partial_data_when_yahoo_fails(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def get(self, url: str):
            if "awesomeapi" in url:
                return FakeResponse(
                    {
                        "BTCBRL": {"bid": "100", "pctChange": "1", "timestamp": "1770914189"},
                        "USDBRL": {"bid": "5", "pctChange": "2", "timestamp": "1770914189"},
                        "EURBRL": {"bid": "6", "pctChange": "3", "timestamp": "1770914189"},
                    }
                )
            raise RuntimeError("yahoo unavailable")

    monkeypatch.setattr(
        "src.automations_lib.providers.finance_provider.httpx.AsyncClient",
        lambda timeout: FakeClient(),
    )

    provider = FinanceProvider(timeout_seconds=10)
    snapshot = await provider.fetch_snapshot(
        awesome_url="https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        yahoo_b3_url="https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&range=1d",
    )

    assert snapshot.bitcoin is not None
    assert snapshot.usd is not None
    assert snapshot.eur is not None
    assert snapshot.ibov is None


@pytest.mark.asyncio
async def test_fetch_snapshot_uses_hg_fallback_for_ibov(monkeypatch) -> None:
    class FakeResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def get(self, url: str):
            if "awesomeapi" in url:
                return FakeResponse(
                    {
                        "BTCBRL": {"bid": "100", "pctChange": "1", "timestamp": "1770914189"},
                        "USDBRL": {"bid": "5", "pctChange": "2", "timestamp": "1770914189"},
                        "EURBRL": {"bid": "6", "pctChange": "3", "timestamp": "1770914189"},
                    }
                )
            if "query1.finance.yahoo.com" in url:
                raise RuntimeError("yahoo unavailable")
            if "api.hgbrasil.com" in url:
                return FakeResponse(
                    {
                        "results": {
                            "stocks": {
                                "IBOVESPA": {
                                    "points": 188810.44,
                                    "variation": -0.47,
                                }
                            }
                        }
                    }
                )
            raise RuntimeError("unexpected url")

    monkeypatch.setattr(
        "src.automations_lib.providers.finance_provider.httpx.AsyncClient",
        lambda timeout: FakeClient(),
    )

    provider = FinanceProvider(timeout_seconds=10)
    snapshot = await provider.fetch_snapshot(
        awesome_url="https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        yahoo_b3_url="https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&range=1d",
    )

    assert snapshot.ibov is not None
    assert snapshot.ibov.price == 188810.44
    assert snapshot.ibov.change_pct == -0.47
