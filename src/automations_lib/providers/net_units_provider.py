from __future__ import annotations

from dataclasses import dataclass

from src.automations_lib.providers.issabel_ami_provider import ConnectedVoipSipPeer


@dataclass(frozen=True)
class NetUnitDefinition:
    name: str
    primary_extension: str
    redundancy_extensions: tuple[str, ...] = ()

    @property
    def checked_extensions(self) -> tuple[str, ...]:
        ordered = [self.primary_extension, *self.redundancy_extensions]
        unique: list[str] = []
        seen: set[str] = set()
        for extension in ordered:
            normalized = str(extension or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            unique.append(normalized)
        return tuple(unique)


@dataclass(frozen=True)
class NetUnitStatus:
    name: str
    online: bool
    active_extension: str | None
    active_ip: str | None
    active_port: int | None
    active_status: str | None
    checked_extensions: tuple[str, ...]


@dataclass(frozen=True)
class NetUnitsOverview:
    total_count: int
    online_count: int
    offline_count: int
    units: list[NetUnitStatus]


DEFAULT_NET_UNITS: tuple[NetUnitDefinition, ...] = (
    NetUnitDefinition("Alfaro", "2511", ("2510", "1112")),
    NetUnitDefinition("Unidade 1", "1101", ("1102",)),
    NetUnitDefinition("Unidade 2", "1201", ("3333",)),
    NetUnitDefinition("Unidade 3", "1301", ("1302",)),
    NetUnitDefinition("Unidade 4", "1402", ("1425",)),
    NetUnitDefinition("Unidade 5", "1501", ("1525",)),
    NetUnitDefinition("Unidade 6", "1601", ("1602",)),
    NetUnitDefinition("Unidade 9", "1901", ("1902",)),
    NetUnitDefinition("Escolinha", "2301", ("1102",)),
    NetUnitDefinition("Collis1", "3333", ("1201",)),
    NetUnitDefinition("Collis2", "3331", ("9101",)),
    NetUnitDefinition("LT", "3101", ("3102",)),
    NetUnitDefinition("Marketing", "1233", ("1234",)),
)


def evaluate_net_units(
    connected_peers: list[ConnectedVoipSipPeer],
    *,
    units: tuple[NetUnitDefinition, ...] = DEFAULT_NET_UNITS,
) -> NetUnitsOverview:
    online_peers_by_extension = {
        str(peer.name).strip(): peer
        for peer in connected_peers
        if str(peer.name).strip()
    }
    statuses: list[NetUnitStatus] = []
    online_count = 0
    for unit in units:
        active_peer: ConnectedVoipSipPeer | None = None
        active_extension: str | None = None
        if unit.primary_extension in online_peers_by_extension:
            active_extension = unit.primary_extension
            active_peer = online_peers_by_extension[unit.primary_extension]
        else:
            for redundancy in unit.redundancy_extensions:
                if redundancy in online_peers_by_extension:
                    active_extension = redundancy
                    active_peer = online_peers_by_extension[redundancy]
                    break
        is_online = active_extension is not None
        if is_online:
            online_count += 1
        statuses.append(
            NetUnitStatus(
                name=unit.name,
                online=is_online,
                active_extension=active_extension,
                active_ip=(active_peer.ip if active_peer is not None else None),
                active_port=(active_peer.port if active_peer is not None else None),
                active_status=(active_peer.status if active_peer is not None else None),
                checked_extensions=unit.checked_extensions,
            )
        )
    total_count = len(statuses)
    return NetUnitsOverview(
        total_count=total_count,
        online_count=online_count,
        offline_count=max(0, total_count - online_count),
        units=statuses,
    )


__all__ = [
    "DEFAULT_NET_UNITS",
    "NetUnitDefinition",
    "NetUnitStatus",
    "NetUnitsOverview",
    "evaluate_net_units",
]
