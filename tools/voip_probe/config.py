from __future__ import annotations

from dataclasses import dataclass
import os

from dotenv import load_dotenv


def _read_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    return int(raw)


def _read_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, str(default)).strip().lower()
    if raw in {"1", "true", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "no", "n", "off"}:
        return False
    return default


@dataclass(frozen=True)
class VoipProbeSettings:
    enabled: bool
    sipp_bin: str
    sip_server: str
    sip_port: int
    sip_transport: str
    sip_domain: str
    sip_username: str
    sip_login: str
    sip_password: str
    caller_id: str
    target_number: str
    external_reference_number: str
    hold_seconds: int
    call_timeout_seconds: int
    results_db_path: str
    retention_days: int = 30
    baseline_window_days: int = 7
    baseline_min_samples: int = 5
    success_drop_alert_pct_points: float = 20.0
    latency_baseline_multiplier: float = 2.0
    latency_alert_ms: int = 1500
    baseline_timezone: str = "America/Sao_Paulo"
    ami_host: str | None = None
    ami_port: int = 5038
    ami_username: str | None = None
    ami_secret: str | None = None
    ami_timeout_seconds: int = 8
    ami_use_tls: bool = False
    ami_peer_name_regex: str = r"^\d+$"

    def validate(self) -> None:
        if not self.sipp_bin:
            raise ValueError("VOIP_SIPP_BIN vazio.")
        if not self.sip_server:
            raise ValueError("VOIP_SIP_SERVER vazio.")
        if not self.sip_domain:
            raise ValueError("VOIP_SIP_DOMAIN vazio.")
        if not self.sip_login:
            raise ValueError("VOIP_SIP_LOGIN vazio.")
        if not self.caller_id:
            raise ValueError("VOIP_CALLER_ID vazio.")
        if not self.target_number:
            raise ValueError("VOIP_TARGET_NUMBER vazio.")
        if not self.external_reference_number:
            raise ValueError("VOIP_EXTERNAL_REFERENCE_NUMBER vazio.")
        if self.sip_port <= 0:
            raise ValueError("VOIP_SIP_PORT invalido.")
        if self.hold_seconds <= 0:
            raise ValueError("VOIP_HOLD_SECONDS invalido.")
        if self.call_timeout_seconds <= 0:
            raise ValueError("VOIP_CALL_TIMEOUT_SECONDS invalido.")
        if self.baseline_window_days <= 0:
            raise ValueError("VOIP_BASELINE_WINDOW_DAYS invalido.")
        if self.baseline_min_samples <= 0:
            raise ValueError("VOIP_BASELINE_MIN_SAMPLES invalido.")
        if self.success_drop_alert_pct_points <= 0:
            raise ValueError("VOIP_SUCCESS_DROP_ALERT_PCT_POINTS invalido.")
        if self.latency_baseline_multiplier <= 0:
            raise ValueError("VOIP_LATENCY_BASELINE_MULTIPLIER invalido.")
        if self.latency_alert_ms <= 0:
            raise ValueError("VOIP_LATENCY_ALERT_MS invalido.")
        if not self.results_db_path:
            raise ValueError("VOIP_RESULTS_DB_PATH vazio.")


def load_settings_from_env(*, validate: bool = True) -> VoipProbeSettings:
    # Ensure local .env wins over stale shell/system environment values.
    load_dotenv(override=True)

    settings = VoipProbeSettings(
        enabled=_read_bool("VOIP_PROBE_ENABLED", True),
        sipp_bin=os.getenv("VOIP_SIPP_BIN", "sipp").strip(),
        sip_server=os.getenv("VOIP_SIP_SERVER", "mvtelecom.ddns.net").strip(),
        sip_port=_read_int("VOIP_SIP_PORT", 5060),
        sip_transport=os.getenv("VOIP_SIP_TRANSPORT", "udp").strip().lower() or "udp",
        sip_domain=os.getenv("VOIP_SIP_DOMAIN", "mvtelecom.ddns.net").strip(),
        sip_username=os.getenv("VOIP_SIP_USERNAME", "1101").strip(),
        sip_login=os.getenv("VOIP_SIP_LOGIN", "1101").strip(),
        sip_password=os.getenv("VOIP_SIP_PASSWORD", "").strip(),
        caller_id=os.getenv("VOIP_CALLER_ID", "1101").strip(),
        target_number=os.getenv("VOIP_TARGET_NUMBER", "1102").strip(),
        external_reference_number=os.getenv(
            "VOIP_EXTERNAL_REFERENCE_NUMBER", ""
        ).strip(),
        hold_seconds=_read_int("VOIP_HOLD_SECONDS", 5),
        call_timeout_seconds=_read_int("VOIP_CALL_TIMEOUT_SECONDS", 30),
        results_db_path=os.getenv("VOIP_RESULTS_DB_PATH", "data/voip_probe.db").strip(),
        retention_days=_read_int("VOIP_RETENTION_DAYS", 30),
        baseline_window_days=_read_int("VOIP_BASELINE_WINDOW_DAYS", 7),
        baseline_min_samples=_read_int("VOIP_BASELINE_MIN_SAMPLES", 5),
        success_drop_alert_pct_points=float(
            os.getenv("VOIP_SUCCESS_DROP_ALERT_PCT_POINTS", "20").strip()
        ),
        latency_baseline_multiplier=float(
            os.getenv("VOIP_LATENCY_BASELINE_MULTIPLIER", "2.0").strip()
        ),
        latency_alert_ms=_read_int("VOIP_LATENCY_ALERT_MS", 1500),
        baseline_timezone=os.getenv("BOT_TIMEZONE", "America/Sao_Paulo").strip()
        or "America/Sao_Paulo",
        ami_host=(os.getenv("ISSABEL_AMI_HOST", "").strip() or None),
        ami_port=_read_int("ISSABEL_AMI_PORT", 5038),
        ami_username=(os.getenv("ISSABEL_AMI_USERNAME", "").strip() or None),
        ami_secret=(os.getenv("ISSABEL_AMI_SECRET", "").strip() or None),
        ami_timeout_seconds=_read_int("ISSABEL_AMI_TIMEOUT_SECONDS", 8),
        ami_use_tls=_read_bool("ISSABEL_AMI_USE_TLS", False),
        ami_peer_name_regex=(
            (os.getenv("ISSABEL_AMI_PEER_NAME_REGEX", r"^\\d+$").strip() or r"^\\d+$")
            .replace("\\\\", "\\")
        ),
    )
    if validate:
        settings.validate()
    return settings
