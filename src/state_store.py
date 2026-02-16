from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class BotStateStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS monitored_state (
                    state_key TEXT PRIMARY KEY,
                    state_value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS unauthorized_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    chat_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    command_text TEXT,
                    trace_id TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    trace_id TEXT,
                    event_type TEXT NOT NULL,
                    command TEXT,
                    chat_id INTEGER,
                    user_id INTEGER,
                    username TEXT,
                    status TEXT,
                    severity TEXT,
                    payload_json TEXT
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    tab TEXT NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT,
                    source_chat_id INTEGER,
                    source_user_id INTEGER,
                    source_username TEXT,
                    target_chat_id INTEGER NOT NULL,
                    telegram_message_id INTEGER
                )
                """
            )
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    user_id INTEGER,
                    username TEXT,
                    text TEXT NOT NULL,
                    remind_at_utc TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    sent_at_utc TEXT,
                    send_attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT
                )
                """
            )
            self._connection.commit()

    def compare_and_set_state(self, key: str, value: str) -> tuple[bool, str | None]:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            row = cursor.execute(
                "SELECT state_value FROM monitored_state WHERE state_key = ?",
                (key,),
            ).fetchone()
            previous = str(row["state_value"]) if row else None
            changed = previous != value
            cursor.execute(
                """
                INSERT INTO monitored_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at=excluded.updated_at
                """,
                (key, value, now_iso),
            )
            self._connection.commit()
        return changed, previous

    def record_unauthorized_attempt(
        self,
        *,
        chat_id: int | None,
        user_id: int | None,
        username: str | None,
        command_text: str | None,
        trace_id: str,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                INSERT INTO unauthorized_attempts (
                    created_at, chat_id, user_id, username, command_text, trace_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    chat_id,
                    user_id,
                    username,
                    command_text,
                    trace_id,
                ),
            )
            self._connection.commit()

    def record_audit_event(
        self,
        *,
        trace_id: str | None,
        event_type: str,
        command: str | None,
        chat_id: int | None,
        user_id: int | None,
        username: str | None,
        status: str | None,
        severity: str | None,
        payload: dict | None = None,
    ) -> None:
        now_iso = datetime.now(timezone.utc).isoformat()
        payload_json = json.dumps(payload, ensure_ascii=False) if payload else None
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                INSERT INTO audit_log (
                    created_at, trace_id, event_type, command, chat_id, user_id,
                    username, status, severity, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    trace_id,
                    event_type,
                    command,
                    chat_id,
                    user_id,
                    username,
                    status,
                    severity,
                    payload_json,
                ),
            )
            self._connection.commit()

    def create_note(
        self,
        *,
        tab: str,
        title: str,
        body: str,
        source_chat_id: int | None,
        source_user_id: int | None,
        source_username: str | None,
        target_chat_id: int,
        telegram_message_id: int | None,
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                INSERT INTO notes (
                    created_at, tab, title, body, source_chat_id, source_user_id,
                    source_username, target_chat_id, telegram_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    tab,
                    title,
                    body,
                    source_chat_id,
                    source_user_id,
                    source_username,
                    target_chat_id,
                    telegram_message_id,
                ),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    def create_reminder(
        self,
        *,
        chat_id: int,
        user_id: int | None,
        username: str | None,
        text: str,
        remind_at_utc: datetime,
        timezone_name: str,
    ) -> int:
        now_iso = datetime.now(timezone.utc).isoformat()
        remind_at_iso = remind_at_utc.astimezone(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                INSERT INTO reminders (
                    created_at, chat_id, user_id, username, text, remind_at_utc,
                    timezone
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now_iso,
                    chat_id,
                    user_id,
                    username,
                    text,
                    remind_at_iso,
                    timezone_name,
                ),
            )
            self._connection.commit()
            return int(cursor.lastrowid)

    def list_reminders_by_local_date(
        self,
        *,
        chat_id: int,
        date_local: date,
        timezone_name: str,
    ) -> list[dict]:
        tzinfo = _resolve_timezone(timezone_name)
        local_start = datetime.combine(date_local, time.min, tzinfo=tzinfo)
        local_end = datetime.combine(date_local, time.max, tzinfo=tzinfo)
        start_utc = local_start.astimezone(timezone.utc).isoformat()
        end_utc = local_end.astimezone(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            rows = cursor.execute(
                """
                SELECT id, chat_id, user_id, username, text, remind_at_utc, timezone,
                       sent_at_utc, send_attempts, last_error
                FROM reminders
                WHERE chat_id = ?
                  AND remind_at_utc >= ?
                  AND remind_at_utc <= ?
                ORDER BY remind_at_utc ASC
                """,
                (chat_id, start_utc, end_utc),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def list_due_reminders(
        self,
        *,
        now_utc: datetime,
        retry_limit: int,
        limit: int = 100,
    ) -> list[dict]:
        now_iso = now_utc.astimezone(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            rows = cursor.execute(
                """
                SELECT id, chat_id, user_id, username, text, remind_at_utc, timezone,
                       sent_at_utc, send_attempts, last_error
                FROM reminders
                WHERE sent_at_utc IS NULL
                  AND remind_at_utc <= ?
                  AND send_attempts < ?
                ORDER BY remind_at_utc ASC
                LIMIT ?
                """,
                (now_iso, retry_limit, limit),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]

    def mark_reminder_sent(
        self,
        *,
        reminder_id: int,
        sent_at_utc: datetime,
    ) -> None:
        sent_iso = sent_at_utc.astimezone(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                UPDATE reminders
                SET sent_at_utc = ?, last_error = NULL
                WHERE id = ?
                """,
                (sent_iso, reminder_id),
            )
            self._connection.commit()

    def mark_reminder_failed(
        self,
        *,
        reminder_id: int,
        error_text: str,
    ) -> None:
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                UPDATE reminders
                SET send_attempts = send_attempts + 1, last_error = ?
                WHERE id = ?
                """,
                (error_text[:500], reminder_id),
            )
            self._connection.commit()

    def list_audit_events(self, *, limit: int = 20, only_error: bool = False) -> list[dict]:
        safe_limit = max(1, min(200, int(limit)))
        where_clause = "WHERE lower(coalesce(status, '')) = 'error'" if only_error else ""
        with self._lock:
            cursor = self._connection.cursor()
            rows = cursor.execute(
                f"""
                SELECT created_at, trace_id, event_type, command, chat_id, user_id,
                       username, status, severity, payload_json
                FROM audit_log
                {where_clause}
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        events: list[dict] = []
        for row in rows:
            payload_json = row["payload_json"]
            payload = None
            if payload_json:
                try:
                    payload = json.loads(payload_json)
                except json.JSONDecodeError:
                    payload = None
            events.append(
                {
                    "created_at": row["created_at"],
                    "trace_id": row["trace_id"],
                    "event_type": row["event_type"],
                    "command": row["command"],
                    "chat_id": row["chat_id"],
                    "user_id": row["user_id"],
                    "username": row["username"],
                    "status": row["status"],
                    "severity": row["severity"],
                    "payload": payload,
                }
            )
        return events

def _resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            return timezone(timedelta(hours=-3))
        return timezone.utc


def _row_to_dict(row: sqlite3.Row) -> dict:
    return {
        "id": int(row["id"]),
        "chat_id": int(row["chat_id"]),
        "user_id": int(row["user_id"]) if row["user_id"] is not None else None,
        "username": row["username"],
        "text": row["text"],
        "remind_at_utc": row["remind_at_utc"],
        "timezone": row["timezone"],
        "sent_at_utc": row["sent_at_utc"],
        "send_attempts": int(row["send_attempts"]),
        "last_error": row["last_error"],
    }
