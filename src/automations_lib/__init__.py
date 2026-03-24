"""Automation library for Telegram bot commands."""

from src.automations_lib.base import Automation
from src.automations_lib.models import AutomationContext, AutomationResult
from src.automations_lib.orchestrator import StatusOrchestrator
from src.automations_lib.registry import AutomationRegistry

__all__ = [
    "Automation",
    "AutomationContext",
    "AutomationResult",
    "AutomationRegistry",
    "StatusOrchestrator",
]

