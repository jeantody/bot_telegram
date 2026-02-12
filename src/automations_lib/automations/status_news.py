from __future__ import annotations

from datetime import timezone
import html

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.news_provider import NewsBundle, NewsProvider


class StatusNewsAutomation:
    name = "status_news"
    trigger = "status"

    def __init__(self, provider: NewsProvider) -> None:
        self._provider = provider

    async def run(self, context: AutomationContext) -> AutomationResult:
        bundle = await self._provider.fetch_news()
        message = self._format_message(bundle)
        return AutomationResult(
            title="Noticias",
            message=message,
            source_label="G1 | TecMundo | BoletimSec",
            generated_at=context.utc_now().astimezone(timezone.utc),
            ok=True,
        )

    def _format_message(self, bundle: NewsBundle) -> str:
        sections = [
            "<b>Noticias</b>",
            "<i>Top 10 G1\n</i>",
            self._to_links(bundle.g1),
            "<i>\nTop 10 TecMundo\n</i>",
            self._to_links(bundle.tecmundo),
            "<i>\nUltimas 5 BoletimSec</i>\n",
            self._to_links(bundle.boletimsec),
        ]
        return "\n".join(sections)

    @staticmethod
    def _to_links(items: list) -> str:
        lines: list[str] = []
        for idx, item in enumerate(items, start=1):
            title = html.escape(item.title)
            link = html.escape(item.link, quote=True)
            lines.append(f"{idx}. <a href=\"{link}\">{title}</a>")
        return "\n".join(lines) if lines else "Sem itens no momento."

