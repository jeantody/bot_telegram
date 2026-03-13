from __future__ import annotations

import pytest

from src import config as config_module


def test_load_settings_requires_telegram_bot_token(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "load_dotenv", lambda override=True: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValueError, match="Missing TELEGRAM_BOT_TOKEN"):
        config_module.load_settings()


def test_load_settings_applies_defaults_and_normalizes_ami(monkeypatch) -> None:
    load_dotenv_calls: list[bool] = []

    def fake_load_dotenv(*, override: bool) -> None:
        load_dotenv_calls.append(override)

    monkeypatch.setattr(config_module, "load_dotenv", fake_load_dotenv)

    for key in (
        "TELEGRAM_ALLOWED_CHAT_ID",
        "REQUEST_TIMEOUT_SECONDS",
        "AUTOMATION_TIMEOUT_SECONDS",
        "VOIP_CALL_TIMEOUT_SECONDS",
        "VOIP_PROBE_INTERVAL_SECONDS",
        "RATE_LIMIT_VOIP_SECONDS",
        "RATE_LIMIT_PING_SECONDS",
        "ISSABEL_AMI_PORT",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ISSABEL_AMI_RAWMAN_URL", "http://coalapabx.ddns.net/")
    monkeypatch.setenv("ISSABEL_AMI_PEER_NAME_REGEX", r"^\\d+$")

    settings = config_module.load_settings()

    assert load_dotenv_calls == [True]
    assert settings.telegram_bot_token == "token"
    assert settings.telegram_allowed_chat_id is None
    assert settings.request_timeout_seconds == 20
    assert settings.automation_timeout_seconds == 30
    assert settings.voip_call_timeout_seconds == 30
    assert settings.voip_probe_interval_seconds == 3600
    assert settings.rate_limit_voip_seconds == 120
    assert settings.rate_limit_ping_seconds == 20
    assert settings.issabel_ami_rawman_url == (
        "http://coalapabx.ddns.net:8088/asterisk/rawman"
    )
    assert settings.issabel_ami_port == 8088
    assert settings.issabel_ami_peer_name_regex == r"^\d+$"
