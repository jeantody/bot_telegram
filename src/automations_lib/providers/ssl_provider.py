from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import socket
import ssl
from urllib.parse import urlparse


@dataclass(frozen=True)
class SslInfo:
    host: str
    port: int
    subject_cn: str | None
    issuer_cn: str | None
    not_after: datetime
    days_remaining: int
    severity: str


class SslProvider:
    def __init__(
        self,
        timeout_seconds: int,
        alert_days: int,
        critical_days: int,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._alert_days = alert_days
        self._critical_days = critical_days

    async def check(self, raw_target: str) -> SslInfo:
        host, port = self._normalize_target(raw_target)
        cert = await asyncio.to_thread(self._fetch_certificate, host, port)
        not_after_raw = cert.get("notAfter")
        if not not_after_raw:
            raise ValueError("Certificado sem data de expiracao.")
        not_after = datetime.strptime(not_after_raw, "%b %d %H:%M:%S %Y %Z")
        not_after = not_after.replace(tzinfo=timezone.utc)
        days_remaining = int((not_after - datetime.now(timezone.utc)).total_seconds() // 86400)
        severity = self._classify_severity(days_remaining)
        return SslInfo(
            host=host,
            port=port,
            subject_cn=_extract_cn(cert.get("subject", ())),
            issuer_cn=_extract_cn(cert.get("issuer", ())),
            not_after=not_after,
            days_remaining=days_remaining,
            severity=severity,
        )

    def _normalize_target(self, raw_target: str) -> tuple[str, int]:
        raw = (raw_target or "").strip()
        if not raw:
            raise ValueError("Dominio nao informado.")
        if "://" in raw:
            parsed = urlparse(raw)
            host = (parsed.hostname or "").strip()
            port = int(parsed.port or 443)
        else:
            if ":" in raw:
                host, port_raw = raw.rsplit(":", maxsplit=1)
                host = host.strip()
                try:
                    port = int(port_raw)
                except ValueError as exc:
                    raise ValueError("Porta invalida.") from exc
            else:
                host = raw
                port = 443
        if not host:
            raise ValueError("Dominio invalido.")
        if port <= 0 or port > 65535:
            raise ValueError("Porta invalida.")
        return host, port

    def _fetch_certificate(self, host: str, port: int) -> dict:
        context = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=self._timeout_seconds) as sock:
            with context.wrap_socket(sock, server_hostname=host) as tls:
                return tls.getpeercert()

    def _classify_severity(self, days_remaining: int) -> str:
        if days_remaining <= self._critical_days:
            return "critico"
        if days_remaining <= self._alert_days:
            return "alerta"
        return "info"


def _extract_cn(parts: tuple) -> str | None:
    for item in parts:
        for attr in item:
            if len(attr) == 2 and str(attr[0]).lower() == "commonname":
                value = str(attr[1]).strip()
                if value:
                    return value
    return None
