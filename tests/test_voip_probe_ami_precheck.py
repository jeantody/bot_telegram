from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.automations_lib.providers.ami_client import AmiError
from src.automations_lib.providers.issabel_ami_provider import ConnectedVoipSipPeer
from tools.voip_probe import main as voip_main


def _settings(**overrides):
    base = {
        "ami_host": "127.0.0.1",
        "ami_port": 5038,
        "ami_username": "admin",
        "ami_secret": "secret",
        "ami_timeout_seconds": 8,
        "ami_use_tls": False,
        "ami_peer_name_regex": r"^\d+$",
        "sip_login": "1101",
        "sip_username": "1101",
        "target_number": "1102",
        "external_reference_number": "11999990000",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_collect_ami_snapshot_success_with_watched_peers(monkeypatch) -> None:
    peers = [
        ConnectedVoipSipPeer(name="1101", ip="10.0.0.10", port=5060, status="OK"),
        ConnectedVoipSipPeer(name="1102", ip="10.0.0.20", port=5061, status="OK (12 ms)"),
    ]

    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def list_connected_voips(self):
            return peers

    monkeypatch.setattr(voip_main, "IssabelAmiProvider", FakeProvider)

    snapshot = await voip_main._collect_ami_snapshot_async(_settings())

    assert snapshot["configured"] is True
    assert snapshot["ok"] is True
    assert snapshot["warning"] is False
    assert snapshot["peer_total"] == 2
    assert snapshot["watched"]["self"]["connected"] is True
    assert snapshot["watched"]["self"]["ip"] == "10.0.0.10"
    assert snapshot["watched"]["target"]["connected"] is True
    # External is numeric and regex-enabled, but absent from peers => still listed as disconnected.
    assert snapshot["watched"]["external"]["connected"] is False


@pytest.mark.asyncio
async def test_collect_ami_snapshot_not_configured(monkeypatch) -> None:
    class FakeProvider:
        async def list_connected_voips(self):
            raise AssertionError("should not call provider when AMI not configured")

    monkeypatch.setattr(voip_main, "IssabelAmiProvider", FakeProvider)

    snapshot = await voip_main._collect_ami_snapshot_async(
        _settings(ami_host=None, ami_username=None, ami_secret=None)
    )

    assert snapshot["configured"] is False
    assert snapshot["warning"] is False
    assert snapshot["error"] == "not_configured"
    assert snapshot["watched"]["self"]["number"] == "1101"


@pytest.mark.asyncio
async def test_collect_ami_snapshot_ami_failure_sets_warning(monkeypatch) -> None:
    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def list_connected_voips(self):
            raise AmiError("timeout ao consultar AMI")

    monkeypatch.setattr(voip_main, "IssabelAmiProvider", FakeProvider)

    snapshot = await voip_main._collect_ami_snapshot_async(_settings())
    payload = {"prechecks": {}, "summary": {"deviation_alert": False}}
    voip_main._apply_ami_snapshot(payload=payload, snapshot=snapshot)

    assert snapshot["configured"] is True
    assert snapshot["ok"] is False
    assert snapshot["warning"] is True
    assert "timeout" in (snapshot["error"] or "")
    assert payload["summary"]["ami_warning"] is True
    assert "timeout" in (payload["summary"]["ami_warning_reason"] or "")


@pytest.mark.asyncio
async def test_collect_ami_snapshot_peer_absent_is_informational(monkeypatch) -> None:
    peers = [ConnectedVoipSipPeer(name="1101", ip="10.0.0.10", port=5060, status="OK")]

    class FakeProvider:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        async def list_connected_voips(self):
            return peers

    monkeypatch.setattr(voip_main, "IssabelAmiProvider", FakeProvider)

    snapshot = await voip_main._collect_ami_snapshot_async(_settings())
    payload = {"summary": {}, "prechecks": {}}
    voip_main._apply_ami_snapshot(payload=payload, snapshot=snapshot)

    assert snapshot["warning"] is False
    assert snapshot["watched"]["target"]["connected"] is False
    assert payload["summary"]["ami_warning"] is False
    assert payload["summary"]["ami_warning_reason"] is None

