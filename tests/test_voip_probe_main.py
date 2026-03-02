from __future__ import annotations

import json
import sys
from pathlib import Path

from tools.voip_probe import main as voip_main


class _DummyStorage:
    def __init__(self) -> None:
        self.inserted: list[dict] = []

    def baseline_for_destination(self, **kwargs) -> dict:
        del kwargs
        return {"samples": 0, "success_rate_pct": None, "avg_latency_ms": None}

    def insert_result(self, payload: dict) -> int:
        self.inserted.append(payload)
        return 1

    def purge_older_than_days(self, days: int) -> int:
        del days
        return 0

    def close(self) -> None:
        return None


class _FakeRunResult:
    def __init__(self, number: str) -> None:
        self._number = number

    def to_dict(self) -> dict:
        return {
            "ok": True,
            "completed_call": False,
            "no_issues": True,
            "target_number": self._number,
            "hold_seconds": 5,
            "setup_latency_ms": 620,
            "total_duration_ms": 2300,
            "sip_final_code": 183,
            "error": None,
            "started_at_utc": "2026-02-16T10:00:00+00:00",
            "finished_at_utc": "2026-02-16T10:00:02+00:00",
            "mode": "single_call_v1",
            "run_id": "call-run-1",
            "category": None,
            "reason": None,
            "prechecks": {"register": {"ok": True}},
            "destinations": [
                {
                    "key": "target",
                    "number": self._number,
                    "no_issues": True,
                    "setup_latency_ms": 620,
                    "sip_final_code": 183,
                    "error": None,
                    "category": None,
                    "reason": None,
                }
            ],
            "summary": {"total_destinations": 1, "successful_destinations": 1, "failed_destinations": 0},
            "failure_destination_number": None,
            "failure_stage": None,
        }


def test_run_call_json_outputs_single_call_mode(monkeypatch, capsys, tmp_path: Path) -> None:
    dummy_storage = _DummyStorage()

    class _FakeSettings:
        results_db_path = str(tmp_path / "voip_probe.db")
        retention_days = 30
        baseline_timezone = "America/Sao_Paulo"
        baseline_window_days = 7
        baseline_min_samples = 5
        success_drop_alert_pct_points = 20.0
        latency_baseline_multiplier = 2.0
        latency_alert_ms = 1500

    monkeypatch.setattr(
        voip_main,
        "load_settings_from_env",
        lambda **kwargs: _FakeSettings(),
    )
    monkeypatch.setattr(voip_main, "VoipProbeStorage", lambda _: dummy_storage)
    monkeypatch.setattr(
        voip_main,
        "run_single_call_probe",
        lambda settings, destination_number: _FakeRunResult(destination_number),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["main.py", "run-call", "--number", "1102", "--json"],
    )

    rc = voip_main.main()
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert rc == 0
    assert payload["mode"] == "single_call_v1"
    assert payload["target_number"] == "1102"
    assert dummy_storage.inserted and dummy_storage.inserted[0]["mode"] == "single_call_v1"
