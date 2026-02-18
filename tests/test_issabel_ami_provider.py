from __future__ import annotations

from src.automations_lib.providers.issabel_ami_provider import filter_connected_sip_peers


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

