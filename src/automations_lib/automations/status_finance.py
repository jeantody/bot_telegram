from __future__ import annotations

from datetime import timezone
import html
import math

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.finance_provider import FinanceProvider, QuoteValue


class StatusFinanceAutomation:
    name = "status_finance"
    trigger = "status"

    def __init__(self, provider: FinanceProvider) -> None:
        self._provider = provider

    async def run(self, context: AutomationContext) -> AutomationResult:
        snapshot = await self._provider.fetch_snapshot(
            awesome_url=context.settings.finance_awesomeapi_url,
            yahoo_b3_url=context.settings.finance_yahoo_b3_url,
        )
        lines = [
            "<b>Cotacoes Financeiras</b>",
            self._format_currency_line("Bitcoin (BTC/BRL)", snapshot.bitcoin),
            self._format_currency_line("Dolar (USD/BRL)", snapshot.usd),
            self._format_currency_line("Euro (EUR/BRL)", snapshot.eur),
            self._format_ibov_line("B3 (IBOV)", snapshot.ibov),
        ]
        return AutomationResult(
            title="Finance",
            message="\n".join(lines),
            source_label="AwesomeAPI | Yahoo Finance",
            generated_at=context.utc_now().astimezone(timezone.utc),
            ok=True,
        )

    @staticmethod
    def _format_currency_line(label: str, quote: QuoteValue | None) -> str:
        safe_label = html.escape(label)
        if quote is None:
            return f"{safe_label}: indisponivel no momento"
        if "BTC/BRL" in label:
            price = StatusFinanceAutomation._format_number_br(quote.price, decimals=2)
        else:
            price = StatusFinanceAutomation._format_number_plain(
                quote.price, decimals=2, truncate=True
            )
        change = StatusFinanceAutomation._format_signed_pct(quote.change_pct)
        return f"{safe_label}: R$ {price} | var: {change}"

    @staticmethod
    def _format_ibov_line(label: str, quote: QuoteValue | None) -> str:
        safe_label = html.escape(label)
        if quote is None:
            return f"{safe_label}: indisponivel no momento"
        price = StatusFinanceAutomation._format_number_br(quote.price, decimals=2)
        change = StatusFinanceAutomation._format_signed_pct(quote.change_pct)
        return f"{safe_label}: {price} pts | var: {change}"

    @staticmethod
    def _format_number_br(value: float, decimals: int, truncate: bool = False) -> str:
        if truncate:
            factor = 10 ** decimals
            value = math.trunc(value * factor) / factor
        formatted = f"{value:,.{decimals}f}"
        return formatted.replace(",", "_").replace(".", ",").replace("_", ".")

    @staticmethod
    def _format_number_plain(value: float, decimals: int, truncate: bool = False) -> str:
        if truncate:
            factor = 10 ** decimals
            value = math.trunc(value * factor) / factor
        return f"{value:.{decimals}f}"

    @staticmethod
    def _format_signed_pct(value: float) -> str:
        return f"{value:+.2f}%"
