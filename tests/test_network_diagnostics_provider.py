from __future__ import annotations

import pytest

from src.automations_lib.providers.network_diagnostics_provider import (
    NetworkDiagnosticsProvider,
)


@pytest.mark.asyncio
async def test_run_success_ping_and_trace(monkeypatch) -> None:
    provider = NetworkDiagnosticsProvider(
        ping_count=4,
        ping_timeout_seconds=20,
        traceroute_max_hops=5,
        traceroute_timeout_seconds=20,
    )

    async def fake_subprocess(*, args, timeout_seconds):
        del timeout_seconds
        command = " ".join(args).lower()
        if command.startswith("ping"):
            return (
                True,
                "Pacotes: Enviados = 4, Recebidos = 4, Perdidos = 0 (0% de perda)\n"
                "Mínimo = 1ms, Máximo = 3ms, Média = 2ms",
                None,
            )
        return (
            True,
            " 1  192.168.0.1\n 2  8.8.8.8",
            None,
        )

    monkeypatch.setattr(provider, "_run_subprocess", fake_subprocess)
    result = await provider.run("example.com")

    assert result.ping.ok is True
    assert result.ping.packet_loss_pct == 0
    assert result.traceroute.ok is True
    assert len(result.traceroute.hops) == 2


@pytest.mark.asyncio
async def test_run_partial_failure(monkeypatch) -> None:
    provider = NetworkDiagnosticsProvider(
        ping_count=4,
        ping_timeout_seconds=20,
        traceroute_max_hops=5,
        traceroute_timeout_seconds=20,
    )

    async def fake_subprocess(*, args, timeout_seconds):
        del timeout_seconds
        command = " ".join(args).lower()
        if command.startswith("ping"):
            return (False, "", "timeout")
        return (True, " 1  10.0.0.1", None)

    monkeypatch.setattr(provider, "_run_subprocess", fake_subprocess)
    result = await provider.run("8.8.8.8")

    assert result.ping.ok is False
    assert result.ping.error == "timeout"
    assert result.traceroute.ok is True


@pytest.mark.asyncio
async def test_run_invalid_host() -> None:
    provider = NetworkDiagnosticsProvider(
        ping_count=4,
        ping_timeout_seconds=20,
        traceroute_max_hops=5,
        traceroute_timeout_seconds=20,
    )
    with pytest.raises(ValueError):
        await provider.run("bad host")
