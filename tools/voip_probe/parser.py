from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ParsedProbeMetrics:
    sip_final_code: int | None
    setup_latency_ms: int | None
    error: str | None
    category: str | None
    reason: str | None
    sip_status_text: str | None


def collect_trace_text(trace_dir: Path) -> str:
    patterns = ("*_messages.log", "*_shortmessages.log", "*_errors.log", "*.log")
    parts: list[str] = []
    for pattern in patterns:
        for path in sorted(trace_dir.glob(pattern)):
            try:
                parts.append(path.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
    return "\n".join(parts)


def parse_probe_metrics(
    *,
    trace_text: str,
    stdout_text: str,
    stderr_text: str,
    total_duration_ms: int,
    hold_seconds: int,
    return_code: int,
    timed_out: bool,
    stage: str = "invite",
    destination: str | None = None,
) -> ParsedProbeMetrics:
    combined = "\n".join([trace_text, stdout_text, stderr_text])
    sip_matches = list(
        re.finditer(r"SIP/2.0\s+(\d{3})(?:\s+([^\r\n]+))?", combined, flags=re.IGNORECASE)
    )
    sip_final_code = _pick_effective_sip_code(
        stage=stage, trace_text=trace_text, sip_matches=sip_matches
    )
    sip_status_text = (
        _format_status_text(sip_final_code, _find_phrase_for_code(sip_final_code, sip_matches))
        if sip_final_code is not None
        else None
    )

    setup_latency_ms = _extract_setup_latency_ms(trace_text)
    if setup_latency_ms is None:
        fallback = total_duration_ms - (max(0, hold_seconds) * 1000)
        setup_latency_ms = max(0, fallback) if fallback > 0 else None

    error = None
    if timed_out:
        error = "timeout"
    elif return_code != 0:
        relevant = _extract_relevant_error_line("\n".join([stderr_text or "", stdout_text or ""]))
        if relevant:
            error = relevant
        elif sip_final_code is not None:
            error = f"sip_final_code={sip_final_code}"
        else:
            error = f"sipp_rc={return_code}"
    category = _classify_error_category(
        stage=stage,
        sip_final_code=sip_final_code,
        error_text=error,
        timed_out=timed_out,
    )
    reason = _build_human_reason(
        category=category,
        destination=destination,
        sip_final_code=sip_final_code,
        sip_status_text=sip_status_text,
        error_text=error,
    )
    return ParsedProbeMetrics(
        sip_final_code=sip_final_code,
        setup_latency_ms=setup_latency_ms,
        error=error,
        category=category,
        reason=reason,
        sip_status_text=sip_status_text,
    )


def _extract_setup_latency_ms(trace_text: str) -> int | None:
    invite_ts: int | None = None
    for raw_line in trace_text.splitlines():
        line = raw_line.strip()
        timestamp_ms = _extract_timestamp_ms(line)
        if timestamp_ms is None:
            continue
        if invite_ts is None and "INVITE sip:" in line:
            invite_ts = timestamp_ms
            continue
        if invite_ts is not None and any(
            token in line for token in ("SIP/2.0 180", "SIP/2.0 183", "SIP/2.0 200")
        ):
            if timestamp_ms >= invite_ts:
                return timestamp_ms - invite_ts
    return None


def _pick_effective_sip_code(
    *,
    stage: str,
    trace_text: str,
    sip_matches: list[re.Match],
) -> int | None:
    if not sip_matches:
        return None
    codes = [int(match.group(1)) for match in sip_matches]
    last_code = codes[-1]
    if stage == "invite":
        has_487 = 487 in codes
        has_183 = 183 in codes
        has_180 = 180 in codes
        # Cancel flow often ends with 487 and can include 200 from CANCEL. Prefer progress.
        if has_487 and (has_183 or has_180):
            return 183 if has_183 else 180
        if 200 in codes:
            return 200
        if has_183:
            return 183
        if has_180:
            return 180
        return last_code
    return last_code


def _find_phrase_for_code(code: int | None, sip_matches: list[re.Match]) -> str | None:
    if code is None:
        return None
    for match in reversed(sip_matches):
        try:
            if int(match.group(1)) == code:
                return match.group(2)
        except (TypeError, ValueError):
            continue
    return None


def _extract_timestamp_ms(line: str) -> int | None:
    # Epoch-like prefix, e.g. "1707926400.123 ..."
    epoch_match = re.search(r"^\s*(\d{10}\.\d+)\s", line)
    if epoch_match:
        return int(float(epoch_match.group(1)) * 1000)

    # Clock-like timestamp, e.g. "12:34:56.789"
    clock_match = re.search(r"(\d{2}):(\d{2}):(\d{2})(?:[.,](\d{1,6}))?", line)
    if not clock_match:
        return None
    hour = int(clock_match.group(1))
    minute = int(clock_match.group(2))
    second = int(clock_match.group(3))
    fraction_raw = clock_match.group(4) or "0"
    fraction_ms = int((fraction_raw + "000")[:3])
    return ((hour * 3600 + minute * 60 + second) * 1000) + fraction_ms


def _extract_relevant_error_line(stderr_text: str) -> str | None:
    lines = [line.strip() for line in (stderr_text or "").splitlines() if line.strip()]
    if not lines:
        return None

    keywords = (
        "authentication",
        "error",
        "failed",
        "invalid",
        "unable",
        "cannot",
        "timeout",
        "unreachable",
        "refused",
        "forbidden",
        "aborting",
        "unexpected",
    )
    for line in reversed(lines):
        if _is_noise_line(line):
            continue
        if _is_low_signal_error_line(line):
            continue
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            return _sanitize_error_line(line)

    for line in reversed(lines):
        if _is_noise_line(line):
            continue
        if _is_low_signal_error_line(line):
            continue
        lowered = line.lower()
        if "resolving remote host" in lowered or lowered == "done.":
            continue
        return _sanitize_error_line(line)

    for line in reversed(lines):
        if _is_noise_line(line):
            continue
        if _is_low_signal_error_line(line):
            continue
        return _sanitize_error_line(line)
    for line in reversed(lines):
        if _is_noise_line(line):
            continue
        return _sanitize_error_line(line)
    return None


def _sanitize_error_line(line: str) -> str:
    compact = " ".join(line.split())
    # Remove timestamp prefix from sipp logs if present.
    cleaned = re.sub(
        r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+\d+(?:\.\d+)?:\s*",
        "",
        compact,
    )
    abort_match = re.search(
        r"Aborting call on unexpected message.*?expecting '([^']+)'.*?received '([^']+)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if abort_match:
        expecting = abort_match.group(1).strip()
        received = abort_match.group(2).strip()
        return (
            f"Unexpected SIP response: received {received} while expecting {expecting}"
        )[:300]
    return cleaned[:300]


def _is_noise_line(line: str) -> bool:
    compact = " ".join(line.split())
    if compact in {"'", '"', "'"}:
        return True
    lowered = compact.lower()
    prefixes = (
        "via:",
        "from:",
        "to:",
        "call-id:",
        "cseq:",
        "server:",
        "allow:",
        "supported:",
        "content-length:",
    )
    return lowered.startswith(prefixes)


def _is_low_signal_error_line(line: str) -> bool:
    compact = " ".join(line.split()).lower()
    patterns = (
        "failed call | 0 | 0",
        "failed call|0|0",
        "failed outbound call | 0 | 0",
    )
    return any(pattern in compact for pattern in patterns)


def _classify_error_category(
    *,
    stage: str,
    sip_final_code: int | None,
    error_text: str | None,
    timed_out: bool,
) -> str | None:
    if timed_out:
        return "rede_timeout"

    lowered = (error_text or "").lower()
    network_keywords = (
        "timeout",
        "unreachable",
        "refused",
        "cannot resolve",
        "resolving remote host",
        "network is unreachable",
        "failed to get local ip",
    )
    if any(keyword in lowered for keyword in network_keywords):
        return "rede_timeout"

    if sip_final_code in {401, 407}:
        return "auth"

    if sip_final_code == 403:
        if stage in {"register", "register_auth", "options_auth"}:
            return "auth"
        if "authentication" in lowered or "unauthorized" in lowered:
            return "auth"
        return "rota_permissao"

    if sip_final_code in {404, 488}:
        return "rota_permissao"

    auth_keywords = ("authentication", "unauthorized", "forbidden by auth", "wrong password")
    if any(keyword in lowered for keyword in auth_keywords):
        return "auth"

    if error_text:
        return "desconhecida"
    return None


def _build_human_reason(
    *,
    category: str | None,
    destination: str | None,
    sip_final_code: int | None,
    sip_status_text: str | None,
    error_text: str | None,
) -> str | None:
    if category is None:
        return None
    dest = destination or "destino"
    status = sip_status_text or (
        f"SIP {sip_final_code}" if sip_final_code is not None else "sem codigo SIP"
    )
    if category == "auth":
        return f"falha de autenticacao SIP ({status})"
    if category == "rota_permissao":
        if sip_final_code == 403:
            return f"permissao de discagem para {dest} ({status})"
        if sip_final_code == 404:
            return f"rota nao encontrada para {dest} ({status})"
        if sip_final_code == 488:
            return f"incompatibilidade de midia/codec para {dest} ({status})"
        return f"falha de rota/permissao para {dest} ({status})"
    if category == "rede_timeout":
        if error_text and "timeout" in error_text.lower():
            return f"timeout de rede ao contatar {dest}"
        return f"falha de rede ao contatar {dest} ({status})"
    return error_text or f"falha desconhecida para {dest} ({status})"


def _format_status_text(code: int | None, phrase: str | None) -> str | None:
    if code is None:
        return None
    normalized_phrase = " ".join((phrase or "").strip().split())
    lowered = normalized_phrase.lower()
    marker = " while expecting "
    if marker in lowered:
        idx = lowered.index(marker)
        normalized_phrase = normalized_phrase[:idx].strip()
    normalized_phrase = normalized_phrase.strip("'\" ")
    if normalized_phrase:
        return f"{code} {normalized_phrase}"
    return str(code)
