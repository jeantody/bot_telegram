from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from src.config import Settings


@dataclass(frozen=True)
class AutomationResult:
    title: str
    message: str
    source_label: str
    generated_at: datetime
    ok: bool


@dataclass(frozen=True)
class AutomationContext:
    settings: Settings

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)

