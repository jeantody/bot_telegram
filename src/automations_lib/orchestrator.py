from __future__ import annotations

import asyncio
from datetime import timezone
import html

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.registry import AutomationRegistry


class StatusOrchestrator:
    def __init__(self, registry: AutomationRegistry, timeout_seconds: int) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def run_trigger(
        self, trigger: str, context: AutomationContext
    ) -> list[AutomationResult]:
        results: list[AutomationResult] = []
        for automation in self._registry.get_by_trigger(trigger):
            try:
                result = await asyncio.wait_for(
                    automation.run(context), timeout=self._timeout_seconds
                )
                results.append(result)
            except Exception as exc:  # pragma: no cover - defensive path
                label = getattr(automation, "name", automation.__class__.__name__)
                msg = (
                    f"<b>{html.escape(label)}</b>\n"
                    f"Falha ao executar automação: {html.escape(str(exc))}"
                )
                results.append(
                    AutomationResult(
                        title=label,
                        message=msg,
                        source_label=label,
                        generated_at=context.utc_now().astimezone(timezone.utc),
                        ok=False,
                    )
                )
        return results

