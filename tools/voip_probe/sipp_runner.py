from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile

from tools.voip_probe.config import VoipProbeSettings
from tools.voip_probe.parser import collect_trace_text, parse_probe_metrics


@dataclass(frozen=True)
class VoipProbeRunResult:
    ok: bool
    completed_call: bool
    no_issues: bool
    target_number: str
    hold_seconds: int
    setup_latency_ms: int | None
    total_duration_ms: int
    sip_final_code: int | None
    error: str | None
    started_at_utc: str
    finished_at_utc: str

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "completed_call": self.completed_call,
            "no_issues": self.no_issues,
            "target_number": self.target_number,
            "hold_seconds": self.hold_seconds,
            "setup_latency_ms": self.setup_latency_ms,
            "total_duration_ms": self.total_duration_ms,
            "sip_final_code": self.sip_final_code,
            "error": self.error,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
        }


def build_sipp_command(
    settings: VoipProbeSettings,
    *,
    scenario_path: Path,
    trace_dir: Path,
) -> list[str]:
    transport_map = {"udp": "u1", "tcp": "t1", "tls": "l1"}
    transport_flag = transport_map.get(settings.sip_transport.lower(), "u1")
    command = [
        settings.sipp_bin,
        f"{settings.sip_server}:{settings.sip_port}",
        "-sf",
        str(scenario_path),
        "-m",
        "1",
        "-s",
        settings.target_number,
        "-t",
        transport_flag,
        "-recv_timeout",
        str(settings.call_timeout_seconds * 1000),
        "-timeout",
        str(settings.call_timeout_seconds * 1000),
        "-trace_msg",
        "-trace_err",
        "-trace_shortmsg",
        "-trace_logs",
    ]
    if settings.sip_login:
        command.extend(["-au", settings.sip_login])
    if settings.sip_password:
        command.extend(["-ap", settings.sip_password])
    if settings.sip_username:
        command.extend(["-inf", str(_build_users_csv(trace_dir, settings.sip_username))])
    return command


def run_voip_probe(settings: VoipProbeSettings) -> VoipProbeRunResult:
    started_at = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix="voip_probe_") as tmpdir:
        trace_dir = Path(tmpdir)
        rendered_scenario = trace_dir / "call_out_5s.xml"
        _render_scenario(settings, rendered_scenario)
        command = build_sipp_command(
            settings,
            scenario_path=rendered_scenario,
            trace_dir=trace_dir,
        )
        return_code = 1
        timed_out = False
        stdout_text = ""
        stderr_text = ""
        try:
            process = subprocess.run(
                command,
                cwd=trace_dir,
                text=True,
                capture_output=True,
                timeout=settings.call_timeout_seconds,
                check=False,
            )
            return_code = int(process.returncode)
            stdout_text = process.stdout or ""
            stderr_text = process.stderr or ""
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            return_code = 124
            stdout_text = _safe_text(exc.stdout)
            stderr_text = _safe_text(exc.stderr)
        except FileNotFoundError:
            return_code = 127
            stderr_text = f"sipp binary not found: {settings.sipp_bin}"
        except Exception as exc:  # pragma: no cover - defensive
            return_code = 1
            stderr_text = str(exc)

        finished_at = datetime.now(timezone.utc)
        total_duration_ms = max(
            0,
            int((finished_at - started_at).total_seconds() * 1000),
        )
        trace_text = collect_trace_text(trace_dir)
        parsed = parse_probe_metrics(
            trace_text=trace_text,
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            total_duration_ms=total_duration_ms,
            hold_seconds=settings.hold_seconds,
            return_code=return_code,
            timed_out=timed_out,
        )

    completed_call = return_code == 0 and parsed.sip_final_code == 200
    no_issues = completed_call and parsed.error is None
    ok = no_issues
    return VoipProbeRunResult(
        ok=ok,
        completed_call=completed_call,
        no_issues=no_issues,
        target_number=settings.target_number,
        hold_seconds=settings.hold_seconds,
        setup_latency_ms=parsed.setup_latency_ms,
        total_duration_ms=total_duration_ms,
        sip_final_code=parsed.sip_final_code,
        error=parsed.error,
        started_at_utc=started_at.isoformat(),
        finished_at_utc=finished_at.isoformat(),
    )


def _render_scenario(settings: VoipProbeSettings, destination: Path) -> None:
    template_path = Path(__file__).resolve().parent / "scenarios" / "call_out_5s.xml"
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    replacements = {
        "{{TARGET_NUMBER}}": settings.target_number,
        "{{SIP_DOMAIN}}": settings.sip_domain,
        "{{CALLER_ID}}": settings.caller_id,
        "{{SIP_LOGIN}}": settings.sip_login,
        "{{SIP_PASSWORD}}": settings.sip_password,
        "{{HOLD_MS}}": str(max(1, settings.hold_seconds) * 1000),
    }
    for key, value in replacements.items():
        rendered = rendered.replace(key, value)
    destination.write_text(rendered, encoding="utf-8")


def _build_users_csv(trace_dir: Path, username: str) -> Path:
    csv_path = trace_dir / "users.csv"
    csv_path.write_text(
        f"SEQUENTIAL\n{username}\n",
        encoding="utf-8",
    )
    return csv_path


def _safe_text(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode(errors="replace")
    return value
