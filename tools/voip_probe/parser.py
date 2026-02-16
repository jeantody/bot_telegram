from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


@dataclass(frozen=True)
class ParsedProbeMetrics:
    sip_final_code: int | None
    setup_latency_ms: int | None
    error: str | None


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
) -> ParsedProbeMetrics:
    combined = "\n".join([trace_text, stdout_text, stderr_text])
    sip_codes = [int(match.group(1)) for match in re.finditer(r"SIP/2.0\s+(\d{3})", combined)]
    sip_final_code = sip_codes[-1] if sip_codes else None

    setup_latency_ms = _extract_setup_latency_ms(trace_text)
    if setup_latency_ms is None:
        fallback = total_duration_ms - (max(0, hold_seconds) * 1000)
        setup_latency_ms = max(0, fallback) if fallback > 0 else None

    error = None
    if timed_out:
        error = "timeout"
    elif return_code != 0:
        relevant = _extract_relevant_error_line(stderr_text)
        if relevant:
            error = relevant
        elif sip_final_code is not None:
            error = f"sip_final_code={sip_final_code}"
        else:
            error = f"sipp_rc={return_code}"
    return ParsedProbeMetrics(
        sip_final_code=sip_final_code,
        setup_latency_ms=setup_latency_ms,
        error=error,
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
        if invite_ts is not None and "SIP/2.0 200" in line:
            if timestamp_ms >= invite_ts:
                return timestamp_ms - invite_ts
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
    )
    for line in reversed(lines):
        lowered = line.lower()
        if any(keyword in lowered for keyword in keywords):
            return _sanitize_error_line(line)

    for line in reversed(lines):
        lowered = line.lower()
        if "resolving remote host" in lowered or lowered == "done.":
            continue
        return _sanitize_error_line(line)

    return _sanitize_error_line(lines[-1])


def _sanitize_error_line(line: str) -> str:
    compact = " ".join(line.split())
    # Remove timestamp prefix from sipp logs if present.
    cleaned = re.sub(
        r"^\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}(?:\.\d+)?\s+\d+(?:\.\d+)?:\s*",
        "",
        compact,
    )
    return cleaned[:300]
