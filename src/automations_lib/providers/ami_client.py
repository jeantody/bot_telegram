from __future__ import annotations

import asyncio
from collections.abc import Iterable
import ssl
import uuid

import httpx


class AmiError(Exception):
    pass


class AmiClient:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        secret: str,
        timeout_seconds: int = 8,
        use_tls: bool = False,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._secret = secret
        self._timeout_seconds = max(1, int(timeout_seconds))
        self._use_tls = bool(use_tls)

    async def run_sip_peers(self) -> list[dict[str, str]]:
        writer: asyncio.StreamWriter | None = None
        try:
            ssl_ctx: ssl.SSLContext | None = None
            if self._use_tls:
                # AMI TLS in Issabel/Asterisk commonly uses self-signed certs.
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port, ssl=ssl_ctx),
                timeout=self._timeout_seconds,
            )
            # Banner line, e.g. "Asterisk Call Manager/5.0".
            await self._readline(reader, allow_timeout=True)

            login_id = self._new_action_id()
            await self._send_action(
                writer,
                [
                    "Action: Login",
                    f"Username: {self._username}",
                    f"Secret: {self._secret}",
                    "Events: off",
                    f"ActionID: {login_id}",
                ],
            )
            login_resp = await self._wait_for_response(reader, action_id=login_id)
            if login_resp.get("response", "").strip().lower() != "success":
                message = login_resp.get("message", "").strip() or "unknown"
                raise AmiError(f"login failed: {message}")

            action_id = self._new_action_id()
            await self._send_action(
                writer,
                [
                    "Action: SIPpeers",
                    f"ActionID: {action_id}",
                ],
            )

            entries: list[dict[str, str]] = []
            sippeers_response_seen = False
            while True:
                msg = await self._read_message(reader)
                if msg is None:
                    break
                if not msg:
                    continue

                response = msg.get("response", "").strip().lower()
                if response:
                    if not sippeers_response_seen:
                        sippeers_response_seen = True
                        if response != "success":
                            message = msg.get("message", "").strip() or "unknown"
                            if "permission denied" in message.lower():
                                raise AmiError("sippeers failed: permission denied")
                            raise AmiError(f"sippeers failed: {message}")
                    continue

                event = msg.get("event", "").strip().lower()
                if event == "peerentry":
                    entries.append(msg)
                    continue
                if event == "peerlistcomplete":
                    break

            return entries
        except asyncio.TimeoutError as exc:
            raise AmiError("timeout") from exc
        finally:
            if writer is not None:
                try:
                    await self._send_action(writer, ["Action: Logoff"])
                except Exception:
                    pass
                try:
                    writer.close()
                except Exception:
                    pass
                try:
                    await writer.wait_closed()
                except Exception:
                    pass

    @staticmethod
    def _new_action_id() -> str:
        return uuid.uuid4().hex

    async def _wait_for_response(
        self,
        reader: asyncio.StreamReader,
        *,
        action_id: str,
    ) -> dict[str, str]:
        while True:
            msg = await self._read_message(reader)
            if msg is None:
                raise AmiError("connection closed")
            if not msg:
                continue
            if msg.get("response"):
                # Some AMI responses include ActionID, some don't.
                if not msg.get("actionid") or msg.get("actionid") == action_id:
                    return msg

    async def _read_message(
        self, reader: asyncio.StreamReader
    ) -> dict[str, str] | None:
        result: dict[str, str] = {}
        saw_any_line = False
        while True:
            line = await self._readline(reader)
            if line is None:
                return None if not saw_any_line else result
            if line == "":
                return result
            saw_any_line = True
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)
            key = key.strip().lower()
            if not key:
                continue
            result[key] = value.lstrip()

    async def _readline(
        self,
        reader: asyncio.StreamReader,
        *,
        allow_timeout: bool = False,
    ) -> str | None:
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=self._timeout_seconds)
        except asyncio.TimeoutError as exc:
            if allow_timeout:
                return None
            raise AmiError("timeout") from exc
        if raw == b"":
            return None
        return raw.decode(errors="replace").rstrip("\r\n")

    @staticmethod
    async def _send_action(writer: asyncio.StreamWriter, lines: list[str]) -> None:
        payload = "\r\n".join(lines) + "\r\n\r\n"
        writer.write(payload.encode("utf-8"))
        await writer.drain()


class AmiHttpRawmanClient:
    def __init__(
        self,
        *,
        rawman_url: str,
        username: str,
        secret: str,
        timeout_seconds: int = 8,
    ) -> None:
        self._rawman_url = rawman_url
        self._username = username
        self._secret = secret
        self._timeout_seconds = max(1, int(timeout_seconds))

    async def run_sip_peers(self) -> list[dict[str, str]]:
        timeout = httpx.Timeout(self._timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            try:
                login_text = await self._request_rawman(
                    client,
                    params={
                        "action": "login",
                        "username": self._username,
                        "secret": self._secret,
                    },
                    phase="login",
                )
                login_messages = parse_rawman_messages(login_text)
                login_response = _first_response(login_messages)
                if login_response.get("response", "").lower() != "success":
                    message = login_response.get("message") or "unknown"
                    if "permission denied" in message.lower():
                        raise AmiError("login failed: permission denied")
                    raise AmiError(f"login failed: {message}")

                sippeers_text = await self._request_rawman(
                    client,
                    params={"action": "SIPpeers"},
                    phase="sippeers",
                )
                sippeers_messages = parse_rawman_messages(sippeers_text)
                sippeers_response = _first_response(sippeers_messages)
                if sippeers_response.get("response", "").lower() != "success":
                    message = sippeers_response.get("message") or "unknown"
                    if "permission denied" in message.lower():
                        raise AmiError("sippeers failed: permission denied")
                    raise AmiError(f"sippeers failed: {message}")

                entries: list[dict[str, str]] = []
                for message in sippeers_messages:
                    if message.get("event", "").lower() == "peerentry":
                        entries.append(message)
                return entries
            finally:
                # Best effort; never mask original failure.
                try:
                    await self._request_rawman(
                        client, params={"action": "logoff"}, phase="logoff"
                    )
                except Exception:
                    pass

    async def _request_rawman(
        self,
        client: httpx.AsyncClient,
        *,
        params: dict[str, str],
        phase: str,
    ) -> str:
        try:
            response = await client.get(self._rawman_url, params=params)
            response.raise_for_status()
            return response.text or ""
        except httpx.TimeoutException as exc:
            raise AmiError("timeout") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "unknown"
            raise AmiError(f"{phase} failed: http status {status}") from exc
        except httpx.HTTPError as exc:
            raise AmiError(f"{phase} failed: http error") from exc


def parse_rawman_messages(text: str) -> list[dict[str, str]]:
    if text is None:
        raise AmiError("invalid rawman response")
    normalized = text.replace("\r\n", "\n")
    blocks = [block.strip() for block in normalized.split("\n\n") if block.strip()]
    messages: list[dict[str, str]] = []
    for block in blocks:
        message: dict[str, str] = {}
        for line in block.split("\n"):
            if ":" not in line:
                continue
            key, value = line.split(":", maxsplit=1)
            key = key.strip().lower()
            if not key:
                continue
            message[key] = value.strip()
        if message:
            messages.append(message)
    return messages


def _first_response(messages: Iterable[dict[str, str]]) -> dict[str, str]:
    for message in messages:
        if message.get("response"):
            return message
    raise AmiError("invalid rawman response")

