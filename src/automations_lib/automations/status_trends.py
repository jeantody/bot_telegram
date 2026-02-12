from __future__ import annotations

from datetime import timezone
import html

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.providers.trends_provider import TrendsProvider


class StatusTrendsAutomation:
    name = "status_trends"
    trigger = "status"

    def __init__(self, provider: TrendsProvider) -> None:
        self._provider = provider

    async def run(self, context: AutomationContext) -> AutomationResult:
        snapshot = await self._provider.fetch_top_trends(
            primary_url=context.settings.trends_primary_url,
            fallback_url=context.settings.trends_fallback_url,
            limit=10,
        )
        lines = [
            "<b>Trending Topics (Brasil)</b>",
            (
                "Fonte publica alternativa (nao personalizada da sua conta X): "
                f"<a href=\"{html.escape(snapshot.source_url, quote=True)}\">"
                f"{html.escape(snapshot.source_name)}</a>"
            ),
        ]
        for idx, topic in enumerate(snapshot.trends, start=1):
            lines.append(f"{idx}. {html.escape(topic)}")

        return AutomationResult(
            title="Trends",
            message="\n".join(lines),
            source_label=snapshot.source_name,
            generated_at=context.utc_now().astimezone(timezone.utc),
            ok=True,
        )

