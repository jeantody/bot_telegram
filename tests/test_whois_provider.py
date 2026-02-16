from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from src.automations_lib.providers.whois_provider import WhoisProvider


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=httpx.Request("GET", "https://example.com"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses: dict[str, object], **kwargs) -> None:
        del kwargs
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        del exc_type, exc, tb
        return False

    async def get(self, url: str, **kwargs):
        del kwargs
        item = self._responses[url]
        if isinstance(item, Exception):
            raise item
        return item


@pytest.mark.asyncio
async def test_lookup_br_domain_uses_br_endpoint(monkeypatch) -> None:
    provider = WhoisProvider(
        timeout_seconds=5,
        global_template="https://rdap.org/domain/{domain}",
        br_template="https://rdap.registro.br/domain/{domain}",
    )
    raw = """
domain:      exemplo.com.br
owner:       Jean Gonçalves De Oliveira
owner-c:     JEGOL83
tech-c:      JEGOL83
nserver:     e.sec.dns.br
nsstat:      20260212 AA
nslastaa:    20260212
dsrecord:    41996 ECDSA-SHA-256 2A79
dsstatus:    20260212 DSOK
dslastok:    20260212
saci:        yes
created:     20220503 #24415475
changed:     20250506
expires:     20260503
status:      published

nic-hdl-br:  JEGOL83
person:      Jean Gonçalves De Oliveira
created:     20211208
changed:     20250929
""".strip()
    monkeypatch.setattr(provider, "_query_registro_br", lambda domain: raw)
    result = await provider.lookup("https://exemplo.com.br/path")

    assert result.domain == "exemplo.com.br"
    assert result.owner == "Jean Gonçalves De Oliveira"
    assert result.owner_c == "JEGOL83"
    assert result.tech_c == "JEGOL83"
    assert result.ns_pairs == [("e.sec.dns.br", "20260212 AA", "20260212")]
    assert result.dsrecord == "41996 ECDSA-SHA-256 2A79"
    assert result.nic_hdl_br == "JEGOL83"
    assert result.person == "Jean Gonçalves De Oliveira"
    assert result.expires_at == datetime(2026, 5, 3, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_lookup_global_domain(monkeypatch) -> None:
    payload = {"status": ["ok"], "events": [], "nameservers": [], "entities": []}
    url = "https://rdap.org/domain/example.com"
    monkeypatch.setattr(
        "src.automations_lib.providers.whois_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient({url: FakeResponse(payload)}, **kwargs),
    )
    provider = WhoisProvider(
        timeout_seconds=5,
        global_template="https://rdap.org/domain/{domain}",
        br_template="https://rdap.registro.br/domain/{domain}",
    )
    result = await provider.lookup("example.com")
    assert result.domain == "example.com"


@pytest.mark.asyncio
async def test_lookup_rejects_invalid_domain() -> None:
    provider = WhoisProvider(
        timeout_seconds=5,
        global_template="https://rdap.org/domain/{domain}",
        br_template="https://rdap.registro.br/domain/{domain}",
    )
    with pytest.raises(ValueError):
        await provider.lookup("dominio_invalido")
