from __future__ import annotations

from dataclasses import dataclass
import re

from src.automations_lib.providers.ami_client import AmiClient, AmiError


@dataclass(frozen=True)
class ConnectedVoipSipPeer:
    name: str
    ip: str
    port: int | None
    status: str | None


_BAD_IPS = {"", "0.0.0.0", "(null)", "null", "-none-"}


def filter_connected_sip_peers(
    entries: list[dict[str, str]],
    *,
    peer_name_regex: str,
) -> list[ConnectedVoipSipPeer]:
    pattern = re.compile(peer_name_regex)
    peers: list[ConnectedVoipSipPeer] = []
    for entry in entries:
        lowered = {str(k).strip().lower(): str(v or "").strip() for k, v in entry.items()}
        dynamic = lowered.get("dynamic", "").strip().lower()
        if dynamic != "yes":
            continue
        name = lowered.get("objectname", "").strip()
        if not name or not pattern.match(name):
            continue
        ip = lowered.get("ipaddress", "").strip()
        if ip.strip().lower() in _BAD_IPS:
            continue
        port_raw = lowered.get("ipport", "").strip()
        port = int(port_raw) if port_raw.isdigit() else None
        status = lowered.get("status", "").strip() or None
        peers.append(ConnectedVoipSipPeer(name=name, ip=ip, port=port, status=status))

    def sort_key(item: ConnectedVoipSipPeer) -> tuple[int, int | str]:
        if item.name.isdigit():
            return (0, int(item.name))
        return (1, item.name.lower())

    peers.sort(key=sort_key)
    return peers


class IssabelAmiProvider:
    def __init__(
        self,
        *,
        host: str | None,
        port: int,
        username: str | None,
        secret: str | None,
        timeout_seconds: int = 8,
        use_tls: bool = False,
        peer_name_regex: str = r"^\d+$",
    ) -> None:
        self._host = host
        self._port = int(port)
        self._username = username
        self._secret = secret
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._use_tls = bool(use_tls)
        self._peer_name_regex = peer_name_regex or r"^\d+$"

    async def list_connected_voips(self) -> list[ConnectedVoipSipPeer]:
        if not self._host or not self._username or not self._secret:
            raise ValueError("ISSABEL AMI nao configurado")
        client = AmiClient(
            host=self._host,
            port=self._port,
            username=self._username,
            secret=self._secret,
            timeout_seconds=self._timeout_seconds,
            use_tls=self._use_tls,
        )
        entries = await client.run_sip_peers()
        return filter_connected_sip_peers(entries, peer_name_regex=self._peer_name_regex)


__all__ = [
    "AmiError",
    "ConnectedVoipSipPeer",
    "IssabelAmiProvider",
    "filter_connected_sip_peers",
]

