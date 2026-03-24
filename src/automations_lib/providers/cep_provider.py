from __future__ import annotations

from dataclasses import dataclass
import re

import httpx


@dataclass(frozen=True)
class CepInfo:
    cep: str
    logradouro: str
    complemento: str
    bairro: str
    localidade: str
    uf: str
    ibge: str


class CepProvider:
    CEP_REGEX = re.compile(r"^\d{8}$")

    def __init__(self, timeout_seconds: int, url_template: str) -> None:
        self._timeout_seconds = timeout_seconds
        self._url_template = url_template

    async def lookup(self, raw_cep: str) -> CepInfo:
        cep = self._normalize_cep(raw_cep)
        url = self._url_template.format(cep=cep)
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        if payload.get("erro") is True:
            raise ValueError("CEP nao encontrado.")
        return CepInfo(
            cep=str(payload.get("cep", cep)).strip(),
            logradouro=str(payload.get("logradouro", "")).strip(),
            complemento=str(payload.get("complemento", "")).strip(),
            bairro=str(payload.get("bairro", "")).strip(),
            localidade=str(payload.get("localidade", "")).strip(),
            uf=str(payload.get("uf", "")).strip(),
            ibge=str(payload.get("ibge", "")).strip(),
        )

    def _normalize_cep(self, raw_cep: str) -> str:
        digits = re.sub(r"\D+", "", raw_cep or "")
        if not self.CEP_REGEX.match(digits):
            raise ValueError("CEP invalido. Use 8 digitos.")
        return digits
