from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3


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
                finished_at_utc TEXT NOT NULL
            )
            """
        )
        self._connection.commit()

    def insert_result(self, result: dict) -> int:
        cursor = self._connection.cursor()
        cursor.execute(
            """
            INSERT INTO probe_results (
                created_at_utc, ok, completed_call, no_issues, target_number,
                hold_seconds, setup_latency_ms, total_duration_ms, sip_final_code,
                error, started_at_utc, finished_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
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
            ),
        )
        self._connection.commit()
        return int(cursor.lastrowid)

    def list_results(self, limit: int) -> list[dict]:
        safe_limit = max(1, min(200, int(limit)))
        rows = self._connection.execute(
            """
            SELECT ok, completed_call, no_issues, target_number, hold_seconds,
                   setup_latency_ms, total_duration_ms, sip_final_code, error,
                   started_at_utc, finished_at_utc
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
                }
            )
        return output

    def purge_older_than_days(self, days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, days))
        cursor = self._connection.cursor()
        cursor.execute(
            "DELETE FROM probe_results WHERE finished_at_utc < ?",
            (cutoff.isoformat(),),
        )
        self._connection.commit()
        return int(cursor.rowcount)

    def close(self) -> None:
        self._connection.close()

