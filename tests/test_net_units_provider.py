from __future__ import annotations

from src.automations_lib.providers.issabel_ami_provider import ConnectedVoipSipPeer
from src.automations_lib.providers.net_units_provider import (
    DEFAULT_NET_UNITS,
    evaluate_net_units,
)


def peer(name: str, ip: str = "10.0.0.1", status: str = "OK (10 ms)") -> ConnectedVoipSipPeer:
    return ConnectedVoipSipPeer(name=name, ip=ip, port=5060, status=status)


def test_net_units_marks_unit_online_when_primary_is_online() -> None:
    overview = evaluate_net_units([peer("1101")])

    unidade_1 = next(item for item in overview.units if item.name == "Unidade 1")
    assert unidade_1.online is True
    assert unidade_1.active_extension == "1101"
    assert unidade_1.active_ip == "10.0.0.1"
    assert unidade_1.active_port == 5060
    assert unidade_1.active_status == "OK (10 ms)"


def test_net_units_marks_unit_online_when_redundancy_is_online() -> None:
    overview = evaluate_net_units([peer("1102")])

    unidade_1 = next(item for item in overview.units if item.name == "Unidade 1")
    assert unidade_1.online is True
    assert unidade_1.active_extension == "1102"
    assert unidade_1.active_ip == "10.0.0.1"
    assert unidade_1.active_status == "OK (10 ms)"


def test_net_units_marks_unit_offline_when_all_extensions_are_offline() -> None:
    overview = evaluate_net_units([])

    unidade_1 = next(item for item in overview.units if item.name == "Unidade 1")
    assert unidade_1.online is False
    assert unidade_1.active_extension is None
    assert unidade_1.active_ip is None
    assert unidade_1.active_port is None
    assert unidade_1.active_status is None
    assert unidade_1.checked_extensions == ("1101", "1102")


def test_net_units_uses_first_online_redundancy_for_multiple_redundancies() -> None:
    overview = evaluate_net_units([peer("1112", ip="10.0.0.11"), peer("2510", ip="10.0.0.10")])

    alfaro = next(item for item in overview.units if item.name == "Alfaro")
    assert alfaro.online is True
    assert alfaro.active_extension == "2510"
    assert alfaro.active_ip == "10.0.0.10"
    assert alfaro.active_status == "OK (10 ms)"
    assert alfaro.checked_extensions == ("2511", "2510", "1112")


def test_net_units_shared_extension_keeps_multiple_units_online() -> None:
    overview = evaluate_net_units([peer("3333", ip="10.0.0.33")])

    unidade_2 = next(item for item in overview.units if item.name == "Unidade 2")
    collis1 = next(item for item in overview.units if item.name == "Collis1")

    assert overview.total_count == len(DEFAULT_NET_UNITS)
    assert unidade_2.online is True
    assert unidade_2.active_extension == "3333"
    assert unidade_2.active_ip == "10.0.0.33"
    assert unidade_2.active_status == "OK (10 ms)"
    assert collis1.online is True
    assert collis1.active_extension == "3333"
    assert collis1.active_ip == "10.0.0.33"
    assert collis1.active_status == "OK (10 ms)"
