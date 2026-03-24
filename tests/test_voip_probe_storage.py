from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from tools.voip_probe.storage import VoipProbeStorage


def test_storage_insert_and_list(tmp_path: Path) -> None:
    storage = VoipProbeStorage(str(tmp_path / "voip_probe.db"))
    payload = {
        "run_id": "run-1",
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
        "category": None,
        "reason": None,
        "mode": "matrix_v1",
        "failure_destination_number": None,
        "failure_stage": None,
        "destinations": [
            {
                "key": "target",
                "number": "1102",
                "no_issues": True,
                "setup_latency_ms": 800,
                "sip_final_code": 200,
                "category": None,
                "reason": None,
            }
        ],
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
            "run_id": "run-old",
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
            "destinations": [
                {
                    "key": "target",
                    "number": "1102",
                    "no_issues": True,
                    "setup_latency_ms": 700,
                    "sip_final_code": 200,
                    "category": None,
                    "reason": None,
                }
            ],
            "mode": "matrix_v1",
            "failure_destination_number": None,
            "failure_stage": None,
        }
    )
    storage.insert_result(
        {
            "run_id": "run-recent",
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
            "destinations": [
                {
                    "key": "target",
                    "number": "1102",
                    "no_issues": True,
                    "setup_latency_ms": 750,
                    "sip_final_code": 200,
                    "category": None,
                    "reason": None,
                }
            ],
            "mode": "matrix_v1",
            "failure_destination_number": None,
            "failure_stage": None,
        }
    )
    removed = storage.purge_older_than_days(30)
    rows = storage.list_results(limit=10)
    storage.close()

    assert removed == 1
    assert len(rows) == 1
    assert rows[0]["setup_latency_ms"] == 750


def test_storage_baseline_for_destination_hourly(tmp_path: Path) -> None:
    storage = VoipProbeStorage(str(tmp_path / "voip_probe.db"))
    base_time = datetime(2026, 2, 16, 14, 0, tzinfo=timezone.utc)
    for idx, latency in enumerate([900, 950, 1000, 1100, 1050], start=1):
        ts = (base_time - timedelta(days=idx)).isoformat()
        storage.insert_result(
            {
                "run_id": f"run-{idx}",
                "ok": True,
                "completed_call": True,
                "no_issues": True,
                "target_number": "1102",
                "hold_seconds": 5,
                "setup_latency_ms": latency,
                "total_duration_ms": 6200,
                "sip_final_code": 200,
                "error": None,
                "started_at_utc": ts,
                "finished_at_utc": ts,
                "destinations": [
                    {
                        "key": "target",
                        "number": "1102",
                        "no_issues": True,
                        "setup_latency_ms": latency,
                        "sip_final_code": 200,
                        "category": None,
                        "reason": None,
                    }
                ],
                "mode": "matrix_v1",
                "failure_destination_number": None,
                "failure_stage": None,
            }
        )
    baseline = storage.baseline_for_destination(
        destination_number="1102",
        now_utc=base_time,
        timezone_name="UTC",
        window_days=7,
        hour_local=14,
    )
    storage.close()

    assert baseline["samples"] == 5
    assert baseline["success_rate_pct"] == 100.0
    assert baseline["avg_latency_ms"] == 1000.0


def test_storage_logs_filter_by_mode_matrix_only(tmp_path: Path) -> None:
    storage = VoipProbeStorage(str(tmp_path / "voip_probe.db"))
    now_iso = datetime.now(timezone.utc).isoformat()
    storage.insert_result(
        {
            "run_id": "legacy-run",
            "ok": False,
            "completed_call": False,
            "no_issues": False,
            "target_number": "1102",
            "hold_seconds": 5,
            "setup_latency_ms": None,
            "total_duration_ms": 100,
            "sip_final_code": 500,
            "error": "legacy",
            "started_at_utc": now_iso,
            "finished_at_utc": now_iso,
            "mode": "legacy_v0",
        }
    )
    storage.insert_result(
        {
            "run_id": "matrix-run",
            "ok": True,
            "completed_call": True,
            "no_issues": True,
            "target_number": "1102",
            "hold_seconds": 5,
            "setup_latency_ms": 400,
            "total_duration_ms": 6200,
            "sip_final_code": 200,
            "error": None,
            "started_at_utc": now_iso,
            "finished_at_utc": now_iso,
            "mode": "matrix_v1",
            "destinations": [
                {
                    "key": "target",
                    "number": "1102",
                    "no_issues": True,
                    "setup_latency_ms": 400,
                    "sip_final_code": 200,
                }
            ],
        }
    )
    rows_default = storage.list_results(limit=10)
    rows_all = storage.list_results(limit=10, only_mode=None)
    storage.close()

    assert len(rows_default) == 1
    assert rows_default[0]["run_id"] == "matrix-run"
    assert len(rows_all) == 2
