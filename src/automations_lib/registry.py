from __future__ import annotations

from src.automations_lib.base import Automation


class AutomationRegistry:
    def __init__(self) -> None:
        self._automations: list[Automation] = []

    def register(self, automation: Automation) -> None:
        self._automations.append(automation)

    def get_by_trigger(self, trigger: str) -> list[Automation]:
        normalized = trigger.strip().lower()
        return [a for a in self._automations if a.trigger.strip().lower() == normalized]
