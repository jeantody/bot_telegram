from __future__ import annotations

import pytest

from src.automations_lib.providers import issabel_ami_provider as provider_mod
from src.automations_lib.providers.issabel_ami_provider import (
    IssabelAmiProvider,
    filter_connected_sip_peers,
)


def test_filter_connected_sip_peers_keeps_only_registered_numeric_peers() -> None:
    entries = [
        {
            "Event": "PeerEntry",
            "ObjectName": "1001",
            "Dynamic": "yes",
            "IPaddress": "10.0.0.1",
            "IPport": "5060",
            "Status": "OK (12 ms)",
        },
        {
            "Event": "PeerEntry",
            "ObjectName": "1002",
            "Dynamic": "no",
            "IPaddress": "10.0.0.2",
            "IPport": "5060",
        },
        {
            "Event": "PeerEntry",
            "ObjectName": "abc",
            "Dynamic": "yes",
            "IPaddress": "10.0.0.3",
            "IPport": "5060",
        },
        {
            "Event": "PeerEntry",
            "ObjectName": "1003",
            "Dynamic": "yes",
            "IPaddress": "0.0.0.0",
            "IPport": "5060",
        },
        {
            "Event": "PeerEntry",
            "ObjectName": "1004",
            "Dynamic": "yes",
            "IPaddress": "(null)",
            "IPport": "5060",
        },
    ]

    peers = filter_connected_sip_peers(entries, peer_name_regex=r"^\d+$")

    assert [p.name for p in peers] == ["1001"]
    assert peers[0].ip == "10.0.0.1"
    assert peers[0].port == 5060
    assert peers[0].status == "OK (12 ms)"


@pytest.mark.asyncio
async def test_provider_uses_http_rawman_when_url_present(monkeypatch) -> None:
    called = {"rawman": False}

    async def fake_rawman_run(self):
        called["rawman"] = True
        return [
            {
                "Event": "PeerEntry",
                "ObjectName": "1101",
                "Dynamic": "yes",
                "IPaddress": "10.10.10.10",
                "IPport": "5060",
                "Status": "OK (5 ms)",
            }
        ]

    async def fake_tcp_run(self):
        raise AssertionError("TCP client should not be used when rawman_url is set")

    monkeypatch.setattr(provider_mod.AmiHttpRawmanClient, "run_sip_peers", fake_rawman_run)
    monkeypatch.setattr(provider_mod.AmiClient, "run_sip_peers", fake_tcp_run)

    provider = IssabelAmiProvider(
        host="127.0.0.1",
        rawman_url="http://pbx/asterisk/rawman",
        port=5038,
        username="u",
        secret="s",
    )
    peers = await provider.list_connected_voips()
    assert called["rawman"] is True
    assert len(peers) == 1
    assert peers[0].name == "1101"


@pytest.mark.asyncio
async def test_provider_uses_tcp_when_rawman_url_missing(monkeypatch) -> None:
    called = {"tcp": False}

    async def fake_rawman_run(self):
        raise AssertionError("Rawman client should not be used in TCP mode")

    async def fake_tcp_run(self):
        called["tcp"] = True
        return [
            {
                "Event": "PeerEntry",
                "ObjectName": "2201",
                "Dynamic": "yes",
                "IPaddress": "10.20.30.40",
                "IPport": "5060",
            }
        ]

    monkeypatch.setattr(provider_mod.AmiHttpRawmanClient, "run_sip_peers", fake_rawman_run)
    monkeypatch.setattr(provider_mod.AmiClient, "run_sip_peers", fake_tcp_run)

    provider = IssabelAmiProvider(
        host="pbx.local",
        port=5038,
        username="u",
        secret="s",
    )
    peers = await provider.list_connected_voips()
    assert called["tcp"] is True
    assert len(peers) == 1
    assert peers[0].name == "2201"

