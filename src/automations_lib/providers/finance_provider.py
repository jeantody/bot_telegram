from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx


@dataclass(frozen=True)
class QuoteValue:
    symbol: str
    price: float
    change_pct: float
    updated_at: datetime | None


@dataclass(frozen=True)
class FinanceSnapshot:
    bitcoin: QuoteValue | None
    usd: QuoteValue | None
    eur: QuoteValue | None
    ibov: QuoteValue | None


class FinanceProvider:
    HGBRASIL_B3_URL = "https://api.hgbrasil.com/finance?format=json-cors&key=00000000"

    def __init__(self, timeout_seconds: int) -> None:
        self._timeout_seconds = timeout_seconds

    async def fetch_snapshot(self, awesome_url: str, yahoo_b3_url: str) -> FinanceSnapshot:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            awesome_result, yahoo_result = await asyncio.gather(
                client.get(awesome_url),
                client.get(yahoo_b3_url),
                return_exceptions=True,
            )

            bitcoin: QuoteValue | None = None
            usd: QuoteValue | None = None
            eur: QuoteValue | None = None
            ibov: QuoteValue | None = None
            failures: list[str] = []

            if isinstance(awesome_result, Exception):
                failures.append(f"awesomeapi request: {awesome_result}")
            else:
                try:
                    awesome_result.raise_for_status()
                    parsed = self._parse_awesome(awesome_result.json())
                    bitcoin = parsed.get("BTCBRL")
                    usd = parsed.get("USDBRL")
                    eur = parsed.get("EURBRL")
                except Exception as exc:
                    failures.append(f"awesomeapi parse: {exc}")

            if isinstance(yahoo_result, Exception):
                failures.append(f"yahoo request: {yahoo_result}")
            else:
                try:
                    yahoo_result.raise_for_status()
                    ibov = self._parse_yahoo_b3(yahoo_result.json())
                except Exception as exc:
                    failures.append(f"yahoo parse: {exc}")

            if ibov is None:
                try:
                    hg_result = await client.get(self.HGBRASIL_B3_URL)
                    hg_result.raise_for_status()
                    ibov = self._parse_hg_b3(hg_result.json())
                except Exception as exc:
                    failures.append(f"hgbrasil parse: {exc}")

        snapshot = FinanceSnapshot(bitcoin=bitcoin, usd=usd, eur=eur, ibov=ibov)
        if all(value is None for value in (snapshot.bitcoin, snapshot.usd, snapshot.eur, snapshot.ibov)):
            joined = " | ".join(failures) if failures else "unknown error"
            raise ValueError(f"Nao foi possivel obter cotacoes financeiras: {joined}")
        return snapshot

    @staticmethod
    def _parse_awesome(payload: dict) -> dict[str, QuoteValue]:
        result: dict[str, QuoteValue] = {}
        for code in ("BTCBRL", "USDBRL", "EURBRL"):
            item = payload.get(code)
            if not item:
                continue
            price = float(item["bid"])
            change_pct = float(item["pctChange"])
            updated_at = FinanceProvider._awesome_updated_at(item)
            result[code] = QuoteValue(
                symbol=code,
                price=price,
                change_pct=change_pct,
                updated_at=updated_at,
            )
        return result

    @staticmethod
    def _awesome_updated_at(item: dict) -> datetime | None:
        raw_timestamp = str(item.get("timestamp", "")).strip()
        if raw_timestamp.isdigit():
            return datetime.fromtimestamp(int(raw_timestamp), tz=timezone.utc)

        raw_create_date = str(item.get("create_date", "")).strip()
        if raw_create_date:
            try:
                parsed = datetime.strptime(raw_create_date, "%Y-%m-%d %H:%M:%S")
                return parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                return None
        return None

    @staticmethod
    def _parse_yahoo_b3(payload: dict) -> QuoteValue:
        result_list = payload["chart"]["result"]
        if not result_list:
            raise ValueError("Yahoo returned empty result list")
        meta = result_list[0]["meta"]
        price = float(meta["regularMarketPrice"])
        previous = float(meta["chartPreviousClose"])
        if previous == 0:
            change_pct = 0.0
        else:
            change_pct = ((price - previous) / previous) * 100.0

        updated_at: datetime | None = None
        raw_market_time = meta.get("regularMarketTime")
        if isinstance(raw_market_time, (int, float)):
            updated_at = datetime.fromtimestamp(int(raw_market_time), tz=timezone.utc)

        return QuoteValue(
            symbol="IBOV",
            price=price,
            change_pct=change_pct,
            updated_at=updated_at,
        )

    @staticmethod
    def _parse_hg_b3(payload: dict) -> QuoteValue:
        ibov_payload = payload["results"]["stocks"]["IBOVESPA"]
        price = float(ibov_payload["points"])
        change_pct = float(ibov_payload["variation"])
        return QuoteValue(
            symbol="IBOV",
            price=price,
            change_pct=change_pct,
            updated_at=None,
        )
