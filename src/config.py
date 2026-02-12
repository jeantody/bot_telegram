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
    finance_awesomeapi_url: str
    finance_yahoo_b3_url: str
    locaweb_summary_url: str
    locaweb_components_url: str
    locaweb_incidents_url: str
    meta_orgs_url: str
    meta_outages_url_template: str
    meta_metrics_url_template: str
    umbrella_summary_url: str
    umbrella_incidents_url: str
    host_report_timezone: str


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
        finance_awesomeapi_url=os.getenv(
            "FINANCE_AWESOMEAPI_URL",
            "https://economia.awesomeapi.com.br/last/USD-BRL,EUR-BRL,BTC-BRL",
        ).strip(),
        finance_yahoo_b3_url=os.getenv(
            "FINANCE_YAHOO_B3_URL",
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EBVSP?interval=1d&range=1d",
        ).strip(),
        locaweb_summary_url=os.getenv(
            "LOCAWEB_SUMMARY_URL",
            "https://statusblog.locaweb.com.br/api/v2/summary.json",
        ).strip(),
        locaweb_components_url=os.getenv(
            "LOCAWEB_COMPONENTS_URL",
            "https://statusblog.locaweb.com.br/api/v2/components.json",
        ).strip(),
        locaweb_incidents_url=os.getenv(
            "LOCAWEB_INCIDENTS_URL",
            "https://statusblog.locaweb.com.br/api/v2/incidents.json",
        ).strip(),
        meta_orgs_url=os.getenv(
            "META_ORGS_URL",
            "https://metastatus.com/data/orgs.json",
        ).strip(),
        meta_outages_url_template=os.getenv(
            "META_OUTAGES_URL_TEMPLATE",
            "https://metastatus.com/data/outages/{org}.history.json",
        ).strip(),
        meta_metrics_url_template=os.getenv(
            "META_METRICS_URL_TEMPLATE",
            "https://metastatus.com/metrics/{org}/{metric}.json",
        ).strip(),
        umbrella_summary_url=os.getenv(
            "UMBRELLA_SUMMARY_URL",
            "https://status.umbrella.com/api/v2/summary.json",
        ).strip(),
        umbrella_incidents_url=os.getenv(
            "UMBRELLA_INCIDENTS_URL",
            "https://status.umbrella.com/api/v2/incidents.json",
        ).strip(),
        host_report_timezone=os.getenv(
            "HOST_REPORT_TIMEZONE",
            "America/Sao_Paulo",
        ).strip(),
    )
