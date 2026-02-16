from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from tools.voip_probe.config import VoipProbeSettings
from tools.voip_probe.sipp_runner import build_sipp_command, run_voip_probe


def _settings(tmp_path: Path) -> VoipProbeSettings:
    return VoipProbeSettings(
        enabled=True,
        sipp_bin="sipp",
        sip_server="mvtelecom.ddns.net",
        sip_port=5060,
        sip_transport="udp",
        sip_domain="mvtelecom.ddns.net",
        sip_username="1101",
        sip_login="1101",
        sip_password="secret",
        caller_id="1101",
        target_number="1102",
        hold_seconds=5,
        call_timeout_seconds=30,
        results_db_path=str(tmp_path / "voip_probe.db"),
        retention_days=30,
    )


def test_build_sipp_command_contains_target_and_hold(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    scenario = tmp_path / "call.xml"
    trace_dir = tmp_path
    command = build_sipp_command(settings, scenario_path=scenario, trace_dir=trace_dir)
    assert command[0] == "sipp"
    assert f"{settings.sip_server}:{settings.sip_port}" in command
    assert "-sf" in command
    assert str(scenario) in command
    assert "-s" in command
    assert "1102" in command
    assert "-au" in command
    assert "-ap" in command


def test_run_voip_probe_timeout_sets_failure(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 30))

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_voip_probe(settings)
    assert result.ok is False
    assert result.completed_call is False
    assert result.error == "timeout"


def test_run_voip_probe_binary_missing_sets_error(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)

    def fake_run(*args, **kwargs):
        raise FileNotFoundError

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_voip_probe(settings)
    assert result.ok is False
    assert "sipp binary not found" in (result.error or "")


def test_run_voip_probe_renders_auth_challenge_flow(tmp_path: Path, monkeypatch) -> None:
    settings = _settings(tmp_path)
    captured = {"checked": False}

    def fake_run(command, **kwargs):
        sf_index = command.index("-sf")
        scenario_path = Path(command[sf_index + 1])
        xml = scenario_path.read_text(encoding="utf-8")
        marker = f"INVITE sip:{settings.target_number}@{settings.sip_domain} SIP/2.0"
        invite_sections = xml.split(marker)
        if len(invite_sections) >= 3:
            first_invite = invite_sections[1]
            second_invite = invite_sections[2]
            captured["checked"] = (
                "Authorization: [authentication" not in first_invite
                and "Authorization: [authentication" in second_invite
                and xml.count("Authorization: [authentication") == 1
                and "CSeq: 1 INVITE" in first_invite
                and "CSeq: 2 INVITE" in second_invite
                and "CSeq: 2 ACK" in xml
                and "CSeq: 3 BYE" in xml
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="",
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = run_voip_probe(settings)
    assert captured["checked"] is True
    assert result.completed_call is False
