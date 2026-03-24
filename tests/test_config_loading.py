from __future__ import annotations

from pathlib import Path

import pytest

from src import config as config_module
from src.env_contract import validate_env_contract


def test_load_settings_requires_telegram_bot_token(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "validate_env_contract", lambda: None)
    monkeypatch.setattr(
        config_module,
        "load_dotenv",
        lambda **kwargs: None,
    )
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    with pytest.raises(ValueError, match="Missing TELEGRAM_BOT_TOKEN"):
        config_module.load_settings()


def test_load_settings_applies_defaults_and_normalizes_ami(monkeypatch) -> None:
    call_order: list[str] = []

    expected_dotenv_path = Path(__file__).resolve().parent.parent / ".env"

    def fake_load_dotenv(*, dotenv_path, override: bool) -> None:
        assert Path(dotenv_path) == expected_dotenv_path
        assert override is True
        call_order.append("load_dotenv")

    def fake_validate_env_contract() -> None:
        call_order.append("validate_env_contract")

    monkeypatch.setattr(config_module, "validate_env_contract", fake_validate_env_contract)
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
        "ZABBIX_BASE_URL",
        "ZABBIX_API_TOKEN",
        "ZABBIX_TIMEOUT_SECONDS",
        "ZABBIXH_HOST_TARGETS_JSON",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ISSABEL_AMI_RAWMAN_URL", "http://coalapabx.ddns.net/")
    monkeypatch.setenv("ISSABEL_AMI_PEER_NAME_REGEX", r"^\\d+$")

    settings = config_module.load_settings()

    assert call_order == ["validate_env_contract", "load_dotenv"]
    assert settings.telegram_bot_token == "token"
    assert settings.telegram_allowed_chat_id is None
    assert settings.request_timeout_seconds == 20
    assert settings.automation_timeout_seconds == 30
    assert settings.voip_call_timeout_seconds == 30
    assert settings.voip_probe_interval_seconds == 3600
    assert settings.rate_limit_voip_seconds == 120
    assert settings.rate_limit_ping_seconds == 20
    assert settings.zabbix_base_url is None
    assert settings.zabbix_api_token is None
    assert settings.zabbix_timeout_seconds == 8
    assert settings.zabbixh_host_targets == ()
    assert settings.state_db_path == str(Path(__file__).resolve().parent.parent / "data/bot_state.db")
    assert settings.voip_results_db_path == str(Path(__file__).resolve().parent.parent / "data/voip_probe.db")
    assert settings.issabel_ami_rawman_url == (
        "http://coalapabx.ddns.net:8088/asterisk/rawman"
    )
    assert settings.issabel_ami_port == 8088
    assert settings.issabel_ami_peer_name_regex == r"^\d+$"


def test_validate_env_contract_requires_local_env_file(tmp_path) -> None:
    example_path = tmp_path / ".env.example"
    example_path.write_text("TELEGRAM_BOT_TOKEN=<token>\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing \\.env file"):
        validate_env_contract(
            example_path=example_path,
            env_path=tmp_path / ".env",
        )


def test_validate_env_contract_rejects_missing_required_key(tmp_path) -> None:
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(
        "TELEGRAM_BOT_TOKEN=<token>\nREQUEST_TIMEOUT_SECONDS=20\n",
        encoding="utf-8",
    )
    env_path.write_text("TELEGRAM_BOT_TOKEN=token\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Missing keys in \\.env: REQUEST_TIMEOUT_SECONDS"):
        validate_env_contract(example_path=example_path, env_path=env_path)


def test_validate_env_contract_rejects_empty_required_key(tmp_path) -> None:
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text("TELEGRAM_BOT_TOKEN=<token>\n", encoding="utf-8")
    env_path.write_text("TELEGRAM_BOT_TOKEN=\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Empty required keys in \\.env: TELEGRAM_BOT_TOKEN"):
        validate_env_contract(example_path=example_path, env_path=env_path)


def test_validate_env_contract_allows_empty_optional_key(tmp_path) -> None:
    example_path = tmp_path / ".env.example"
    env_path = tmp_path / ".env"
    example_path.write_text(
        "TELEGRAM_BOT_TOKEN=<token>\nVOIP_ALERT_CHAT_ID=\n",
        encoding="utf-8",
    )
    env_path.write_text(
        "TELEGRAM_BOT_TOKEN=token\nVOIP_ALERT_CHAT_ID=\n",
        encoding="utf-8",
    )

    validate_env_contract(example_path=example_path, env_path=env_path)


def test_load_settings_accepts_complete_zabbix_token_configuration(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "validate_env_contract", lambda: None)
    monkeypatch.setattr(config_module, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ZABBIX_BASE_URL", "https://aurora.acctunnel.space/zabbix")
    monkeypatch.setenv("ZABBIX_API_TOKEN", "token-zbx")
    monkeypatch.setenv("ZABBIX_TIMEOUT_SECONDS", "13")
    monkeypatch.setenv(
        "ZABBIXH_HOST_TARGETS_JSON",
        '[{"label":"01_TrueNas","hostid":"10679"},{"label":"Ubuntu_Hostinger","hostid":"10756"}]',
    )

    settings = config_module.load_settings()

    assert settings.zabbix_base_url == "https://aurora.acctunnel.space/zabbix"
    assert settings.zabbix_api_token == "token-zbx"
    assert settings.zabbix_timeout_seconds == 13
    assert settings.zabbixh_host_targets == (
        ("01_TrueNas", "10679"),
        ("Ubuntu_Hostinger", "10756"),
    )


def test_load_settings_rejects_partial_zabbix_token_configuration(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "validate_env_contract", lambda: None)
    monkeypatch.setattr(config_module, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ZABBIX_BASE_URL", "https://aurora.acctunnel.space/zabbix")
    monkeypatch.delenv("ZABBIX_API_TOKEN", raising=False)

    with pytest.raises(ValueError, match="Incomplete Zabbix configuration"):
        config_module.load_settings()


def test_load_settings_rejects_invalid_zabbixh_targets_json(monkeypatch) -> None:
    monkeypatch.setattr(config_module, "validate_env_contract", lambda: None)
    monkeypatch.setattr(config_module, "load_dotenv", lambda **kwargs: None)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("ZABBIXH_HOST_TARGETS_JSON", '{"label":"server"}')

    with pytest.raises(ValueError, match="Invalid ZABBIXH_HOST_TARGETS_JSON"):
        config_module.load_settings()
