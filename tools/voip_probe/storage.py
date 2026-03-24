from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import sqlite3
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class VoipProbeStorage:
    def __init__(self, db_path: str) -> None:
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._db_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cursor = self._connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS probe_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                created_at_utc TEXT NOT NULL,
                ok INTEGER NOT NULL,
                completed_call INTEGER NOT NULL,
                no_issues INTEGER NOT NULL,
                target_number TEXT NOT NULL,
                hold_seconds INTEGER NOT NULL,
                setup_latency_ms INTEGER,
                total_duration_ms INTEGER NOT NULL,
                sip_final_code INTEGER,
                error TEXT,
                started_at_utc TEXT NOT NULL,
                finished_at_utc TEXT NOT NULL,
                mode TEXT,
                category TEXT,
                reason TEXT,
                failure_destination_number TEXT,
                failure_stage TEXT,
                prechecks_json TEXT,
                destinations_json TEXT,
                summary_json TEXT
            )
            """
        )
        self._ensure_results_columns(cursor)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS probe_destination_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                finished_at_utc TEXT NOT NULL,
                destination_key TEXT NOT NULL,
                destination_number TEXT NOT NULL,
                success INTEGER NOT NULL,
                setup_latency_ms INTEGER,
                sip_final_code INTEGER,
                category TEXT,
                reason TEXT
            )
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_probe_results_finished
            ON probe_results(finished_at_utc)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_probe_destination_finished
            ON probe_destination_results(destination_number, finished_at_utc)
            """
        )
        cursor.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_probe_destination_run
            ON probe_destination_results(run_id)
            """
        )
        self._connection.commit()

    def _ensure_results_columns(self, cursor: sqlite3.Cursor) -> None:
        rows = cursor.execute("PRAGMA table_info(probe_results)").fetchall()
        existing = {str(row["name"]) for row in rows}
        expected = {
            "run_id": "TEXT",
            "mode": "TEXT",
            "category": "TEXT",
            "reason": "TEXT",
            "prechecks_json": "TEXT",
            "destinations_json": "TEXT",
            "summary_json": "TEXT",
            "failure_destination_number": "TEXT",
            "failure_stage": "TEXT",
        }
        for column, col_type in expected.items():
            if column in existing:
                continue
            cursor.execute(
                f"ALTER TABLE probe_results ADD COLUMN {column} {col_type}"
            )

    def insert_result(self, result: dict) -> int:
        run_id = str(result.get("run_id") or "")
        created_at = datetime.now(timezone.utc).isoformat()
        prechecks = result.get("prechecks")
        destinations = result.get("destinations")
        summary = result.get("summary")
        prechecks_json = (
            json.dumps(prechecks, ensure_ascii=False)[:20000]
            if isinstance(prechecks, dict)
            else None
        )
        destinations_json = (
            json.dumps(destinations, ensure_ascii=False)[:30000]
            if isinstance(destinations, list)
            else None
        )
        summary_json = (
            json.dumps(summary, ensure_ascii=False)[:20000]
            if isinstance(summary, dict)
            else None
        )
        cursor = self._connection.cursor()
        cursor.execute(
            """
            INSERT INTO probe_results (
                run_id, created_at_utc, ok, completed_call, no_issues, target_number,
                hold_seconds, setup_latency_ms, total_duration_ms, sip_final_code,
                error, started_at_utc, finished_at_utc, mode, category, reason,
                failure_destination_number, failure_stage,
                prechecks_json, destinations_json, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                created_at,
                1 if bool(result.get("ok")) else 0,
                1 if bool(result.get("completed_call")) else 0,
                1 if bool(result.get("no_issues")) else 0,
                str(result.get("target_number") or ""),
                int(result.get("hold_seconds") or 0),
                int(result["setup_latency_ms"]) if result.get("setup_latency_ms") is not None else None,
                int(result.get("total_duration_ms") or 0),
                int(result["sip_final_code"]) if result.get("sip_final_code") is not None else None,
                str(result.get("error") or "")[:500] or None,
                str(result.get("started_at_utc") or ""),
                str(result.get("finished_at_utc") or ""),
                str(result.get("mode") or "")[:100] or None,
                str(result.get("category") or "")[:50] or None,
                str(result.get("reason") or "")[:500] or None,
                str(result.get("failure_destination_number") or "")[:80] or None,
                str(result.get("failure_stage") or "")[:40] or None,
                prechecks_json,
                destinations_json,
                summary_json,
            ),
        )
        self._insert_destination_rows(cursor, result)
        self._connection.commit()
        return int(cursor.lastrowid)

    def _insert_destination_rows(self, cursor: sqlite3.Cursor, result: dict) -> None:
        run_id = str(result.get("run_id") or "")
        finished_at = str(result.get("finished_at_utc") or datetime.now(timezone.utc).isoformat())
        destinations = result.get("destinations")
        rows: list[tuple] = []
        if isinstance(destinations, list) and destinations:
            for item in destinations:
                if not isinstance(item, dict):
                    continue
                rows.append(
                    (
                        run_id,
                        finished_at,
                        str(item.get("key") or "unknown"),
                        str(item.get("number") or ""),
                        1 if bool(item.get("no_issues")) else 0,
                        int(item["setup_latency_ms"])
                        if item.get("setup_latency_ms") is not None
                        else None,
                        int(item["sip_final_code"])
                        if item.get("sip_final_code") is not None
                        else None,
                        str(item.get("category") or "")[:50] or None,
                        str(item.get("reason") or item.get("error") or "")[:500] or None,
                    )
                )
        else:
            rows.append(
                (
                    run_id,
                    finished_at,
                    "target",
                    str(result.get("target_number") or ""),
                    1 if bool(result.get("no_issues")) else 0,
                    int(result["setup_latency_ms"])
                    if result.get("setup_latency_ms") is not None
                    else None,
                    int(result["sip_final_code"])
                    if result.get("sip_final_code") is not None
                    else None,
                    str(result.get("category") or "")[:50] or None,
                    str(result.get("reason") or result.get("error") or "")[:500] or None,
                )
            )
        cursor.executemany(
            """
            INSERT INTO probe_destination_results (
                run_id, finished_at_utc, destination_key, destination_number,
                success, setup_latency_ms, sip_final_code, category, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )

    def list_results(self, limit: int, *, only_mode: str | None = "matrix_v1") -> list[dict]:
        safe_limit = max(1, min(200, int(limit)))
        if only_mode:
            rows = self._connection.execute(
                """
                SELECT run_id, ok, completed_call, no_issues, target_number, hold_seconds,
                       setup_latency_ms, total_duration_ms, sip_final_code, error,
                       started_at_utc, finished_at_utc, mode, category, reason,
                       failure_destination_number, failure_stage,
                       prechecks_json, destinations_json, summary_json
                FROM probe_results
                WHERE mode = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (only_mode, safe_limit),
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT run_id, ok, completed_call, no_issues, target_number, hold_seconds,
                       setup_latency_ms, total_duration_ms, sip_final_code, error,
                       started_at_utc, finished_at_utc, mode, category, reason,
                       failure_destination_number, failure_stage,
                       prechecks_json, destinations_json, summary_json
                FROM probe_results
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        output: list[dict] = []
        for row in rows:
            output.append(
                {
                    "run_id": row["run_id"],
                    "ok": bool(row["ok"]),
                    "completed_call": bool(row["completed_call"]),
                    "no_issues": bool(row["no_issues"]),
                    "target_number": row["target_number"],
                    "hold_seconds": int(row["hold_seconds"]),
                    "setup_latency_ms": (
                        int(row["setup_latency_ms"])
                        if row["setup_latency_ms"] is not None
                        else None
                    ),
                    "total_duration_ms": int(row["total_duration_ms"]),
                    "sip_final_code": (
                        int(row["sip_final_code"])
                        if row["sip_final_code"] is not None
                        else None
                    ),
                    "error": row["error"],
                    "started_at_utc": row["started_at_utc"],
                    "finished_at_utc": row["finished_at_utc"],
                    "mode": row["mode"],
                    "category": row["category"],
                    "reason": row["reason"],
                    "failure_destination_number": row["failure_destination_number"],
                    "failure_stage": row["failure_stage"],
                    "prechecks": _safe_json_load(row["prechecks_json"]),
                    "destinations": _safe_json_load(row["destinations_json"]),
                    "summary": _safe_json_load(row["summary_json"]),
                }
            )
        return output

    def purge_older_than_days(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        cutoff_iso = cutoff.isoformat()
        cursor = self._connection.cursor()
        cursor.execute(
            "DELETE FROM probe_results WHERE finished_at_utc < ?",
            (cutoff_iso,),
        )
        deleted_results = int(cursor.rowcount)
        cursor.execute(
            "DELETE FROM probe_destination_results WHERE finished_at_utc < ?",
            (cutoff_iso,),
        )
        self._connection.commit()
        return deleted_results

    def baseline_for_destination(
        self,
        *,
        destination_number: str,
        now_utc: datetime,
        timezone_name: str,
        window_days: int,
        hour_local: int,
    ) -> dict:
        cutoff_utc = now_utc - timedelta(days=max(1, int(window_days)))
        rows = self._connection.execute(
            """
            SELECT success, setup_latency_ms, finished_at_utc
            FROM probe_destination_results
            WHERE destination_number = ?
              AND finished_at_utc >= ?
            """,
            (destination_number, cutoff_utc.isoformat()),
        ).fetchall()
        tzinfo = _resolve_timezone(timezone_name)
        samples = 0
        success_count = 0
        latency_values: list[int] = []
        for row in rows:
            finished_at = _parse_iso_datetime(row["finished_at_utc"])
            if finished_at is None:
                continue
            if finished_at.astimezone(tzinfo).hour != hour_local:
                continue
            samples += 1
            if bool(row["success"]):
                success_count += 1
            if row["setup_latency_ms"] is not None:
                latency_values.append(int(row["setup_latency_ms"]))
        success_rate = (success_count / samples * 100.0) if samples > 0 else None
        avg_latency = (
            round(sum(latency_values) / len(latency_values), 2)
            if latency_values
            else None
        )
        return {
            "samples": samples,
            "success_rate_pct": success_rate,
            "avg_latency_ms": avg_latency,
        }

    def close(self) -> None:
        self._connection.close()


def _safe_json_load(raw: str | None):
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _resolve_timezone(timezone_name: str):
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        if timezone_name == "America/Sao_Paulo":
            return timezone(timedelta(hours=-3))
        return timezone.utc
