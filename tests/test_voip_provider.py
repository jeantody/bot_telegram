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
            "mode": "matrix_v1",
            "run_id": "run-xyz",
            "category": None,
            "reason": None,
            "prechecks": {"register": {"ok": True}},
            "destinations": [{"key": "target", "number": "1102", "no_issues": True}],
            "summary": {"total_destinations": 3},
            "failure_destination_number": "1102",
            "failure_stage": "invite",
        }

    monkeypatch.setattr(provider, "_run_json_command", fake_run_json)
    result = await provider.run_once()
    assert result.ok is True
    assert result.target_number == "1102"
    assert result.setup_latency_ms == 900
    assert result.mode == "matrix_v1"
    assert result.run_id == "run-xyz"
    assert isinstance(result.destinations, list)
    assert result.failure_destination_number == "1102"
    assert result.failure_stage == "invite"


@pytest.mark.asyncio
async def test_list_logs_parses_rows(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=30, script_path="tools/voip_probe/main.py")

    async def fake_run_json(args):
        assert args == ["logs", "--limit", "2", "--json"]
        return {
            "logs": [
                {
                    "run_id": "run-1",
                    "ok": False,
                    "target_number": "1102",
                    "setup_latency_ms": None,
                    "sip_final_code": 486,
                    "error": "busy",
                    "started_at_utc": "2026-02-16T10:00:00+00:00",
                    "finished_at_utc": "2026-02-16T10:00:02+00:00",
                    "category": "rota_permissao",
                    "reason": "permissao de discagem para 1102 (486 Busy Here)",
                    "failure_destination_number": "1102",
                    "failure_stage": "invite",
                }
            ]
        }

    monkeypatch.setattr(provider, "_run_json_command", fake_run_json)
    rows = await provider.list_logs(limit=2)
    assert len(rows) == 1
    assert rows[0].ok is False
    assert rows[0].sip_final_code == 486
    assert rows[0].error == "busy"
    assert rows[0].category == "rota_permissao"
    assert rows[0].failure_destination_number == "1102"
    assert rows[0].failure_stage == "invite"


@pytest.mark.asyncio
async def test_run_json_timeout_kills_process(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=1, script_path="tools/voip_probe/main.py")

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = None
            self.killed = False
            self.communicate_calls = 0

        async def communicate(self):
            self.communicate_calls += 1
            if self.communicate_calls == 1:
                await asyncio.sleep(0.01)
                return b"{}", b""
            return b"", b""

        def kill(self):
            self.killed = True
            self.returncode = -9

    import asyncio

    fake_process = FakeProcess()

    async def fake_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        return fake_process

    async def fake_wait_for(coro, timeout):
        del timeout
        # force timeout on first communicate
        coro.close()
        raise asyncio.TimeoutError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(RuntimeError) as excinfo:
        await provider._run_json_command(["run-once", "--json"])
    assert "processo encerrado" in str(excinfo.value)
    assert fake_process.killed is True


@pytest.mark.asyncio
async def test_run_json_negative_rc_reports_signal(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=30, script_path="tools/voip_probe/main.py")

    class FakeProcess:
        def __init__(self) -> None:
            self.returncode = -15

        async def communicate(self):
            return (
                b'{"ok":false,"error":"voip probe rc=-15"}',
                b"terminated by signal",
            )

    import asyncio

    async def fake_create_subprocess_exec(*args, **kwargs):
        del args, kwargs
        return FakeProcess()

    async def fake_wait_for(coro, timeout):
        del timeout
        return await coro

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    monkeypatch.setattr(asyncio, "wait_for", fake_wait_for)

    with pytest.raises(RuntimeError) as excinfo:
        await provider._run_json_command(["run-once", "--json"])
    text = str(excinfo.value)
    assert "rc=-15" in text
    assert "SIGTERM" in text or "terminated" in text
    assert "[run-once]" in text


@pytest.mark.asyncio
async def test_run_once_invalid_payload_raises(monkeypatch) -> None:
    provider = VoipProbeProvider(timeout_seconds=30, script_path="tools/voip_probe/main.py")

    async def fake_run_json(args):
        return {"unexpected": True}

    monkeypatch.setattr(provider, "_run_json_command", fake_run_json)
    with pytest.raises(RuntimeError):
        await provider.run_once()
