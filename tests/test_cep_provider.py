from __future__ import annotations

import httpx
import pytest

from src.automations_lib.providers.cep_provider import CepProvider


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
async def test_lookup_cep_success(monkeypatch) -> None:
    payload = {
        "cep": "01001-000",
        "logradouro": "Praca da Se",
        "bairro": "Se",
        "localidade": "Sao Paulo",
        "uf": "SP",
        "ibge": "3550308",
    }
    url = "https://viacep.com.br/ws/01001000/json/"
    monkeypatch.setattr(
        "src.automations_lib.providers.cep_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient({url: FakeResponse(payload)}, **kwargs),
    )
    provider = CepProvider(timeout_seconds=5, url_template="https://viacep.com.br/ws/{cep}/json/")
    info = await provider.lookup("01001-000")

    assert info.cep == "01001-000"
    assert info.localidade == "Sao Paulo"


@pytest.mark.asyncio
async def test_lookup_cep_invalid() -> None:
    provider = CepProvider(timeout_seconds=5, url_template="https://viacep.com.br/ws/{cep}/json/")
    with pytest.raises(ValueError):
        await provider.lookup("abc")


@pytest.mark.asyncio
async def test_lookup_cep_not_found(monkeypatch) -> None:
    url = "https://viacep.com.br/ws/99999999/json/"
    monkeypatch.setattr(
        "src.automations_lib.providers.cep_provider.httpx.AsyncClient",
        lambda **kwargs: FakeAsyncClient({url: FakeResponse({"erro": True})}, **kwargs),
    )
    provider = CepProvider(timeout_seconds=5, url_template="https://viacep.com.br/ws/{cep}/json/")
    with pytest.raises(ValueError):
        await provider.lookup("99999999")
