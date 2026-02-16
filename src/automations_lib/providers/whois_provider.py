from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import re
import socket
from urllib.parse import urlparse

import httpx


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


@dataclass(frozen=True)
class WhoisInfo:
    domain: str
    registrar: str | None
    statuses: list[str]
    created_at: datetime | None
    updated_at: datetime | None
    expires_at: datetime | None
    nameservers: list[str]
    source_url: str
    raw_text: str | None = None
    owner: str | None = None
    owner_c: str | None = None
    tech_c: str | None = None
    ns_pairs: list[tuple[str, str | None, str | None]] | None = None
    dsrecord: str | None = None
    dsstatus: str | None = None
    dslastok: str | None = None
    saci: str | None = None
    status_label: str | None = None
    nic_hdl_br: str | None = None
    person: str | None = None
    nic_created: str | None = None
    nic_changed: str | None = None
    created_label: str | None = None
    changed_label: str | None = None
    expires_label: str | None = None


class WhoisProvider:
    DOMAIN_REGEX = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")

    def __init__(
        self,
        timeout_seconds: int,
        global_template: str,
        br_template: str,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._global_template = global_template
        self._br_template = br_template

    async def lookup(self, raw_input: str) -> WhoisInfo:
        domain = self._normalize_domain(raw_input)
        if domain.endswith(".br"):
            return await self._lookup_registro_br(domain)
        url = self._select_url(domain)
        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Resposta RDAP invalida.")
        return self._parse_payload(payload, domain=domain, source_url=url)

    async def _lookup_registro_br(self, domain: str) -> WhoisInfo:
        raw_text = await asyncio.to_thread(self._query_registro_br, domain)
        parsed = self._parse_registro_br_response(raw_text)
        if not parsed:
            # fallback para RDAP caso WHOIS bruto falhe no parse.
            url = self._select_url(domain)
            async with httpx.AsyncClient(
                timeout=self._timeout_seconds,
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("Resposta WHOIS/RDAP invalida.")
            info = self._parse_payload(payload, domain=domain, source_url=url)
            return WhoisInfo(
                **info.__dict__,
                raw_text=raw_text,
            )
        parsed["domain"] = parsed.get("domain") or domain
        parsed["source_url"] = "whois://whois.registro.br"
        return WhoisInfo(**parsed)

    def _query_registro_br(self, domain: str) -> str:
        with socket.create_connection(("whois.registro.br", 43), timeout=self._timeout_seconds) as sock:
            sock.sendall(f"{domain}\r\n".encode("ascii"))
            chunks: list[bytes] = []
            while True:
                part = sock.recv(4096)
                if not part:
                    break
                chunks.append(part)
        if not chunks:
            raise ValueError("Resposta WHOIS vazia.")
        return b"".join(chunks).decode("latin-1", errors="replace")

    def _normalize_domain(self, raw_input: str) -> str:
        raw = raw_input.strip().lower()
        if not raw:
            raise ValueError("Dominio nao informado.")
        if "://" in raw:
            parsed = urlparse(raw)
            host = (parsed.hostname or "").strip().lower()
        else:
            host = raw.split("/", maxsplit=1)[0].split(":", maxsplit=1)[0]
        if host.startswith("www."):
            host = host[4:]
        if not self.DOMAIN_REGEX.match(host):
            raise ValueError("Dominio invalido.")
        return host

    def _select_url(self, domain: str) -> str:
        if domain.endswith(".br"):
            return self._br_template.format(domain=domain)
        return self._global_template.format(domain=domain)

    @staticmethod
    def _parse_payload(payload: dict, domain: str, source_url: str) -> WhoisInfo:
        statuses = [str(item).strip() for item in payload.get("status", []) if str(item).strip()]
        created_at: datetime | None = None
        updated_at: datetime | None = None
        expires_at: datetime | None = None
        for event in payload.get("events", []):
            action = str(event.get("eventAction", "")).strip().lower()
            event_date = _parse_dt(event.get("eventDate"))
            if action in {"registration", "registered"} and created_at is None:
                created_at = event_date
            elif action in {"last changed", "last update of rdap database", "last changed"}:
                updated_at = event_date
            elif action in {"expiration", "expiry"} and expires_at is None:
                expires_at = event_date

        if created_at is None:
            created_at = _parse_dt(payload.get("creationDate"))
        if updated_at is None:
            updated_at = _parse_dt(payload.get("updatedDate"))
        if expires_at is None:
            expires_at = _parse_dt(payload.get("expirationDate"))

        nameservers: list[str] = []
        for item in payload.get("nameservers", []):
            value = str(item.get("ldhName", "")).strip()
            if value:
                nameservers.append(value)

        registrar = WhoisProvider._extract_registrar(payload.get("entities", []))
        return WhoisInfo(
            domain=domain,
            registrar=registrar,
            statuses=statuses,
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            nameservers=nameservers,
            source_url=source_url,
        )

    @staticmethod
    def _parse_registro_br_response(raw_text: str) -> dict:
        lines = [line.rstrip() for line in raw_text.splitlines()]
        filtered = [line for line in lines if line.strip() and not line.lstrip().startswith("%")]
        if not filtered:
            return {}

        domain_fields: dict[str, str] = {}
        nic_fields: dict[str, str] = {}
        in_nic_block = False
        ns_pairs: list[tuple[str, str | None, str | None]] = []
        pending_ns: tuple[str, str | None, str | None] | None = None

        for line in filtered:
            match = re.match(r"^([a-z0-9-]+):\s*(.*)$", line.strip(), flags=re.IGNORECASE)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            if key == "nic-hdl-br":
                in_nic_block = True

            target = nic_fields if in_nic_block else domain_fields

            if not in_nic_block and key == "nserver":
                if pending_ns is not None:
                    ns_pairs.append(pending_ns)
                pending_ns = (value, None, None)
                continue
            if not in_nic_block and key == "nsstat" and pending_ns is not None:
                pending_ns = (pending_ns[0], value, pending_ns[2])
                continue
            if not in_nic_block and key == "nslastaa" and pending_ns is not None:
                pending_ns = (pending_ns[0], pending_ns[1], value)
                continue

            if key not in target:
                target[key] = value

        if pending_ns is not None:
            ns_pairs.append(pending_ns)

        nameservers = [item[0] for item in ns_pairs]
        return {
            "domain": domain_fields.get("domain", ""),
            "registrar": "Registro.br",
            "statuses": [domain_fields.get("status", "")] if domain_fields.get("status") else [],
            "created_at": _parse_yyyymmdd(domain_fields.get("created")),
            "updated_at": _parse_yyyymmdd(domain_fields.get("changed")),
            "expires_at": _parse_yyyymmdd(domain_fields.get("expires")),
            "nameservers": nameservers,
            "source_url": "whois://whois.registro.br",
            "raw_text": raw_text,
            "owner": domain_fields.get("owner"),
            "owner_c": domain_fields.get("owner-c"),
            "tech_c": domain_fields.get("tech-c"),
            "ns_pairs": ns_pairs,
            "dsrecord": domain_fields.get("dsrecord"),
            "dsstatus": domain_fields.get("dsstatus"),
            "dslastok": domain_fields.get("dslastok"),
            "saci": domain_fields.get("saci"),
            "status_label": domain_fields.get("status"),
            "nic_hdl_br": nic_fields.get("nic-hdl-br"),
            "person": nic_fields.get("person"),
            "nic_created": nic_fields.get("created"),
            "nic_changed": nic_fields.get("changed"),
            "created_label": domain_fields.get("created"),
            "changed_label": domain_fields.get("changed"),
            "expires_label": domain_fields.get("expires"),
        }

    @staticmethod
    def _extract_registrar(entities: list[dict]) -> str | None:
        for entity in entities:
            roles = [str(role).strip().lower() for role in entity.get("roles", [])]
            if "registrar" not in roles:
                continue
            vcard = entity.get("vcardArray", [])
            if isinstance(vcard, list) and len(vcard) >= 2 and isinstance(vcard[1], list):
                for field in vcard[1]:
                    if isinstance(field, list) and field and str(field[0]).lower() == "fn":
                        if len(field) >= 4:
                            value = str(field[3]).strip()
                            if value:
                                return value
            handle = str(entity.get("handle", "")).strip()
            if handle:
                return handle
        return None


def _parse_yyyymmdd(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().split()[0]
    if not re.match(r"^\d{8}$", raw):
        return None
    try:
        year = int(raw[0:4])
        month = int(raw[4:6])
        day = int(raw[6:8])
        return datetime(year, month, day, tzinfo=timezone.utc)
    except ValueError:
        return None
