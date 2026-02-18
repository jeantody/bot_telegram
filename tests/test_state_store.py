from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

from src.state_store import BotStateStore


def test_compare_and_set_state_tracks_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))

    changed, previous = store.compare_and_set_state("host:main", "v1")
    assert changed is True
    assert previous is None

    changed, previous = store.compare_and_set_state("host:main", "v1")
    assert changed is False
    assert previous == "v1"

    changed, previous = store.compare_and_set_state("host:main", "v2")
    assert changed is True
    assert previous == "v1"


def test_record_unauthorized_attempt_writes_row(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))

    store.record_unauthorized_attempt(
        chat_id=123,
        user_id=456,
        username="tester",
        command_text="/status",
        trace_id="trace-123",
    )

    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT chat_id, user_id, username, command_text, trace_id FROM unauthorized_attempts"
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] == 123
    assert row[1] == 456
    assert row[2] == "tester"
    assert row[3] == "/status"
    assert row[4] == "trace-123"


def test_record_audit_event_writes_row(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))
    store.record_audit_event(
        trace_id="t1",
        event_type="command_end",
        command="/status",
        chat_id=1,
        user_id=2,
        username="tester",
        status="ok",
        severity="info",
        payload={"x": 1},
    )
    connection = sqlite3.connect(db_path)
    row = connection.execute(
        "SELECT trace_id, event_type, command, status, severity FROM audit_log"
    ).fetchone()
    connection.close()
    assert row is not None
    assert row[0] == "t1"
    assert row[1] == "command_end"
    assert row[2] == "/status"
    assert row[3] == "ok"
    assert row[4] == "info"


def test_list_audit_events_returns_latest_first(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))
    store.record_audit_event(
        trace_id="t-old",
        event_type="event_old",
        command="/old",
        chat_id=1,
        user_id=2,
        username="u",
        status="ok",
        severity="info",
        payload=None,
    )
    store.record_audit_event(
        trace_id="t-new",
        event_type="event_new",
        command="/new",
        chat_id=1,
        user_id=2,
        username="u",
        status="ok",
        severity="info",
        payload={"k": "v"},
    )
    events = store.list_audit_events(limit=2)
    assert len(events) == 2
    assert events[0]["trace_id"] == "t-new"
    assert events[0]["payload"] == {"k": "v"}
    assert events[1]["trace_id"] == "t-old"


def test_list_audit_events_only_error_filters_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))
    store.record_audit_event(
        trace_id="t-ok",
        event_type="event_ok",
        command="/ok",
        chat_id=1,
        user_id=2,
        username="u",
        status="ok",
        severity="info",
        payload=None,
    )
    store.record_audit_event(
        trace_id="t-err",
        event_type="event_err",
        command="/err",
        chat_id=1,
        user_id=2,
        username="u",
        status="error",
        severity="alerta",
        payload=None,
    )
    events = store.list_audit_events(limit=10, only_error=True)
    assert len(events) == 1
    assert events[0]["trace_id"] == "t-err"
    assert events[0]["status"] == "error"


def test_consume_rate_limit_blocks_within_interval(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))
    key = "rate:123:/voip"
    now = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)

    allowed, retry_after = store.consume_rate_limit(key, 120, now_utc=now)
    assert allowed is True
    assert retry_after == 0

    allowed, retry_after = store.consume_rate_limit(
        key, 120, now_utc=now + timedelta(seconds=10)
    )
    assert allowed is False
    assert retry_after == 110

    allowed, retry_after = store.consume_rate_limit(
        key, 120, now_utc=now + timedelta(seconds=121)
    )
    assert allowed is True
    assert retry_after == 0


def test_record_audit_event_redacts_sensitive_payload(tmp_path: Path) -> None:
    db_path = tmp_path / "state.db"
    store = BotStateStore(str(db_path))
    store.record_audit_event(
        trace_id="t1",
        event_type="command_end",
        command="/status",
        chat_id=1,
        user_id=2,
        username="tester",
        status="ok",
        severity="info",
        payload={
            "token": "abc",
            "password": "x",
            "nested": {"secret": "y"},
            "url": "https://api.telegram.org/bot123:ABCDEF/getMe",
        },
    )
    events = store.list_audit_events(limit=1)
    assert len(events) == 1
    payload = events[0]["payload"]
    assert payload is not None
    assert payload["token"] == "<redacted>"
    assert payload["password"] == "<redacted>"
    assert payload["nested"]["secret"] == "<redacted>"
    assert "ABCDEF" not in payload["url"]
    assert "api.telegram.org/bot<redacted>" in payload["url"]
