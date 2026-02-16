from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.voip_probe.storage import VoipProbeStorage


def test_storage_insert_and_list(tmp_path: Path) -> None:
    storage = VoipProbeStorage(str(tmp_path / "voip_probe.db"))
    payload = {
        "ok": True,
        "completed_call": True,
        "no_issues": True,
        "target_number": "1102",
        "hold_seconds": 5,
        "setup_latency_ms": 800,
        "total_duration_ms": 6000,
        "sip_final_code": 200,
        "error": None,
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    storage.insert_result(payload)
    rows = storage.list_results(limit=5)
    storage.close()

    assert len(rows) == 1
    assert rows[0]["ok"] is True
    assert rows[0]["target_number"] == "1102"
    assert rows[0]["setup_latency_ms"] == 800


def test_storage_purge_removes_old_rows(tmp_path: Path) -> None:
    storage = VoipProbeStorage(str(tmp_path / "voip_probe.db"))
    old_time = datetime.now(timezone.utc) - timedelta(days=40)
    recent_time = datetime.now(timezone.utc)
    storage.insert_result(
        {
            "ok": True,
            "completed_call": True,
            "no_issues": True,
            "target_number": "1102",
            "hold_seconds": 5,
            "setup_latency_ms": 700,
            "total_duration_ms": 5900,
            "sip_final_code": 200,
            "error": None,
            "started_at_utc": old_time.isoformat(),
            "finished_at_utc": old_time.isoformat(),
        }
    )
    storage.insert_result(
        {
            "ok": True,
            "completed_call": True,
            "no_issues": True,
            "target_number": "1102",
            "hold_seconds": 5,
            "setup_latency_ms": 750,
            "total_duration_ms": 6100,
            "sip_final_code": 200,
            "error": None,
            "started_at_utc": recent_time.isoformat(),
            "finished_at_utc": recent_time.isoformat(),
        }
    )
    removed = storage.purge_older_than_days(30)
    rows = storage.list_results(limit=10)
    storage.close()

    assert removed == 1
    assert len(rows) == 1
    assert rows[0]["setup_latency_ms"] == 750

