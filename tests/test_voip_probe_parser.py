from __future__ import annotations

from tools.voip_probe.parser import parse_probe_metrics


def test_parse_probe_metrics_success_with_200_and_latency() -> None:
    trace = "\n".join(
        [
            "12:00:00.100 >>> INVITE sip:1102@mvtelecom.ddns.net SIP/2.0",
            "12:00:00.450 <<< SIP/2.0 100 Trying",
            "12:00:01.900 <<< SIP/2.0 200 OK",
        ]
    )
    parsed = parse_probe_metrics(
        trace_text=trace,
        stdout_text="",
        stderr_text="",
        total_duration_ms=7000,
        hold_seconds=5,
        return_code=0,
        timed_out=False,
    )
    assert parsed.sip_final_code == 200
    assert parsed.setup_latency_ms == 1800
    assert parsed.error is None


def test_parse_probe_metrics_failure_with_error_code() -> None:
    trace = "12:00:00.100 >>> INVITE sip:1102@mvtelecom.ddns.net SIP/2.0\n12:00:00.800 <<< SIP/2.0 486 Busy Here"
    parsed = parse_probe_metrics(
        trace_text=trace,
        stdout_text="",
        stderr_text="busy",
        total_duration_ms=900,
        hold_seconds=5,
        return_code=1,
        timed_out=False,
    )
    assert parsed.sip_final_code == 486
    assert parsed.error == "busy"


def test_parse_probe_metrics_uses_fallback_latency_when_trace_missing() -> None:
    parsed = parse_probe_metrics(
        trace_text="",
        stdout_text="",
        stderr_text="",
        total_duration_ms=7600,
        hold_seconds=5,
        return_code=0,
        timed_out=False,
    )
    assert parsed.setup_latency_ms == 2600


def test_parse_probe_metrics_picks_technical_stderr_line() -> None:
    stderr_text = "\n".join(
        [
            "Resolving remote host 'mvtelecom.ddns.net'... Done.",
            "2026-02-16 17:15:29.275997 1771262129.275997: Authentication keyword without dialog_authentication!",
        ]
    )
    parsed = parse_probe_metrics(
        trace_text="",
        stdout_text="",
        stderr_text=stderr_text,
        total_duration_ms=120,
        hold_seconds=5,
        return_code=255,
        timed_out=False,
    )
    assert parsed.error == "Authentication keyword without dialog_authentication!"


def test_parse_probe_metrics_extracts_unexpected_sip_response() -> None:
    stderr_text = "\n".join(
        [
            "Resolving remote host 'mvtelecom.ddns.net'... Done.",
            "2026-02-16\t17:27:52.228713\t1771262872.228713: Aborting call on unexpected message for Call-Id '1-31553@192.168.3.26': while expecting '100' (index 10), received 'SIP/2.0 482 (Loop Detected)",
            "Via: SIP/2.0/UDP 192.168.3.26:5060;branch=z9hG4bK",
            "'",
        ]
    )
    parsed = parse_probe_metrics(
        trace_text="",
        stdout_text="",
        stderr_text=stderr_text,
        total_duration_ms=140,
        hold_seconds=5,
        return_code=1,
        timed_out=False,
    )
    assert (
        parsed.error
        == "Unexpected SIP response: received SIP/2.0 482 (Loop Detected) while expecting 100"
    )
