from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from src.automations_lib.providers.ami_client import (
    AmiError,
    AmiHttpRawmanClient,
    parse_rawman_messages,
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


@pytest.mark.asyncio
async def test_http_rawman_login_sippeers_success(monkeypatch) -> None:
    state = {"logged_in": False}

    def handler(request: httpx.Request) -> httpx.Response:
        action = parse_qs(urlparse(str(request.url)).query).get("action", [""])[0].lower()
        if action == "login":
            state["logged_in"] = True
            return httpx.Response(200, text="Response: Success\r\nMessage: Authentication accepted\r\n\r\n")
        if action == "sippeers":
            if not state["logged_in"]:
                return httpx.Response(200, text="Response: Error\r\nMessage: Permission denied\r\n\r\n")
            return httpx.Response(
                200,
                text=(
                    "Response: Success\r\nMessage: Peer status list will follow\r\n\r\n"
                    "Event: PeerEntry\r\nObjectName: 1101\r\nDynamic: yes\r\nIPaddress: 10.0.0.1\r\nIPport: 5060\r\n\r\n"
                    "Event: PeerEntry\r\nObjectName: 1102\r\nDynamic: yes\r\nIPaddress: 10.0.0.2\r\nIPport: 5060\r\n\r\n"
                    "Event: PeerlistComplete\r\nEventList: Complete\r\nListItems: 2\r\n\r\n"
                ),
            )
        if action == "logoff":
            return httpx.Response(200, text="Response: Goodbye\r\nMessage: Thanks\r\n\r\n")
        return httpx.Response(200, text="Response: Error\r\nMessage: Missing action in request\r\n\r\n")

    monkeypatch.setattr(
        "src.automations_lib.providers.ami_client.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    client = AmiHttpRawmanClient(
        rawman_url="http://coalapabx.ddns.net:8088/asterisk/rawman",
        username="zabbix",
        secret="123",
        timeout_seconds=5,
    )
    entries = await client.run_sip_peers()
    assert len(entries) == 2
    assert entries[0].get("objectname") == "1101"


@pytest.mark.asyncio
async def test_http_rawman_login_failed(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        action = parse_qs(urlparse(str(request.url)).query).get("action", [""])[0].lower()
        if action == "login":
            return httpx.Response(200, text="Response: Error\r\nMessage: Authentication failed\r\n\r\n")
        return httpx.Response(200, text="Response: Error\r\nMessage: Permission denied\r\n\r\n")

    monkeypatch.setattr(
        "src.automations_lib.providers.ami_client.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    client = AmiHttpRawmanClient(
        rawman_url="http://pbx/asterisk/rawman",
        username="bad",
        secret="bad",
        timeout_seconds=5,
    )
    with pytest.raises(AmiError, match="login failed"):
        await client.run_sip_peers()


@pytest.mark.asyncio
async def test_http_rawman_sippeers_permission_denied(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        action = parse_qs(urlparse(str(request.url)).query).get("action", [""])[0].lower()
        if action == "login":
            return httpx.Response(200, text="Response: Success\r\nMessage: Authentication accepted\r\n\r\n")
        if action == "sippeers":
            return httpx.Response(200, text="Response: Error\r\nMessage: Permission denied\r\n\r\n")
        return httpx.Response(200, text="Response: Goodbye\r\nMessage: Thanks\r\n\r\n")

    monkeypatch.setattr(
        "src.automations_lib.providers.ami_client.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    client = AmiHttpRawmanClient(
        rawman_url="http://pbx/asterisk/rawman",
        username="ok",
        secret="ok",
        timeout_seconds=5,
    )
    with pytest.raises(AmiError, match="sippeers failed: permission denied"):
        await client.run_sip_peers()


@pytest.mark.asyncio
async def test_http_rawman_timeout(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectTimeout("timeout")

    monkeypatch.setattr(
        "src.automations_lib.providers.ami_client.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    client = AmiHttpRawmanClient(
        rawman_url="http://pbx/asterisk/rawman",
        username="ok",
        secret="ok",
        timeout_seconds=1,
    )
    with pytest.raises(AmiError, match="timeout"):
        await client.run_sip_peers()


def test_parse_rawman_messages_parses_multiple_blocks() -> None:
    text = (
        "Response: Success\r\nMessage: Authentication accepted\r\n\r\n"
        "Event: PeerEntry\r\nObjectName: 1101\r\nIPaddress: 10.0.0.1\r\n\r\n"
        "Event: PeerEntry\r\nObjectName: 1102\r\nIPaddress: 10.0.0.2\r\n\r\n"
    )
    messages = parse_rawman_messages(text)
    assert len(messages) == 3
    assert messages[0]["response"] == "Success"
    assert messages[1]["event"] == "PeerEntry"
    assert messages[2]["objectname"] == "1102"

