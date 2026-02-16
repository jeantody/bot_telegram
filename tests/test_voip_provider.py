from __future__ import annotations

import pytest

from src.automations_lib.providers.voip_probe_provider import VoipProbeProvider


@pytest.mark.asyncio
async def test_run_once_parses_valid_json(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=30, script_path="tools/voip_probe/main.py")

    async def fake_run_json(args):
        assert args == ["run-once", "--json"]
        return {
            "ok": True,
            "completed_call": True,
            "no_issues": True,
            "target_number": "1102",
            "hold_seconds": 5,
            "setup_latency_ms": 900,
            "total_duration_ms": 6100,
            "sip_final_code": 200,
            "error": None,
            "started_at_utc": "2026-02-16T10:00:00+00:00",
            "finished_at_utc": "2026-02-16T10:00:06+00:00",
        }

    monkeypatch.setattr(provider, "_run_json_command", fake_run_json)
    result = await provider.run_once()
    assert result.ok is True
    assert result.target_number == "1102"
    assert result.setup_latency_ms == 900


@pytest.mark.asyncio
async def test_list_logs_parses_rows(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=30, script_path="tools/voip_probe/main.py")

    async def fake_run_json(args):
        assert args == ["logs", "--limit", "2", "--json"]
        return {
            "logs": [
                {
                    "ok": False,
                    "target_number": "1102",
                    "setup_latency_ms": None,
                    "sip_final_code": 486,
                    "error": "busy",
                    "started_at_utc": "2026-02-16T10:00:00+00:00",
                    "finished_at_utc": "2026-02-16T10:00:02+00:00",
                }
            ]
        }

    monkeypatch.setattr(provider, "_run_json_command", fake_run_json)
    rows = await provider.list_logs(limit=2)
    assert len(rows) == 1
    assert rows[0].ok is False
    assert rows[0].sip_final_code == 486
    assert rows[0].error == "busy"


@pytest.mark.asyncio
async def test_run_once_invalid_payload_raises(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=30, script_path="tools/voip_probe/main.py")

    async def fake_run_json(args):
        return {"unexpected": True}

    monkeypatch.setattr(provider, "_run_json_command", fake_run_json)
    with pytest.raises(RuntimeError):
        await provider.run_once()

