from __future__ import annotations

from typing import Protocol

from src.automations_lib.models import AutomationContext, AutomationResult


class Automation(Protocol):
    name: str
    trigger: str

    async def run(self, context: AutomationContext) -> AutomationResult:
        """Execute the automation and return a result payload."""

