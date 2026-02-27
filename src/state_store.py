from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
import logging
import json
import math
from pathlib import Path
import sqlite3
import threading
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from src.redaction import redact_payload


logger = logging.getLogger(__name__)


class BotStateStore:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._lock = threading.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._configure_pragmas()
        self._ensure_schema()

    def _configure_pragmas(self) -> None:
        with self._lock:
            cursor = self._connection.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA busy_timeout=5000;")
                cursor.execute("PRAGMA foreign_keys=ON;")
            except Exception:
                logger.warning(
                    "failed to configure sqlite pragmas",
                    extra={"event": "sqlite_pragmas_error"},
                    exc_info=True,
                )

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
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS ami_peer_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    online_count INTEGER NOT NULL,
                    offline_count INTEGER NOT NULL,
                    total_count INTEGER NOT NULL
                )
                """
            )
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_ami_peer_snapshots_created_at
                ON ami_peer_snapshots(created_at)
                """
            )
            self._connection.commit()

    def close(self) -> None:
        with self._lock:
            try:
                self._connection.close()
            except Exception:
                logger.warning(
                    "failed to close sqlite connection",
                    extra={"event": "sqlite_close_error"},
                    exc_info=True,
                )

    def consume_rate_limit(
        self,
        key: str,
        min_interval_seconds: int,
        now_utc: datetime | None = None,
    ) -> tuple[bool, int]:
        if min_interval_seconds <= 0:
            return True, 0
        now = now_utc or datetime.now(timezone.utc)
        now = now.astimezone(timezone.utc)
        now_iso = now.isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            row = cursor.execute(
                "SELECT state_value FROM monitored_state WHERE state_key = ?",
                (key,),
            ).fetchone()
            last: datetime | None = None
            if row:
                raw = row["state_value"]
                if raw:
                    try:
                        last = datetime.fromisoformat(str(raw))
                    except ValueError:
                        last = None
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last is not None:
                elapsed = (now - last).total_seconds()
                remaining = float(min_interval_seconds) - elapsed
                if remaining > 0:
                    return False, max(1, int(math.ceil(remaining)))

            cursor.execute(
                """
                INSERT INTO monitored_state (state_key, state_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value=excluded.state_value,
                    updated_at=excluded.updated_at
                """,
                (key, now_iso, now_iso),
            )
            self._connection.commit()
        return True, 0

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
        payload_json = (
            json.dumps(redact_payload(payload), ensure_ascii=False)
            if payload is not None
            else None
        )
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

    def record_ami_peer_snapshot(
        self,
        *,
        captured_at_utc: datetime,
        online_count: int,
        offline_count: int,
    ) -> None:
        created_at = captured_at_utc.astimezone(timezone.utc).isoformat()
        online = max(0, int(online_count))
        offline = max(0, int(offline_count))
        total = online + offline
        with self._lock:
            cursor = self._connection.cursor()
            cursor.execute(
                """
                INSERT INTO ami_peer_snapshots (
                    created_at, online_count, offline_count, total_count
                ) VALUES (?, ?, ?, ?)
                """,
                (created_at, online, offline, total),
            )
            self._connection.commit()

    def get_ami_peer_snapshot_at_or_before(
        self,
        *,
        target_utc: datetime,
    ) -> dict | None:
        target_iso = target_utc.astimezone(timezone.utc).isoformat()
        with self._lock:
            cursor = self._connection.cursor()
            row = cursor.execute(
                """
                SELECT created_at, online_count, offline_count, total_count
                FROM ami_peer_snapshots
                WHERE created_at <= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (target_iso,),
            ).fetchone()
        if row is None:
            return None
        return {
            "created_at": row["created_at"],
            "online_count": int(row["online_count"]),
            "offline_count": int(row["offline_count"]),
            "total_count": int(row["total_count"]),
        }

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
