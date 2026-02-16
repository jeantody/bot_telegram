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
    severity: str = "info"


@dataclass(frozen=True)
class AutomationContext:
    settings: Settings
    trace_id: str = "-"
    chat_id: int | None = None
    user_id: int | None = None
    username: str | None = None
    command: str | None = None

    @staticmethod
    def utc_now() -> datetime:
        return datetime.now(timezone.utc)
