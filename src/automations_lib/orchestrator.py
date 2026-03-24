from __future__ import annotations

import asyncio
from datetime import timezone
import html
import logging
from time import perf_counter

from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.registry import AutomationRegistry


logger = logging.getLogger(__name__)


class StatusOrchestrator:
    def __init__(self, registry: AutomationRegistry, timeout_seconds: int) -> None:
        self._registry = registry
        self._timeout_seconds = timeout_seconds

    async def run_trigger(
        self, trigger: str, context: AutomationContext
    ) -> list[AutomationResult]:
        logger.info(
            "trigger execution started",
            extra={
                "event": "trigger_start",
                "trace_id": context.trace_id,
                "trigger": trigger,
                "chat_id": context.chat_id,
                "user_id": context.user_id,
                "username": context.username,
            },
        )
        results: list[AutomationResult] = []
        for automation in self._registry.get_by_trigger(trigger):
            start = perf_counter()
            label = getattr(automation, "name", automation.__class__.__name__)
            try:
                result = await asyncio.wait_for(
                    automation.run(context), timeout=self._timeout_seconds
                )
                elapsed_ms = int((perf_counter() - start) * 1000)
                logger.info(
                    "automation execution finished",
                    extra={
                        "event": "automation_ok",
                        "trace_id": context.trace_id,
                        "trigger": trigger,
                        "source": label,
                        "status": "ok",
                        "severity": result.severity,
                        "latency_ms": elapsed_ms,
                    },
                )
                results.append(result)
            except Exception as exc:  # pragma: no cover - defensive path
                msg = (
                    f"<b>{html.escape(label)}</b>\n"
                    f"Falha ao executar automacao: {html.escape(str(exc))}"
                )
                logger.exception(
                    "automation execution failed",
                    extra={
                        "event": "automation_error",
                        "trace_id": context.trace_id,
                        "trigger": trigger,
                        "source": label,
                        "status": "error",
                    },
                )
                results.append(
                    AutomationResult(
                        title=label,
                        message=msg,
                        source_label=label,
                        generated_at=context.utc_now().astimezone(timezone.utc),
                        ok=False,
                        severity="critico",
                    )
                )
        logger.info(
            "trigger execution finished",
            extra={
                "event": "trigger_end",
                "trace_id": context.trace_id,
                "trigger": trigger,
                "status": "ok",
                "result_count": len(results),
            },
        )
        return results


