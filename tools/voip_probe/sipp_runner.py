from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
import uuid

from tools.voip_probe.config import VoipProbeSettings
from tools.voip_probe.parser import collect_trace_text, parse_probe_metrics


@dataclass(frozen=True)
class ProbeStageResult:
    stage: str
    ok: bool
    sip_final_code: int | None
    sip_status_text: str | None
    setup_latency_ms: int | None
    total_duration_ms: int
    error: str | None
    category: str | None
    reason: str | None

    def to_dict(self) -> dict:
        return {
            "stage": self.stage,
            "ok": self.ok,
            "sip_final_code": self.sip_final_code,
            "sip_status_text": self.sip_status_text,
            "setup_latency_ms": self.setup_latency_ms,
            "total_duration_ms": self.total_duration_ms,
            "error": self.error,
            "category": self.category,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class DestinationProbeResult:
    key: str
    number: str
    options: ProbeStageResult
    invite: ProbeStageResult
    completed_call: bool
    no_issues: bool
    setup_latency_ms: int | None
    sip_final_code: int | None
    error: str | None
    category: str | None
    reason: str | None

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "number": self.number,
            "options": self.options.to_dict(),
            "invite": self.invite.to_dict(),
            "completed_call": self.completed_call,
            "no_issues": self.no_issues,
            "setup_latency_ms": self.setup_latency_ms,
            "sip_final_code": self.sip_final_code,
            "error": self.error,
            "category": self.category,
            "reason": self.reason,
        }


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
    mode: str
    run_id: str
    category: str | None
    reason: str | None
    prechecks: dict
    destinations: list[dict]
    summary: dict
    failure_destination_number: str | None
    failure_stage: str | None

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
            "mode": self.mode,
            "run_id": self.run_id,
            "category": self.category,
            "reason": self.reason,
            "prechecks": self.prechecks,
            "destinations": self.destinations,
            "summary": self.summary,
            "failure_destination_number": self.failure_destination_number,
            "failure_stage": self.failure_stage,
        }


def build_sipp_command(
    settings: VoipProbeSettings,
    *,
    scenario_path: Path,
    trace_dir: Path,
    target_number: str,
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
        target_number,
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
    run_id = uuid.uuid4().hex[:12]
    matrix_targets = _build_matrix_targets(settings)

    register_stage = _run_stage(
        settings=settings,
        stage_name="register",
        scenario_template="register_check.xml",
        target_number=settings.sip_login,
        stage_destination=settings.sip_login,
        replacements={},
        hold_seconds=0,
    )

    destinations: list[DestinationProbeResult] = []
    if not register_stage.ok:
        for key, number in matrix_targets:
            destinations.append(
                DestinationProbeResult(
                    key=key,
                    number=number,
                    options=ProbeStageResult(
                        stage="options",
                        ok=False,
                        sip_final_code=register_stage.sip_final_code,
                        sip_status_text=register_stage.sip_status_text,
                        setup_latency_ms=None,
                        total_duration_ms=0,
                        error=register_stage.error,
                        category=register_stage.category,
                        reason=register_stage.reason,
                    ),
                    invite=ProbeStageResult(
                        stage="invite",
                        ok=False,
                        sip_final_code=register_stage.sip_final_code,
                        sip_status_text=register_stage.sip_status_text,
                        setup_latency_ms=None,
                        total_duration_ms=0,
                        error="invite nao executado por falha no REGISTER",
                        category=register_stage.category,
                        reason=register_stage.reason,
                    ),
                    completed_call=False,
                    no_issues=False,
                    setup_latency_ms=None,
                    sip_final_code=register_stage.sip_final_code,
                    error=register_stage.error,
                    category=register_stage.category,
                    reason=register_stage.reason,
                )
            )
    else:
        for key, number in matrix_targets:
            options_stage = _run_stage(
                settings=settings,
                stage_name="options",
                scenario_template="options_check.xml",
                target_number=number,
                stage_destination=number,
                replacements={"{{TARGET_NUMBER}}": number},
                hold_seconds=0,
            )
            invite_stage = _run_stage(
                settings=settings,
                stage_name="invite",
                scenario_template="call_out_5s.xml",
                target_number=number,
                stage_destination=number,
                replacements={"{{TARGET_NUMBER}}": number},
                hold_seconds=settings.hold_seconds,
            )
            completed_call = invite_stage.ok and invite_stage.sip_final_code == 200
            no_issues = invite_stage.ok and invite_stage.error is None
            if invite_stage.ok and invite_stage.error is None:
                category = invite_stage.category
                reason = invite_stage.reason
                error = invite_stage.error
            else:
                category = invite_stage.category or options_stage.category
                reason = invite_stage.reason or options_stage.reason
                error = invite_stage.error or options_stage.error
            destinations.append(
                DestinationProbeResult(
                    key=key,
                    number=number,
                    options=options_stage,
                    invite=invite_stage,
                    completed_call=completed_call,
                    no_issues=no_issues,
                    setup_latency_ms=invite_stage.setup_latency_ms,
                    sip_final_code=invite_stage.sip_final_code,
                    error=error,
                    category=category,
                    reason=reason,
                )
            )

    finished_at = datetime.now(timezone.utc)
    total_duration_ms = max(0, int((finished_at - started_at).total_seconds() * 1000))
    target_result = _pick_target_result(destinations, settings.target_number)
    primary_failure = _pick_primary_failure(destinations)
    if not register_stage.ok:
        failure_destination_number = settings.sip_login
        failure_stage = "register"
    else:
        failure_destination_number = (
            primary_failure.number if primary_failure is not None else None
        )
        failure_stage = (
            _pick_failure_stage(primary_failure) if primary_failure is not None else None
        )
    summary = _build_summary(destinations)
    prechecks = {"register": register_stage.to_dict()}
    return VoipProbeRunResult(
        ok=all(item.no_issues for item in destinations),
        completed_call=target_result.completed_call,
        no_issues=target_result.no_issues,
        target_number=settings.target_number,
        hold_seconds=settings.hold_seconds,
        setup_latency_ms=target_result.setup_latency_ms,
        total_duration_ms=total_duration_ms,
        sip_final_code=target_result.sip_final_code,
        error=primary_failure.reason if primary_failure is not None else None,
        started_at_utc=started_at.isoformat(),
        finished_at_utc=finished_at.isoformat(),
        mode="matrix_v1",
        run_id=run_id,
        category=primary_failure.category if primary_failure is not None else None,
        reason=primary_failure.reason if primary_failure is not None else None,
        prechecks=prechecks,
        destinations=[item.to_dict() for item in destinations],
        summary=summary,
        failure_destination_number=failure_destination_number,
        failure_stage=failure_stage,
    )


def _run_stage(
    *,
    settings: VoipProbeSettings,
    stage_name: str,
    scenario_template: str,
    target_number: str,
    stage_destination: str,
    replacements: dict[str, str],
    hold_seconds: int,
) -> ProbeStageResult:
    started_at = datetime.now(timezone.utc)
    with tempfile.TemporaryDirectory(prefix=f"voip_probe_{stage_name}_") as tmpdir:
        trace_dir = Path(tmpdir)
        rendered_scenario = trace_dir / scenario_template
        _render_scenario(
            settings=settings,
            template_name=scenario_template,
            destination=rendered_scenario,
            replacements=replacements,
        )
        command = build_sipp_command(
            settings,
            scenario_path=rendered_scenario,
            trace_dir=trace_dir,
            target_number=target_number,
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
            hold_seconds=hold_seconds,
            return_code=return_code,
            timed_out=timed_out,
            stage=stage_name,
            destination=stage_destination,
        )
        if stage_name in {"register", "options"}:
            ok = return_code == 0 and parsed.sip_final_code == 200
        elif stage_name == "invite":
            ok = return_code == 0 and (parsed.sip_final_code in {180, 183, 200})
        else:
            ok = return_code == 0 and parsed.sip_final_code == 200

        error_text = parsed.error
        category = parsed.category
        reason = parsed.reason
        # OPTIONS is a best-effort pre-check. Some PBXs reply 200 but SIPp still exits
        # non-zero due to stray retransmissions/unexpected provisional messages.
        if stage_name == "options" and not timed_out and parsed.sip_final_code == 200:
            ok = True
            error_text = None
            category = None
            reason = None
        return ProbeStageResult(
            stage=stage_name,
            ok=ok,
            sip_final_code=parsed.sip_final_code,
            sip_status_text=parsed.sip_status_text,
            setup_latency_ms=parsed.setup_latency_ms if stage_name == "invite" else None,
            total_duration_ms=total_duration_ms,
            error=error_text,
            category=category,
            reason=reason,
        )


def _render_scenario(
    *,
    settings: VoipProbeSettings,
    template_name: str,
    destination: Path,
    replacements: dict[str, str],
) -> None:
    template_path = Path(__file__).resolve().parent / "scenarios" / template_name
    template = template_path.read_text(encoding="utf-8")
    rendered = template
    common_replacements = {
        "{{SIP_DOMAIN}}": settings.sip_domain,
        "{{CALLER_ID}}": settings.caller_id,
        "{{SIP_LOGIN}}": settings.sip_login,
        "{{SIP_PASSWORD}}": settings.sip_password,
        "{{HOLD_MS}}": str(max(1, settings.hold_seconds) * 1000),
    }
    merged_replacements = {**common_replacements, **replacements}
    for key, value in merged_replacements.items():
        rendered = rendered.replace(key, value)
    destination.write_text(rendered, encoding="utf-8")


def _build_matrix_targets(settings: VoipProbeSettings) -> list[tuple[str, str]]:
    return [
        ("self", settings.sip_username),
        ("target", settings.target_number),
        ("external", settings.external_reference_number),
    ]


def _pick_target_result(
    destinations: list[DestinationProbeResult],
    target_number: str,
) -> DestinationProbeResult:
    for item in destinations:
        if item.number == target_number:
            return item
    return destinations[0]


def _pick_primary_failure(
    destinations: list[DestinationProbeResult],
) -> DestinationProbeResult | None:
    if not destinations:
        return None
    for preferred_key in ("target", "external", "self"):
        for item in destinations:
            if item.key == preferred_key and not item.no_issues:
                return item
    for item in destinations:
        if not item.no_issues:
            return item
    return None


def _build_summary(destinations: list[DestinationProbeResult]) -> dict:
    total = len(destinations)
    success = sum(1 for item in destinations if item.no_issues)
    failed = total - success
    categories: dict[str, int] = {}
    for item in destinations:
        if item.no_issues:
            continue
        key = item.category or "desconhecida"
        categories[key] = categories.get(key, 0) + 1
    return {
        "total_destinations": total,
        "successful_destinations": success,
        "failed_destinations": failed,
        "failure_categories": categories,
        "deviation_alert": False,
        "deviation_reasons": [],
        "baseline": [],
    }


def _pick_failure_stage(item: DestinationProbeResult) -> str:
    if not item.invite.ok:
        return "invite"
    if not item.options.ok:
        return "options"
    return "invite"


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
