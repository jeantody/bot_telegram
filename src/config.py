from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    telegram_bot_token: str
    telegram_allowed_chat_id: int | None
    request_timeout_seconds: int
    automation_timeout_seconds: int
    weather_timezone: str
    weather_city_name: str
    trends_primary_url: str
    trends_fallback_url: str


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    return int(raw)


def _read_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return int(raw)


def load_settings() -> Settings:
    load_dotenv()

    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise ValueError("Missing TELEGRAM_BOT_TOKEN in environment.")

    return Settings(
        telegram_bot_token=token,
        telegram_allowed_chat_id=_read_optional_int("TELEGRAM_ALLOWED_CHAT_ID"),
        request_timeout_seconds=_read_int("REQUEST_TIMEOUT_SECONDS", 20),
        automation_timeout_seconds=_read_int("AUTOMATION_TIMEOUT_SECONDS", 30),
        weather_timezone=os.getenv("WEATHER_TIMEZONE", "America/Sao_Paulo").strip(),
        weather_city_name=os.getenv("WEATHER_CITY_NAME", "Sao Paulo").strip(),
        trends_primary_url=os.getenv(
            "TRENDS_PRIMARY_URL", "https://getdaytrends.com/brazil/"
        ).strip(),
        trends_fallback_url=os.getenv(
            "TRENDS_FALLBACK_URL", "https://trends24.in/brazil/"
        ).strip(),
    )

