from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from src.state_store import BotStateStore


def test_create_and_list_reminders_by_local_date(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    now_utc = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    reminder_id = store.create_reminder(
        chat_id=123,
        user_id=1,
        username="u",
        text="reuniao",
        remind_at_utc=now_utc,
        timezone_name="America/Sao_Paulo",
    )
    assert reminder_id > 0
    rows = store.list_reminders_by_local_date(
        chat_id=123,
        date_local=now_utc.date(),
        timezone_name="UTC",
    )
    assert len(rows) == 1
    assert rows[0]["text"] == "reuniao"


def test_due_reminders_and_mark_sent_failed(tmp_path: Path) -> None:
    store = BotStateStore(str(tmp_path / "state.db"))
    due_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    reminder_id = store.create_reminder(
        chat_id=123,
        user_id=1,
        username="u",
        text="pagar",
        remind_at_utc=due_time,
        timezone_name="America/Sao_Paulo",
    )
    due = store.list_due_reminders(
        now_utc=datetime.now(timezone.utc),
        retry_limit=3,
        limit=10,
    )
    assert any(item["id"] == reminder_id for item in due)

    store.mark_reminder_failed(reminder_id=reminder_id, error_text="timeout")
    due_after_fail = store.list_due_reminders(
        now_utc=datetime.now(timezone.utc),
        retry_limit=1,
        limit=10,
    )
    assert all(item["id"] != reminder_id for item in due_after_fail)

    store.mark_reminder_sent(reminder_id=reminder_id, sent_at_utc=datetime.now(timezone.utc))
    rows = store.list_reminders_by_local_date(
        chat_id=123,
        date_local=due_time.astimezone(timezone.utc).date(),
        timezone_name="UTC",
    )
    assert rows
    assert rows[0]["sent_at_utc"] is not None
