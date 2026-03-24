from __future__ import annotations

import httpx
import pytest

from src.automations_lib.providers.zabbix_provider import (
    ZabbixError,
    ZabbixHostTarget,
    ZabbixProvider,
)


def _make_async_client_factory(handler):
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*, timeout, follow_redirects):
        return real_async_client(
            transport=transport,
            timeout=timeout,
            follow_redirects=follow_redirects,
        )

    return factory


def _mock_host_and_item_calls(monkeypatch, *, hosts, items) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "host.get" in payload:
            return httpx.Response(
                200,
                json={"jsonrpc": "2.0", "result": hosts, "id": 1},
            )
        return httpx.Response(
            200,
            json={"jsonrpc": "2.0", "result": items, "id": 2},
        )

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )


@pytest.mark.asyncio
async def test_fetch_integration_status_uses_bearer_token_and_returns_version(monkeypatch) -> None:
    seen_authorization: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "apiinfo.version" in payload:
            seen_authorization.append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "7.0.4", "id": 1})
        if "host.get" in payload:
            seen_authorization.append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": [], "id": 2})
        raise AssertionError(f"unexpected payload: {payload}")

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    result = await provider.fetch_integration_status()

    assert result.base_url == "https://aurora.acctunnel.space/zabbix"
    assert result.api_url == "https://aurora.acctunnel.space/zabbix/api_jsonrpc.php"
    assert result.version == "7.0.4"
    assert result.authenticated is True
    assert seen_authorization == [None, "Bearer zbx-token"]


@pytest.mark.asyncio
async def test_fetch_integration_status_rejects_invalid_token(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "apiinfo.version" in payload:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "7.0.4", "id": 1})
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32602,
                    "message": "Not authorized.",
                    "data": "Invalid params.",
                },
                "id": 2,
            },
        )

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="wrong-token",
        timeout_seconds=5,
    )

    with pytest.raises(ZabbixError, match="token rejected or lacks permission"):
        await provider.fetch_integration_status()


@pytest.mark.asyncio
async def test_fetch_integration_status_times_out(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=1,
    )

    with pytest.raises(ZabbixError, match="timed out"):
        await provider.fetch_integration_status()


@pytest.mark.asyncio
async def test_fetch_integration_status_handles_generic_api_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "apiinfo.version" in payload:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "7.0.4", "id": 1})
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "error": {
                    "code": -32500,
                    "message": "Application error.",
                    "data": "Host is unavailable.",
                },
                "id": 2,
            },
        )

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    with pytest.raises(ZabbixError, match="Host is unavailable"):
        await provider.fetch_integration_status()


@pytest.mark.asyncio
async def test_fetch_integration_status_accepts_full_api_url(monkeypatch) -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        seen_urls.append(str(request.url))
        if "apiinfo.version" in payload:
            return httpx.Response(200, json={"jsonrpc": "2.0", "result": "7.0.4", "id": 1})
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": [], "id": 2})

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix/api_jsonrpc.php",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    result = await provider.fetch_integration_status()

    assert result.base_url == "https://aurora.acctunnel.space/zabbix"
    assert result.api_url == "https://aurora.acctunnel.space/zabbix/api_jsonrpc.php"
    assert seen_urls == [
        "https://aurora.acctunnel.space/zabbix/api_jsonrpc.php",
        "https://aurora.acctunnel.space/zabbix/api_jsonrpc.php",
    ]


@pytest.mark.asyncio
async def test_fetch_host_metrics_resolves_hosts_and_matches_all_four_metrics(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "host.get" in payload:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": [
                        {
                            "hostid": "10679",
                            "name": "01_TrueNas",
                            "interfaces": [{"main": "1", "available": "1"}],
                        },
                        {
                            "hostid": "10676",
                            "name": "13_Painel_De_Senhas",
                            "interfaces": [{"main": "1", "available": "1"}],
                        },
                    ],
                    "id": 1,
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "result": [
                    {
                        "hostid": "10679",
                        "name": "CPU utilization",
                        "key_": "system.cpu.util[0]",
                        "lastvalue": "8",
                        "units": "%",
                    },
                    {
                        "hostid": "10679",
                        "name": "Memory utilization",
                        "key_": "vm.memory.util",
                        "lastvalue": "70.99874464066627",
                        "units": "%",
                    },
                    {
                        "hostid": "10679",
                        "name": "Uptime",
                        "key_": "system.uptime",
                        "lastvalue": "7876041",
                        "units": "uptime",
                    },
                    {
                        "hostid": "10679",
                        "name": "TrueNAS CORE: [sda]: Disk utilization",
                        "key_": "truenas.disk.sda",
                        "lastvalue": "12.4",
                        "units": "%",
                    },
                    {
                        "hostid": "10679",
                        "name": "TrueNAS CORE: [sdb]: Disk utilization",
                        "key_": "truenas.disk.sdb",
                        "lastvalue": "21.7",
                        "units": "%",
                    },
                    {
                        "hostid": "10679",
                        "name": "TrueNAS CORE: [sdc]: Disk utilization",
                        "key_": "truenas.disk.sdc",
                        "lastvalue": "33.2",
                        "units": "%",
                    },
                    {
                        "hostid": "10676",
                        "name": "CPU utilization",
                        "key_": "system.cpu.util",
                        "lastvalue": "2.126660000000001",
                        "units": "%",
                    },
                    {
                        "hostid": "10676",
                        "name": "Memory utilization",
                        "key_": "vm.memory.utilization",
                        "lastvalue": "34.812662",
                        "units": "%",
                    },
                    {
                        "hostid": "10676",
                        "name": "System uptime",
                        "key_": "system.uptime",
                        "lastvalue": "168901",
                        "units": "uptime",
                    },
                    {
                        "hostid": "10676",
                        "name": "FS [/]: Space: Used, in %",
                        "key_": "vfs.fs.dependent.size[/,pused]",
                        "lastvalue": "45.798339",
                        "units": "%",
                    },
                ],
                "id": 2,
            },
        )

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (
            ZabbixHostTarget(hostid="10679", label="01_TrueNas"),
            ZabbixHostTarget(hostid="10676", label="13_Painel_De_Senhas"),
        )
    )

    assert [item.hostid for item in snapshots] == ["10679", "10676"]
    assert snapshots[0].metrics["cpu"].item_key == "system.cpu.util[0]"
    assert snapshots[0].metrics["memory"].found is True
    assert snapshots[0].metrics["uptime"].value == "7876041"
    assert snapshots[0].metrics["disk_root_used_pct"].value == "sda: 12.4% | sdb: 21.7% | sdc: 33.2%"
    assert snapshots[1].metrics["disk_root_used_pct"].value == "45.798339"


@pytest.mark.asyncio
async def test_fetch_host_metrics_marks_missing_item_as_not_found(monkeypatch) -> None:
    _mock_host_and_item_calls(
        monkeypatch,
        hosts=[
            {
                "hostid": "10645",
                "name": "09_ACCBServer",
                "interfaces": [{"main": "1", "available": "1"}],
            }
        ],
        items=[
            {
                "hostid": "10645",
                "name": "CPU utilization",
                "key_": "system.cpu.util",
                "lastvalue": "0",
                "units": "%",
            },
            {
                "hostid": "10645",
                "name": "Memory utilization",
                "key_": "vm.memory.util",
                "lastvalue": "0",
                "units": "%",
            },
            {
                "hostid": "10645",
                "name": "Uptime",
                "key_": "system.uptime",
                "lastvalue": "0",
                "units": "uptime",
            },
        ],
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10645", label="09_ACCBServer"),)
    )

    assert snapshots[0].metrics["disk_root_used_pct"].found is False


@pytest.mark.asyncio
async def test_fetch_host_metrics_keeps_linux_disk_root_matching(monkeypatch) -> None:
    _mock_host_and_item_calls(
        monkeypatch,
        hosts=[
            {
                "hostid": "10756",
                "name": "Ubuntu_Hostinger",
                "interfaces": [{"main": "1", "available": "1"}],
            }
        ],
        items=[
            {
                "hostid": "10756",
                "name": "FS [/]: Space: Used, in %",
                "key_": "vfs.fs.dependent.size[/,pused]",
                "lastvalue": "63.2",
                "units": "%",
            }
        ],
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10756", label="Ubuntu_Hostinger"),)
    )

    assert snapshots[0].metrics["disk_root_used_pct"].found is True
    assert snapshots[0].metrics["disk_root_used_pct"].value == "63.2"


@pytest.mark.asyncio
async def test_fetch_host_metrics_uses_windows_disk_c_when_available(monkeypatch) -> None:
    _mock_host_and_item_calls(
        monkeypatch,
        hosts=[
            {
                "hostid": "10645",
                "name": "09_ACCBServer",
                "interfaces": [{"main": "1", "available": "1"}],
            }
        ],
        items=[
            {
                "hostid": "10645",
                "name": "FS [(C:)]: Space: Used, in %",
                "key_": "windows.disk.c",
                "lastvalue": "44.6",
                "units": "%",
            },
            {
                "hostid": "10645",
                "name": "FS [(D:)]: Space: Used, in %",
                "key_": "windows.disk.d",
                "lastvalue": "82.1",
                "units": "%",
            },
            {
                "hostid": "10645",
                "name": "FS [Dados(E:)]: Space: Used, in %",
                "key_": "windows.disk.e",
                "lastvalue": "70",
                "units": "%",
            },
        ],
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10645", label="09_ACCBServer"),)
    )

    assert snapshots[0].metrics["disk_root_used_pct"].found is True
    assert snapshots[0].metrics["disk_root_used_pct"].value == "C: 44.6% | D: 82.1% | E: 70%"


@pytest.mark.asyncio
async def test_fetch_host_metrics_uses_windows_disk_d_when_c_is_missing(monkeypatch) -> None:
    _mock_host_and_item_calls(
        monkeypatch,
        hosts=[
            {
                "hostid": "10677",
                "name": "12_TOKYO-3",
                "interfaces": [{"main": "1", "available": "1"}],
            }
        ],
        items=[
            {
                "hostid": "10677",
                "name": "FS [(D:)]: Space: Used, in %",
                "key_": "windows.disk.d",
                "lastvalue": "58.9",
                "units": "%",
            }
        ],
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10677", label="12_TOKYO-3"),)
    )

    assert snapshots[0].metrics["disk_root_used_pct"].found is True
    assert snapshots[0].metrics["disk_root_used_pct"].value == "D: 58.9%"


@pytest.mark.asyncio
async def test_fetch_host_metrics_includes_windows_disk_e_with_d(monkeypatch) -> None:
    _mock_host_and_item_calls(
        monkeypatch,
        hosts=[
            {
                "hostid": "10677",
                "name": "12_TOKYO-3",
                "interfaces": [{"main": "1", "available": "1"}],
            }
        ],
        items=[
            {
                "hostid": "10677",
                "name": "FS [(D:)]: Space: Used, in %",
                "key_": "windows.disk.d",
                "lastvalue": "58.9",
                "units": "%",
            },
            {
                "hostid": "10677",
                "name": "FS [Dados(E:)]: Space: Used, in %",
                "key_": "windows.disk.e",
                "lastvalue": "11.2",
                "units": "%",
            },
        ],
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10677", label="12_TOKYO-3"),)
    )

    assert snapshots[0].metrics["disk_root_used_pct"].found is True
    assert snapshots[0].metrics["disk_root_used_pct"].value == "D: 58.9% | E: 11.2%"


@pytest.mark.asyncio
async def test_fetch_host_metrics_matches_windows_disk_name_variations(monkeypatch) -> None:
    _mock_host_and_item_calls(
        monkeypatch,
        hosts=[
            {
                "hostid": "10645",
                "name": "09_ACCBServer",
                "interfaces": [{"main": "1", "available": "1"}],
            }
        ],
        items=[
            {
                "hostid": "10645",
                "name": "FS [Novo volume(D:)]: Space: Used, in %",
                "key_": "windows.disk.d",
                "lastvalue": "77.01",
                "units": "%",
            }
        ],
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10645", label="09_ACCBServer"),)
    )

    assert snapshots[0].metrics["disk_root_used_pct"].found is True
    assert snapshots[0].metrics["disk_root_used_pct"].value == "D: 77.01%"


@pytest.mark.asyncio
async def test_fetch_host_metrics_marks_host_unavailable_from_main_interface(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "host.get" in payload:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": [
                        {
                            "hostid": "10645",
                            "name": "09_ACCBServer",
                            "interfaces": [{"main": "1", "available": "2"}],
                        }
                    ],
                    "id": 1,
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": [], "id": 2})

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10645", label="09_ACCBServer"),)
    )

    assert snapshots[0].unavailable is True
    assert snapshots[0].interface_available == 2


@pytest.mark.asyncio
async def test_fetch_host_metrics_does_not_mark_unknown_availability_as_unavailable(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        payload = request.read().decode("utf-8")
        if "host.get" in payload:
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "result": [
                        {
                            "hostid": "10756",
                            "name": "Ubuntu_Hostinger",
                            "interfaces": [{"main": "1", "available": "0"}],
                        }
                    ],
                    "id": 1,
                },
            )
        return httpx.Response(200, json={"jsonrpc": "2.0", "result": [], "id": 2})

    monkeypatch.setattr(
        "src.automations_lib.providers.zabbix_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = ZabbixProvider(
        base_url="https://aurora.acctunnel.space/zabbix",
        api_token="zbx-token",
        timeout_seconds=5,
    )

    snapshots = await provider.fetch_host_metrics(
        (ZabbixHostTarget(hostid="10756", label="Ubuntu_Hostinger"),)
    )

    assert snapshots[0].unavailable is False
    assert snapshots[0].interface_available == 0
