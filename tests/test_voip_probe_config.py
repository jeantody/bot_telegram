from __future__ import annotations

from pathlib import Path

from tools.voip_probe.config import PROJECT_ROOT, load_settings_from_env


def test_load_settings_resolves_local_sipp_wrapper(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("VOIP_SIPP_BIN", "bin/sipp")
    monkeypatch.setenv("VOIP_SIP_SERVER", "sip.example.com")
    monkeypatch.setenv("VOIP_SIP_DOMAIN", "sip.example.com")
    monkeypatch.setenv("VOIP_SIP_LOGIN", "1101")
    monkeypatch.setenv("VOIP_CALLER_ID", "1101")
    monkeypatch.setenv("VOIP_TARGET_NUMBER", "1102")
    monkeypatch.setenv("VOIP_EXTERNAL_REFERENCE_NUMBER", "11999990000")

    settings = load_settings_from_env(validate=True)

    assert settings.sipp_bin == str(PROJECT_ROOT / "bin/sipp")
