from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any, Callable, Awaitable

import httpx

from src.bridge import BridgeNotifier
from src.config import Settings
from src.handlers import BotHandlers

try:  # pragma: no cover - exercised only when dependency is absent at runtime.
    import discord
except ModuleNotFoundError:  # pragma: no cover
    discord = None  # type: ignore[assignment]


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _BridgeChat:
    id: int


@dataclass(frozen=True)
class _BridgeUser:
    id: int
    username: str


class _BridgeMessage:
    bridge_origin = "discord"

    def __init__(
        self,
        *,
        text: str,
        chat_id: int,
        user_id: int,
        username: str,
        bridge_notifier: BridgeNotifier,
    ) -> None:
        self.text = text
        self.chat = _BridgeChat(chat_id)
        self.from_user = _BridgeUser(user_id, username)
        self._bridge_notifier = bridge_notifier

    async def reply_text(self, text: str, **kwargs: Any) -> None:
        await self._bridge_notifier.reply(self, text, **kwargs)


class _BridgeUpdate:
    def __init__(self, message: _BridgeMessage) -> None:
        self.message = message
        self.channel_post = None
        self.effective_message = message
        self.effective_chat = message.chat
        self.effective_user = message.from_user


class _BridgeBot:
    def __init__(
        self,
        *,
        username: str | None,
        bridge_notifier: BridgeNotifier,
    ) -> None:
        self.username = username
        self._bridge_notifier = bridge_notifier

    async def send_message(self, **kwargs: Any) -> None:
        await self._bridge_notifier.send_telegram(mirror=False, **kwargs)


class _BridgeContext:
    def __init__(
        self,
        *,
        username: str | None,
        args: list[str],
        bridge_notifier: BridgeNotifier,
    ) -> None:
        self.bot = _BridgeBot(username=username, bridge_notifier=bridge_notifier)
        self.args = args


class DiscordBridgeService:
    def __init__(
        self,
        *,
        settings: Settings,
        handlers: BotHandlers,
        bridge_notifier: BridgeNotifier,
    ) -> None:
        self._settings = settings
        self._handlers = handlers
        self._bridge_notifier = bridge_notifier
        self._client: Any | None = None
        self._task: asyncio.Task | None = None
        self._channel_id = settings.discord_bridge_channel_id

    async def start(self) -> None:
        if not self._settings.discord_bridge_enabled:
            return
        if discord is None:
            raise RuntimeError("discord.py nao instalado. Rode pip install -r requirements.txt.")
        if not self._settings.discord_bot_token:
            raise RuntimeError("DISCORD_BOT_TOKEN obrigatorio quando DISCORD_BRIDGE_ENABLED=true.")
        if not self._settings.discord_bridge_webhook_url:
            raise RuntimeError(
                "DISCORD_BRIDGE_WEBHOOK_URL obrigatorio quando DISCORD_BRIDGE_ENABLED=true."
            )
        if self._settings.telegram_allowed_chat_id is None:
            raise RuntimeError(
                "TELEGRAM_ALLOWED_CHAT_ID obrigatorio para espelhar Discord no Telegram."
            )
        if self._task and not self._task.done():
            return

        self._channel_id = self._channel_id or await self._resolve_channel_id()
        intents = discord.Intents.default()
        intents.message_content = True
        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready() -> None:
            logger.info(
                "discord bridge ready",
                extra={
                    "event": "discord_bridge_ready",
                    "channel_id": self._channel_id,
                },
            )

        @client.event
        async def on_message(message) -> None:
            await self._on_discord_message(message, client)

        self._task = asyncio.create_task(
            client.start(self._settings.discord_bot_token),
            name="discord_bridge_client",
        )
        self._task.add_done_callback(self._log_task_done)
        logger.info(
            "discord bridge started",
            extra={"event": "discord_bridge_started", "channel_id": self._channel_id},
        )

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.close()
        if self._task is not None:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.warning(
                    "discord bridge stopped with error",
                    extra={"event": "discord_bridge_stop_error"},
                    exc_info=True,
                )
        self._client = None
        self._task = None
        logger.info("discord bridge stopped", extra={"event": "discord_bridge_stopped"})

    def _log_task_done(self, task: asyncio.Task) -> None:
        if task.cancelled():
            return
        exc = task.exception()
        if exc is None:
            return
        logger.error(
            "discord bridge client failed",
            extra={"event": "discord_bridge_client_error"},
            exc_info=(type(exc), exc, exc.__traceback__),
        )

    async def _resolve_channel_id(self) -> int:
        async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
            response = await client.get(self._settings.discord_bridge_webhook_url)
            response.raise_for_status()
            payload = response.json()
        channel_id = payload.get("channel_id")
        if channel_id is None:
            raise RuntimeError("Webhook Discord nao retornou channel_id.")
        return int(channel_id)

    async def _on_discord_message(self, message: Any, client: Any) -> None:
        if self._channel_id is None:
            return
        if getattr(getattr(message, "channel", None), "id", None) != self._channel_id:
            return
        author = getattr(message, "author", None)
        if author is None:
            return
        if getattr(author, "bot", False):
            return
        if getattr(message, "webhook_id", None) is not None:
            return
        if client.user is not None and getattr(author, "id", None) == getattr(client.user, "id", None):
            return

        content = str(getattr(message, "content", "") or "").strip()
        if not content:
            return

        username = (
            str(getattr(author, "global_name", "") or "")
            or str(getattr(author, "name", "") or "")
            or str(getattr(author, "display_name", "") or "")
        )
        await self._bridge_notifier.mirror_incoming_discord(
            text=content,
            username=username or None,
        )

        update = _BridgeUpdate(
            _BridgeMessage(
                text=content,
                chat_id=self._settings.telegram_allowed_chat_id,
                user_id=int(getattr(author, "id", 0) or 0),
                username=username,
                bridge_notifier=self._bridge_notifier,
            )
        )
        context = _BridgeContext(
            username=str(getattr(client.user, "name", "") or ""),
            args=_command_args(content),
            bridge_notifier=self._bridge_notifier,
        )
        handler = self._handler_for_text(content)
        if handler is None:
            await self._handlers.text_handler(update, context)
            return
        await handler(update, context)

    def _handler_for_text(
        self, text: str
    ) -> Callable[[Any, Any], Awaitable[None]] | None:
        command = _command_name(text)
        if not command:
            return None
        return {
            "start": self._handlers.start_handler,
            "help": self._handlers.help_handler,
            "status": self._handlers.status_handler,
            "host": self._handlers.host_handler,
            "health": self._handlers.health_handler,
            "all": self._handlers.all_handler,
            "whois": self._handlers.whois_handler,
            "cep": self._handlers.cep_handler,
            "ping": self._handlers.ping_handler,
            "ssl": self._handlers.ssl_handler,
            "voips": self._handlers.voips_handler,
            "net": self._handlers.net_handler,
            "zabbixh": self._handlers.zabbixh_handler,
            "voip": self._handlers.voip_handler,
            "call": self._handlers.call_handler,
            "voip_logs": self._handlers.voip_logs_handler,
            "note": self._handlers.note_handler,
            "lembrete": self._handlers.lembrete_handler,
            "logs": self._handlers.logs_handler,
        }.get(command)


def _command_name(text: str) -> str | None:
    token = text.strip().split(maxsplit=1)[0].lower() if text.strip() else ""
    if not token.startswith("/"):
        return None
    token = token[1:]
    if "@" in token:
        token = token.split("@", maxsplit=1)[0]
    return token or None


def _command_args(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    parts = stripped.split()
    if not parts or not parts[0].startswith("/"):
        return []
    return parts[1:]
