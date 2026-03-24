from __future__ import annotations

from dataclasses import dataclass
import itertools
import json
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.redaction import redact_text


class ZabbixError(Exception):
    pass


@dataclass(frozen=True)
class ZabbixIntegrationStatus:
    base_url: str
    api_url: str
    version: str
    authenticated: bool


@dataclass(frozen=True)
class ZabbixHostTarget:
    hostid: str
    label: str


@dataclass(frozen=True)
class ZabbixMetricValue:
    metric_key: str
    label: str
    found: bool
    value: str | None
    units: str | None
    item_name: str | None
    item_key: str | None


@dataclass(frozen=True)
class ZabbixHostMetricsSnapshot:
    hostid: str
    label: str
    host_name: str | None
    unavailable: bool
    interface_available: int | None
    metrics: dict[str, ZabbixMetricValue]


@dataclass(frozen=True)
class _MetricSpec:
    metric_key: str
    label: str
    key_aliases: tuple[str, ...]
    name_aliases: tuple[str, ...]


_METRIC_SPECS: tuple[_MetricSpec, ...] = (
    _MetricSpec(
        metric_key="cpu",
        label="CPU",
        key_aliases=("system.cpu.util", "system.cpu.util[0]"),
        name_aliases=("CPU utilization",),
    ),
    _MetricSpec(
        metric_key="memory",
        label="Memoria",
        key_aliases=("vm.memory.util", "vm.memory.utilization"),
        name_aliases=("Memory utilization",),
    ),
    _MetricSpec(
        metric_key="uptime",
        label="Uptime",
        key_aliases=("system.uptime",),
        name_aliases=("System uptime", "Uptime"),
    ),
    _MetricSpec(
        metric_key="disk_root_used_pct",
        label="Disco /",
        key_aliases=("vfs.fs.dependent.size[/,pused]",),
        name_aliases=("FS [/]: Space: Used, in %",),
    ),
)

_WINDOWS_DISK_HOSTIDS = frozenset({"10645", "10677"})
_WINDOWS_DISK_LETTERS = ("C", "D", "E")
_TRUENAS_DISK_HOSTIDS = frozenset({"10679"})
_TRUENAS_DISK_NAMES = ("sda", "sdb", "sdc")


class ZabbixProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_token: str,
        timeout_seconds: int = 8,
    ) -> None:
        normalized_base_url, api_url = _normalize_urls(base_url)
        self._base_url = normalized_base_url
        self._api_url = api_url
        self._api_token = api_token.strip()
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._request_ids = itertools.count(1)
        if not self._api_token:
            raise ValueError("Missing Zabbix API token.")

    async def fetch_integration_status(self) -> ZabbixIntegrationStatus:
        version = await self._call("apiinfo.version", {})
        await self._call(
            "host.get",
            {
                "output": ["hostid", "host"],
                "limit": 1,
            },
            authenticated=True,
        )
        return ZabbixIntegrationStatus(
            base_url=self._base_url,
            api_url=self._api_url,
            version=str(version),
            authenticated=True,
        )

    async def fetch_host_metrics(
        self,
        host_targets: tuple[ZabbixHostTarget, ...],
    ) -> list[ZabbixHostMetricsSnapshot]:
        if not host_targets:
            return []

        hostids = [target.hostid for target in host_targets]
        hosts = await self._call(
            "host.get",
            {
                "output": ["hostid", "host", "name", "status"],
                "hostids": hostids,
                "selectInterfaces": ["interfaceid", "available", "ip", "dns", "type", "main"],
            },
            authenticated=True,
        )
        items = await self._call(
            "item.get",
            {
                "output": ["itemid", "hostid", "name", "key_", "lastvalue", "units", "status", "state"],
                "hostids": hostids,
                "monitored": True,
                "sortfield": "name",
            },
            authenticated=True,
        )
        host_map = {
            str(item.get("hostid")): item
            for item in hosts
            if isinstance(item, dict) and item.get("hostid") is not None
        }
        items_by_host: dict[str, list[dict[str, Any]]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            hostid = str(item.get("hostid") or "")
            if not hostid:
                continue
            items_by_host.setdefault(hostid, []).append(item)

        snapshots: list[ZabbixHostMetricsSnapshot] = []
        for target in host_targets:
            host_payload = host_map.get(target.hostid)
            host_items = items_by_host.get(target.hostid, [])
            interface_available = _resolve_interface_available(host_payload)
            metrics: dict[str, ZabbixMetricValue] = {}
            for spec in _METRIC_SPECS:
                if spec.metric_key == "disk_root_used_pct":
                    metrics[spec.metric_key] = _resolve_disk_metric_value(
                        spec=spec,
                        hostid=target.hostid,
                        items=host_items,
                    )
                else:
                    metrics[spec.metric_key] = _resolve_metric_value(spec, host_items)
            snapshots.append(
                ZabbixHostMetricsSnapshot(
                    hostid=target.hostid,
                    label=target.label,
                    host_name=_resolve_host_name(host_payload),
                    unavailable=interface_available == 2 or host_payload is None,
                    interface_available=interface_available,
                    metrics=metrics,
                )
            )
        return snapshots

    async def _call(
        self,
        method: str,
        params,
        *,
        authenticated: bool = False,
    ):
        headers = {"Content-Type": "application/json-rpc"}
        if authenticated:
            headers["Authorization"] = f"Bearer {self._api_token}"
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": next(self._request_ids),
        }
        timeout = httpx.Timeout(self._timeout_seconds)
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=True,
            ) as client:
                response = await client.post(
                    self._api_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise ZabbixError("Zabbix request timed out.") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise ZabbixError(f"Zabbix HTTP error: {status}.") from exc
        except httpx.HTTPError as exc:
            raise ZabbixError("Failed to reach Zabbix API.") from exc

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError) as exc:
            raise ZabbixError("Invalid JSON response from Zabbix API.") from exc

        if not isinstance(body, dict):
            raise ZabbixError("Unexpected Zabbix API response shape.")

        if "error" in body:
            error = body.get("error")
            if not isinstance(error, dict):
                raise ZabbixError("Unknown Zabbix API error.")
            message = str(error.get("message", "")).strip()
            data = str(error.get("data", "")).strip()
            combined = redact_text(" ".join(part for part in (message, data) if part).strip())
            lowered = combined.lower()
            if authenticated and (
                "not authorized" in lowered
                or "permission" in lowered
                or "denied" in lowered
                or "session terminated" in lowered
            ):
                raise ZabbixError("Zabbix API token rejected or lacks permission.")
            raise ZabbixError(
                f"Zabbix API error in {method}: {combined or 'unknown'}."
            )

        return body.get("result")


def _normalize_urls(raw_base_url: str) -> tuple[str, str]:
    raw = (raw_base_url or "").strip()
    if not raw:
        raise ValueError("Missing Zabbix base URL.")
    candidate = raw if "://" in raw else f"https://{raw}"
    if candidate.endswith("/api_jsonrpc.php"):
        api_url = candidate.rstrip("/")
        base_url = api_url[: -len("/api_jsonrpc.php")]
    else:
        base_url = candidate.rstrip("/")
        api_url = f"{base_url}/api_jsonrpc.php"
    parsed = urlsplit(api_url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError("Invalid Zabbix base URL.")
    return base_url, api_url


def _normalize_text(value: str | None) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _resolve_metric_value(
    spec: _MetricSpec,
    items: list[dict[str, Any]],
) -> ZabbixMetricValue:
    best: dict[str, Any] | None = None
    best_rank: tuple[int, int] | None = None
    normalized_name_aliases = tuple(_normalize_text(item) for item in spec.name_aliases)

    for item in items:
        key = str(item.get("key_") or "")
        if key in spec.key_aliases:
            rank = (0, spec.key_aliases.index(key))
        else:
            name = _normalize_text(item.get("name"))
            if name not in normalized_name_aliases:
                continue
            rank = (1, normalized_name_aliases.index(name))
        if best_rank is None or rank < best_rank:
            best = item
            best_rank = rank

    if best is None:
        return ZabbixMetricValue(
            metric_key=spec.metric_key,
            label=spec.label,
            found=False,
            value=None,
            units=None,
            item_name=None,
            item_key=None,
        )

    raw_value = best.get("lastvalue")
    value = str(raw_value).strip() if raw_value is not None else ""
    if value == "":
        return ZabbixMetricValue(
            metric_key=spec.metric_key,
            label=spec.label,
            found=False,
            value=None,
            units=str(best.get("units") or "").strip() or None,
            item_name=str(best.get("name") or "").strip() or None,
            item_key=str(best.get("key_") or "").strip() or None,
        )

    return ZabbixMetricValue(
        metric_key=spec.metric_key,
        label=spec.label,
        found=True,
        value=value,
        units=str(best.get("units") or "").strip() or None,
        item_name=str(best.get("name") or "").strip() or None,
        item_key=str(best.get("key_") or "").strip() or None,
    )


def _resolve_disk_metric_value(
    *,
    spec: _MetricSpec,
    hostid: str,
    items: list[dict[str, Any]],
) -> ZabbixMetricValue:
    if hostid in _TRUENAS_DISK_HOSTIDS:
        return _resolve_truenas_disk_metric_value(spec=spec, items=items)

    if hostid not in _WINDOWS_DISK_HOSTIDS:
        return _resolve_metric_value(spec, items)

    selected: list[tuple[str, dict[str, Any]]] = []
    for drive_letter in _WINDOWS_DISK_LETTERS:
        disk_item = _find_windows_disk_item(items, drive_letter)
        if disk_item is not None:
            selected.append((drive_letter, disk_item))

    if not selected:
        return ZabbixMetricValue(
            metric_key=spec.metric_key,
            label=spec.label,
            found=False,
            value=None,
            units=None,
            item_name=None,
            item_key=None,
        )

    value_parts: list[str] = []
    item_names: list[str] = []
    item_keys: list[str] = []
    units: str | None = None
    for drive_letter, item in selected:
        value = _extract_item_value(item)
        if value is None:
            continue
        value_parts.append(f"{drive_letter}: {_format_compact_percentage(value)}")
        item_name = str(item.get("name") or "").strip()
        item_key = str(item.get("key_") or "").strip()
        if item_name:
            item_names.append(item_name)
        if item_key:
            item_keys.append(item_key)
        units = units or (str(item.get("units") or "").strip() or None)

    if not value_parts:
        return ZabbixMetricValue(
            metric_key=spec.metric_key,
            label=spec.label,
            found=False,
            value=None,
            units=None,
            item_name=None,
            item_key=None,
        )

    return ZabbixMetricValue(
        metric_key=spec.metric_key,
        label=spec.label,
        found=True,
        value=" | ".join(value_parts),
        units=units,
        item_name=" | ".join(item_names) or None,
        item_key=" | ".join(item_keys) or None,
    )


def _resolve_truenas_disk_metric_value(
    *,
    spec: _MetricSpec,
    items: list[dict[str, Any]],
) -> ZabbixMetricValue:
    selected: list[tuple[str, dict[str, Any]]] = []
    for disk_name in _TRUENAS_DISK_NAMES:
        item = _find_truenas_disk_item(items, disk_name)
        if item is not None:
            selected.append((disk_name, item))

    if not selected:
        return ZabbixMetricValue(
            metric_key=spec.metric_key,
            label=spec.label,
            found=False,
            value=None,
            units=None,
            item_name=None,
            item_key=None,
        )

    value_parts: list[str] = []
    item_names: list[str] = []
    item_keys: list[str] = []
    units: str | None = None
    for disk_name, item in selected:
        value = _extract_item_value(item)
        if value is None:
            continue
        value_parts.append(f"{disk_name}: {_format_compact_percentage(value)}")
        item_name = str(item.get("name") or "").strip()
        item_key = str(item.get("key_") or "").strip()
        if item_name:
            item_names.append(item_name)
        if item_key:
            item_keys.append(item_key)
        units = units or (str(item.get("units") or "").strip() or None)

    if not value_parts:
        return ZabbixMetricValue(
            metric_key=spec.metric_key,
            label=spec.label,
            found=False,
            value=None,
            units=None,
            item_name=None,
            item_key=None,
        )

    return ZabbixMetricValue(
        metric_key=spec.metric_key,
        label=spec.label,
        found=True,
        value=" | ".join(value_parts),
        units=units,
        item_name=" | ".join(item_names) or None,
        item_key=" | ".join(item_keys) or None,
    )


def _find_windows_disk_item(
    items: list[dict[str, Any]],
    drive_letter: str,
) -> dict[str, Any] | None:
    target_drive = f"({drive_letter.lower()}:)"
    best: dict[str, Any] | None = None
    for item in items:
        name = _normalize_text(item.get("name"))
        if "space: used, in %" not in name:
            continue
        if target_drive not in name:
            continue
        best = item
        break
    return best


def _find_truenas_disk_item(
    items: list[dict[str, Any]],
    disk_name: str,
) -> dict[str, Any] | None:
    target_name = f"[{disk_name.lower()}]: disk utilization"
    for item in items:
        name = _normalize_text(item.get("name"))
        if "truenas core:" not in name:
            continue
        if target_name not in name:
            continue
        return item
    return None


def _extract_item_value(item: dict[str, Any]) -> str | None:
    raw_value = item.get("lastvalue")
    value = str(raw_value).strip() if raw_value is not None else ""
    return value or None


def _format_compact_percentage(raw_value: str) -> str:
    try:
        value = float(str(raw_value).strip())
    except (TypeError, ValueError):
        return str(raw_value).strip()
    formatted = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{formatted}%"


def _resolve_interface_available(host_payload: dict[str, Any] | None) -> int | None:
    if not isinstance(host_payload, dict):
        return None
    interfaces = host_payload.get("interfaces")
    if not isinstance(interfaces, list) or not interfaces:
        return None
    main_interface = next(
        (
            item
            for item in interfaces
            if isinstance(item, dict) and str(item.get("main")) == "1"
        ),
        None,
    )
    selected = main_interface if isinstance(main_interface, dict) else interfaces[0]
    try:
        return int(str(selected.get("available")))
    except (TypeError, ValueError, AttributeError):
        return None


def _resolve_host_name(host_payload: dict[str, Any] | None) -> str | None:
    if not isinstance(host_payload, dict):
        return None
    for key in ("name", "host"):
        value = str(host_payload.get(key) or "").strip()
        if value:
            return value
    return None
