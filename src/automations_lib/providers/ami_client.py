from __future__ import annotations

import asyncio
import ssl
import uuid


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
        reader: asyncio.StreamReader | None = None
        writer: asyncio.StreamWriter | None = None
        try:
            ssl_ctx: ssl.SSLContext | None = None
            if self._use_tls:
                # AMI is typically internal; when TLS is enabled on Asterisk, installs
                # often use self-signed certificates. We disable verification to avoid
                # operational friction, but this is less secure.
                ssl_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                ssl_ctx.check_hostname = False
                ssl_ctx.verify_mode = ssl.CERT_NONE

            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port, ssl=ssl_ctx),
                timeout=self._timeout_seconds,
            )

            # Discard greeting/banner line (e.g. "Asterisk Call Manager/5.0").
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
                    # There is at least one immediate response to SIPpeers; capture errors
                    # early, but don't require ActionID matching for compatibility.
                    if not sippeers_response_seen:
                        sippeers_response_seen = True
                        if response != "success":
                            message = msg.get("message", "").strip() or "unknown"
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
                # Some AMI responses include ActionID; some don't. Accept either.
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

