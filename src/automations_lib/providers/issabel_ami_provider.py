from __future__ import annotations

from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from src.automations_lib.providers.ami_client import (
    AmiClient,
    AmiError,
    AmiHttpRawmanClient,
)


@dataclass(frozen=True)
class ConnectedVoipSipPeer:
    name: str
    ip: str
    port: int | None
    status: str | None


@dataclass(frozen=True)
class VoipSipPeer:
    name: str
    ip: str
    port: int | None
    status: str | None
    online: bool


@dataclass(frozen=True)
class VoipPeerOverview:
    total_count: int
    online_count: int
    offline_count: int
    connected_peers: list[ConnectedVoipSipPeer]


_BAD_IPS = {"", "0.0.0.0", "(null)", "null", "-none-"}
_OFFLINE_STATUS_HINTS = (
    "unreachable",
    "unknown",
    "unmonitored",
    "lagged",
    "timeout",
    "offline",
    "unavail",
)


def _is_peer_online(*, ip: str, status: str | None) -> bool:
    if ip.strip().lower() in _BAD_IPS:
        return False
    normalized_status = (status or "").strip().lower()
    if any(hint in normalized_status for hint in _OFFLINE_STATUS_HINTS):
        return False
    return True


def filter_sip_peers(
    entries: list[dict[str, str]],
    *,
    peer_name_regex: str,
) -> list[VoipSipPeer]:
    pattern = re.compile(peer_name_regex)
    peers: list[VoipSipPeer] = []
    for entry in entries:
        lowered = {str(k).strip().lower(): str(v or "").strip() for k, v in entry.items()}
        dynamic = lowered.get("dynamic", "").strip().lower()
        if dynamic != "yes":
            continue
        name = lowered.get("objectname", "").strip()
        if not name or not pattern.match(name):
            continue
        ip = lowered.get("ipaddress", "").strip()
        port_raw = lowered.get("ipport", "").strip()
        port = int(port_raw) if port_raw.isdigit() else None
        status = lowered.get("status", "").strip() or None
        peers.append(
            VoipSipPeer(
                name=name,
                ip=ip,
                port=port,
                status=status,
                online=_is_peer_online(ip=ip, status=status),
            )
        )

    def sort_key(item: VoipSipPeer) -> tuple[int, int | str]:
        if item.name.isdigit():
            return (0, int(item.name))
        return (1, item.name.lower())

    peers.sort(key=sort_key)
    return peers


def filter_connected_sip_peers(
    entries: list[dict[str, str]],
    *,
    peer_name_regex: str,
) -> list[ConnectedVoipSipPeer]:
    peers = filter_sip_peers(entries, peer_name_regex=peer_name_regex)
    return [
        ConnectedVoipSipPeer(
            name=item.name,
            ip=item.ip,
            port=item.port,
            status=item.status,
        )
        for item in peers
        if item.online
    ]


class IssabelAmiProvider:
    def __init__(
        self,
        *,
        host: str | None,
        rawman_url: str | None = None,
        port: int,
        username: str | None,
        secret: str | None,
        timeout_seconds: int = 8,
        use_tls: bool = False,
        peer_name_regex: str = r"^\d+$",
    ) -> None:
        self._host = host
        self._rawman_url = rawman_url
        self._port = int(port)
        self._username = username
        self._secret = secret
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._use_tls = bool(use_tls)
        self._peer_name_regex = peer_name_regex or r"^\d+$"

    async def _run_sip_peers(self) -> list[dict[str, str]]:
        if not self._username or not self._secret:
            raise ValueError("ISSABEL AMI nao configurado")
        if self._rawman_url:
            client = AmiHttpRawmanClient(
                rawman_url=self._rawman_url,
                username=self._username,
                secret=self._secret,
                timeout_seconds=self._timeout_seconds,
            )
        else:
            if not self._host:
                raise ValueError("ISSABEL AMI nao configurado")
            client = AmiClient(
                host=self._host,
                port=self._port,
                username=self._username,
                secret=self._secret,
                timeout_seconds=self._timeout_seconds,
                use_tls=self._use_tls,
            )
        return await client.run_sip_peers()

    async def list_voip_overview(self) -> VoipPeerOverview:
        entries = await self._run_sip_peers()
        peers = filter_sip_peers(entries, peer_name_regex=self._peer_name_regex)
        connected_peers = [
            ConnectedVoipSipPeer(
                name=item.name,
                ip=item.ip,
                port=item.port,
                status=item.status,
            )
            for item in peers
            if item.online
        ]
        total_count = len(peers)
        online_count = len(connected_peers)
        return VoipPeerOverview(
            total_count=total_count,
            online_count=online_count,
            offline_count=max(0, total_count - online_count),
            connected_peers=connected_peers,
        )

    async def list_connected_voips(self) -> list[ConnectedVoipSipPeer]:
        overview = await self.list_voip_overview()
        return overview.connected_peers

    def transport_name(self) -> str:
        return "http_rawman" if self._rawman_url else "tcp_ami"

    def endpoint_label(self) -> str:
        if self._rawman_url:
            parsed = urlsplit(self._rawman_url)
            host = parsed.hostname or parsed.netloc or ""
            port = parsed.port
            path = parsed.path or ""
            if host and port:
                return f"{host}:{port}{path}"
            if parsed.netloc:
                return f"{parsed.netloc}{path}"
            return self._rawman_url
        if self._host:
            return f"{self._host}:{self._port}"
        return "-"


__all__ = [
    "AmiError",
    "ConnectedVoipSipPeer",
    "IssabelAmiProvider",
    "VoipPeerOverview",
    "VoipSipPeer",
    "filter_sip_peers",
    "filter_connected_sip_peers",
]

