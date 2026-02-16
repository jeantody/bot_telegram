from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.automations_lib.providers.ssl_provider import SslProvider


@pytest.mark.asyncio
async def test_ssl_valid_info_severity_info(monkeypatch) -> None:
    provider = SslProvider(timeout_seconds=5, alert_days=30, critical_days=7)
    future = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%b %d %H:%M:%S %Y GMT")

    monkeypatch.setattr(
        provider,
        "_fetch_certificate",
        lambda host, port: {
            "notAfter": future,
            "subject": ((("commonName", "example.com"),),),
            "issuer": ((("commonName", "Fake CA"),),),
        },
    )
    info = await provider.check("example.com")

    assert info.host == "example.com"
    assert info.port == 443
    assert info.severity == "info"


@pytest.mark.asyncio
async def test_ssl_alert_and_critical(monkeypatch) -> None:
    provider = SslProvider(timeout_seconds=5, alert_days=30, critical_days=7)
    alert_future = (datetime.now(timezone.utc) + timedelta(days=20)).strftime("%b %d %H:%M:%S %Y GMT")
    critical_future = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%b %d %H:%M:%S %Y GMT")

    monkeypatch.setattr(provider, "_fetch_certificate", lambda host, port: {"notAfter": alert_future})
    info_alert = await provider.check("example.com:444")
    assert info_alert.severity == "alerta"
    assert info_alert.port == 444

    monkeypatch.setattr(provider, "_fetch_certificate", lambda host, port: {"notAfter": critical_future})
    info_critical = await provider.check("example.com")
    assert info_critical.severity == "critico"


@pytest.mark.asyncio
async def test_ssl_invalid_target() -> None:
    provider = SslProvider(timeout_seconds=5, alert_days=30, critical_days=7)
    with pytest.raises(ValueError):
        await provider.check("")
