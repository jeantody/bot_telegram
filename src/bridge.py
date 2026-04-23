from __future__ import annotations

import html
import logging
import re
from typing import Any

import httpx
from telegram.constants import ParseMode

from src.config import Settings
from src.message_utils import split_message

logger = logging.getLogger(__name__)


class BridgeDeliveryError(RuntimeError):
    pass


def discord_text_from_telegram_html(value: str) -> str:
    text = value or ""
    text = re.sub(r"<\s*b\s*>(.*?)<\s*/\s*b\s*>", r"**\1**", text, flags=re.I | re.S)
    text = re.sub(
        r"<\s*strong\s*>(.*?)<\s*/\s*strong\s*>",
        r"**\1**",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"<\s*code\s*>(.*?)<\s*/\s*code\s*>",
        r"`\1`",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(
        r"<\s*a\s+[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)<\s*/\s*a\s*>",
        r"\2 (\1)",
        text,
        flags=re.I | re.S,
    )
    text = re.sub(r"<\s*br\s*/?\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text.strip()


class BridgeNotifier:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._telegram_bot: Any | None = None

    def set_telegram_bot(self, bot: Any | None) -> None:
        self._telegram_bot = bot

    @property
    def discord_output_enabled(self) -> bool:
        return bool(
            self._settings.discord_bridge_enabled
            and self._settings.discord_bridge_webhook_url
        )

    @property
    def telegram_output_enabled(self) -> bool:
        return self._telegram_bot is not None and (
            self._settings.telegram_allowed_chat_id is not None
        )

    async def reply(
        self,
        message: Any,
        text: str,
        *,
        mirror: bool = True,
        **telegram_kwargs: Any,
    ) -> None:
        origin = getattr(message, "bridge_origin", "telegram")
        if origin == "discord":
            await self._safe_send_discord(text)
            if mirror:
                await self.send_telegram(
                    chat_id=self._settings.telegram_allowed_chat_id,
                    text=text,
                    mirror=False,
                    **telegram_kwargs,
                )
            return

        await message.reply_text(text, **telegram_kwargs)
        if mirror:
            await self._safe_send_discord(text)

    async def send_telegram(
        self,
        *,
        chat_id: int | None,
        text: str,
        mirror: bool = True,
        **kwargs: Any,
    ) -> None:
        if self._telegram_bot is None:
            raise BridgeDeliveryError("Telegram bot indisponivel para ponte.")
        if chat_id is None:
            raise BridgeDeliveryError("Telegram chat_id indisponivel para ponte.")
        await self._telegram_bot.send_message(chat_id=chat_id, text=text, **kwargs)
        if mirror:
            await self._safe_send_discord(text)

    async def send_discord(self, text: str) -> None:
        if not self.discord_output_enabled:
            return
        content = discord_text_from_telegram_html(text)
        if not content:
            return
        await self.send_discord_plain(content)

    async def send_discord_plain(self, content: str) -> None:
        if not self.discord_output_enabled:
            return
        if not content:
            return
        for chunk in split_message(content, max_length=1900):
            await self._post_discord_webhook(chunk)

    async def mirror_incoming_telegram(
        self,
        *,
        text: str | None,
        username: str | None,
    ) -> None:
        if not text:
            return
        source = f"Telegram @{username}" if username else "Telegram"
        await self.send_discord_plain(f"**{source}**\n{text}")

    async def mirror_incoming_discord(
        self,
        *,
        text: str,
        username: str | None,
    ) -> None:
        if not self.telegram_output_enabled:
            return
        source = f"Discord @{username}" if username else "Discord"
        await self.send_telegram(
            chat_id=self._settings.telegram_allowed_chat_id,
            text=f"<b>{html.escape(source)}</b>\n{html.escape(text)}",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            mirror=False,
        )

    async def _post_discord_webhook(self, content: str) -> None:
        payload = {
            "content": content,
            "allowed_mentions": {"parse": []},
        }
        async with httpx.AsyncClient(timeout=self._settings.request_timeout_seconds) as client:
            try:
                response = await client.post(
                    self._settings.discord_bridge_webhook_url,
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                logger.warning(
                    "discord bridge webhook send failed",
                    extra={"event": "discord_bridge_webhook_error"},
                    exc_info=True,
                )
                raise BridgeDeliveryError(f"Discord webhook falhou: {exc}") from exc

    async def _safe_send_discord(self, text: str) -> None:
        try:
            await self.send_discord(text)
        except Exception:
            logger.warning(
                "discord bridge mirror failed",
                extra={"event": "discord_bridge_mirror_error"},
                exc_info=True,
            )
