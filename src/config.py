from __future__ import annotations

from dataclasses import dataclass, field
import json
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class AlertPriorityRule:
    pattern: str
    client: str
    system: str
    call: bool
    severity: str


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
    hostinger_summary_url: str
    hostinger_components_url: str
    hostinger_incidents_url: str
    hostinger_status_page_url: str
    host_report_timezone: str
    host_site_targets: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    bot_timezone: str = "America/Sao_Paulo"
    note_tab_chat_ids: tuple[tuple[str, int], ...] = field(default_factory=tuple)
    whois_rdap_global_url_template: str = "https://rdap.org/domain/{domain}"
    whois_rdap_br_url_template: str = "https://rdap.registro.br/domain/{domain}"
    viacep_url_template: str = "https://viacep.com.br/ws/{cep}/json/"
    ping_count: int = 4
    ping_timeout_seconds: int = 20
    traceroute_max_hops: int = 12
    traceroute_timeout_seconds: int = 30
    ssl_timeout_seconds: int = 8
    ssl_alert_days: int = 30
    ssl_critical_days: int = 7
    reminder_poll_interval_seconds: int = 15
    reminder_send_retry_limit: int = 3
    log_level: str = "INFO"
    state_db_path: str = "data/bot_state.db"
    proactive_enabled: bool = True
    proactive_check_interval_seconds: int = 300
    proactive_morning_time: str = "08:00"
    proactive_night_time: str = "21:00"
    proactive_call_repeat_count: int = 2
    alert_priority_rules: tuple[AlertPriorityRule, ...] = field(default_factory=tuple)
    voip_probe_enabled: bool = True
    voip_sipp_bin: str = "sipp"
    voip_sip_server: str = "mvtelecom.ddns.net"
    voip_sip_port: int = 5060
    voip_sip_transport: str = "udp"
    voip_sip_domain: str = "mvtelecom.ddns.net"
    voip_sip_username: str = "1101"
    voip_sip_login: str = "1101"
    voip_sip_password: str = ""
    voip_caller_id: str = "1101"
    voip_target_number: str = "1102"
    voip_hold_seconds: int = 5
    voip_call_timeout_seconds: int = 30
    voip_probe_interval_seconds: int = 3600
    voip_latency_alert_ms: int = 1500
    voip_results_db_path: str = "data/voip_probe.db"
    voip_alert_chat_id: int | None = None
    rate_limit_voip_seconds: int = 120
    rate_limit_ping_seconds: int = 20
    issabel_ami_host: str | None = None
    issabel_ami_port: int = 5038
    issabel_ami_username: str | None = None
    issabel_ami_secret: str | None = None
    issabel_ami_timeout_seconds: int = 8
    issabel_ami_use_tls: bool = False
    issabel_ami_peer_name_regex: str = r"^\d+$"


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    return int(raw)


def _read_int_or_default(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return int(raw)


def _read_optional_str(name: str) -> str | None:
    raw = os.getenv(name, "").strip()
    return raw or None


def _read_optional_int(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    return int(raw)


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _read_site_targets(name: str) -> tuple[tuple[str, str], ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid {name}: expected JSON list with [label, url] pairs."
        ) from exc
    if not isinstance(payload, list):
        raise ValueError(f"Invalid {name}: expected a JSON list.")

    normalized: list[tuple[str, str]] = []
    for item in payload:
        if isinstance(item, list) and len(item) == 2:
            label_raw, url_raw = item
        elif isinstance(item, dict):
            label_raw = item.get("label")
            url_raw = item.get("url")
        else:
            raise ValueError(
                f"Invalid {name}: each item must be [label, url] or "
                '{"label":"...","url":"..."}'
            )

        label = str(label_raw or "").strip()
        url = str(url_raw or "").strip()
        if not label or not url:
            raise ValueError(
                f"Invalid {name}: label and url are required for every item."
            )
        normalized.append((label, url))
    return tuple(normalized)


def _read_note_tab_chat_ids(name: str) -> tuple[tuple[str, int], ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return ()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid {name}: expected JSON object with tab->chat_id."
        ) from exc
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid {name}: expected JSON object.")

    pairs: list[tuple[str, int]] = []
    for key, value in payload.items():
        tab = str(key).strip().lower()
        if not tab:
            raise ValueError(f"Invalid {name}: tab name cannot be empty.")
        try:
            chat_id = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid {name}: chat_id for tab '{tab}' must be integer."
            ) from exc
        pairs.append((tab, chat_id))
    return tuple(sorted(pairs, key=lambda item: item[0]))


def _default_priority_rules() -> tuple[AlertPriorityRule, ...]:
    return (
        AlertPriorityRule(
            pattern="rogini",
            client="Rogini",
            system="Voip/Chat",
            call=True,
            severity="critico",
        ),
        AlertPriorityRule(
            pattern="pet",
            client="Pet/Sind",
            system="Voip",
            call=True,
            severity="critico",
        ),
    )


def _read_priority_rules(name: str) -> tuple[AlertPriorityRule, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return _default_priority_rules()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid {name}: expected JSON list of rule objects."
        ) from exc
    if not isinstance(payload, list):
        raise ValueError(f"Invalid {name}: expected a JSON list.")

    rules: list[AlertPriorityRule] = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError(
                f"Invalid {name}: each item must be an object with pattern/client/system."
            )
        pattern = str(item.get("pattern", "")).strip().lower()
        client = str(item.get("client", "")).strip() or "Cliente"
        system = str(item.get("system", "")).strip() or "Sistema"
        if not pattern:
            raise ValueError(f"Invalid {name}: pattern is required for every rule.")
        call = bool(item.get("call", False))
        severity = str(item.get("severity", "alerta")).strip().lower()
        if severity not in {"info", "alerta", "critico"}:
            raise ValueError(
                f"Invalid {name}: severity must be info, alerta or critico."
            )
        rules.append(
            AlertPriorityRule(
                pattern=pattern,
                client=client,
                system=system,
                call=call,
                severity=severity,
            )
        )
    return tuple(rules)


def load_settings() -> Settings:
    # Ensure local .env values win over stale shell/system environment values.
    load_dotenv(override=True)

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
        hostinger_summary_url=os.getenv(
            "HOSTINGER_SUMMARY_URL",
            "https://statuspage.hostinger.com/api/v2/summary.json",
        ).strip(),
        hostinger_components_url=os.getenv(
            "HOSTINGER_COMPONENTS_URL",
            "https://statuspage.hostinger.com/api/v2/components.json",
        ).strip(),
        hostinger_incidents_url=os.getenv(
            "HOSTINGER_INCIDENTS_URL",
            "https://statuspage.hostinger.com/api/v2/incidents.json",
        ).strip(),
        hostinger_status_page_url=os.getenv(
            "HOSTINGER_STATUS_PAGE_URL",
            "https://statuspage.hostinger.com/",
        ).strip(),
        bot_timezone=os.getenv("BOT_TIMEZONE", "America/Sao_Paulo").strip(),
        host_report_timezone=os.getenv(
            "HOST_REPORT_TIMEZONE",
            "America/Sao_Paulo",
        ).strip(),
        host_site_targets=_read_site_targets("HOST_SITE_TARGETS_JSON"),
        note_tab_chat_ids=_read_note_tab_chat_ids("NOTE_TAB_CHAT_IDS_JSON"),
        whois_rdap_global_url_template=os.getenv(
            "WHOIS_RDAP_GLOBAL_URL_TEMPLATE",
            "https://rdap.org/domain/{domain}",
        ).strip(),
        whois_rdap_br_url_template=os.getenv(
            "WHOIS_RDAP_BR_URL_TEMPLATE",
            "https://rdap.registro.br/domain/{domain}",
        ).strip(),
        viacep_url_template=os.getenv(
            "VIACEP_URL_TEMPLATE",
            "https://viacep.com.br/ws/{cep}/json/",
        ).strip(),
        ping_count=_read_int("PING_COUNT", 4),
        ping_timeout_seconds=_read_int("PING_TIMEOUT_SECONDS", 20),
        traceroute_max_hops=_read_int("TRACEROUTE_MAX_HOPS", 12),
        traceroute_timeout_seconds=_read_int("TRACEROUTE_TIMEOUT_SECONDS", 30),
        ssl_timeout_seconds=_read_int("SSL_TIMEOUT_SECONDS", 8),
        ssl_alert_days=_read_int("SSL_ALERT_DAYS", 30),
        ssl_critical_days=_read_int("SSL_CRITICAL_DAYS", 7),
        reminder_poll_interval_seconds=_read_int(
            "REMINDER_POLL_INTERVAL_SECONDS", 15
        ),
        reminder_send_retry_limit=_read_int("REMINDER_SEND_RETRY_LIMIT", 3),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        state_db_path=os.getenv("STATE_DB_PATH", "data/bot_state.db").strip(),
        proactive_enabled=_read_bool("PROACTIVE_ENABLED", True),
        proactive_check_interval_seconds=_read_int(
            "PROACTIVE_CHECK_INTERVAL_SECONDS", 300
        ),
        proactive_morning_time=os.getenv(
            "PROACTIVE_MORNING_TIME", "08:00"
        ).strip(),
        proactive_night_time=os.getenv(
            "PROACTIVE_NIGHT_TIME", "21:00"
        ).strip(),
        proactive_call_repeat_count=_read_int("PROACTIVE_CALL_REPEAT_COUNT", 2),
        alert_priority_rules=_read_priority_rules("ALERT_PRIORITY_RULES_JSON"),
        voip_probe_enabled=_read_bool("VOIP_PROBE_ENABLED", True),
        voip_sipp_bin=os.getenv("VOIP_SIPP_BIN", "sipp").strip(),
        voip_sip_server=os.getenv("VOIP_SIP_SERVER", "mvtelecom.ddns.net").strip(),
        voip_sip_port=_read_int("VOIP_SIP_PORT", 5060),
        voip_sip_transport=os.getenv("VOIP_SIP_TRANSPORT", "udp").strip().lower()
        or "udp",
        voip_sip_domain=os.getenv("VOIP_SIP_DOMAIN", "mvtelecom.ddns.net").strip(),
        voip_sip_username=os.getenv("VOIP_SIP_USERNAME", "1101").strip(),
        voip_sip_login=os.getenv("VOIP_SIP_LOGIN", "1101").strip(),
        voip_sip_password=os.getenv("VOIP_SIP_PASSWORD", "").strip(),
        voip_caller_id=os.getenv("VOIP_CALLER_ID", "1101").strip(),
        voip_target_number=os.getenv("VOIP_TARGET_NUMBER", "1102").strip(),
        voip_hold_seconds=_read_int("VOIP_HOLD_SECONDS", 5),
        voip_call_timeout_seconds=_read_int("VOIP_CALL_TIMEOUT_SECONDS", 30),
        voip_probe_interval_seconds=_read_int("VOIP_PROBE_INTERVAL_SECONDS", 3600),
        voip_latency_alert_ms=_read_int("VOIP_LATENCY_ALERT_MS", 1500),
        voip_results_db_path=os.getenv(
            "VOIP_RESULTS_DB_PATH", "data/voip_probe.db"
        ).strip(),
        voip_alert_chat_id=_read_optional_int("VOIP_ALERT_CHAT_ID"),
        rate_limit_voip_seconds=_read_int("RATE_LIMIT_VOIP_SECONDS", 120),
        rate_limit_ping_seconds=_read_int("RATE_LIMIT_PING_SECONDS", 20),
        issabel_ami_host=_read_optional_str("ISSABEL_AMI_HOST"),
        issabel_ami_port=_read_int_or_default("ISSABEL_AMI_PORT", 5038),
        issabel_ami_username=_read_optional_str("ISSABEL_AMI_USERNAME"),
        issabel_ami_secret=_read_optional_str("ISSABEL_AMI_SECRET"),
        issabel_ami_timeout_seconds=_read_int_or_default("ISSABEL_AMI_TIMEOUT_SECONDS", 8),
        issabel_ami_use_tls=_read_bool("ISSABEL_AMI_USE_TLS", False),
        issabel_ami_peer_name_regex=(
            (os.getenv("ISSABEL_AMI_PEER_NAME_REGEX", r"^\\d+$").strip() or r"^\\d+$")
            .replace("\\\\", "\\")
        ),
    )
