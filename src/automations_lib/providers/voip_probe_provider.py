from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import signal
import sys
from typing import Any


@dataclass(frozen=True)
class VoipProbeResult:
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
    mode: str | None = None
    run_id: str | None = None
    category: str | None = None
    reason: str | None = None
    prechecks: dict[str, Any] | None = None
    destinations: list[dict[str, Any]] | None = None
    summary: dict[str, Any] | None = None
    failure_destination_number: str | None = None
    failure_stage: str | None = None


@dataclass(frozen=True)
class VoipProbeLogEntry:
    ok: bool
    target_number: str
    setup_latency_ms: int | None
    sip_final_code: int | None
    error: str | None
    started_at_utc: str
    finished_at_utc: str
    run_id: str | None = None
    category: str | None = None
    reason: str | None = None
    failure_destination_number: str | None = None
    failure_stage: str | None = None


class VoipProbeProvider:
    def __init__(
        self,
        *,
        timeout_seconds: int,
        python_bin: str | None = None,
        script_path: str | None = None,
    ) -> None:
        self._timeout_seconds = max(5, int(timeout_seconds))
        self._python_bin = python_bin or sys.executable
        if script_path:
            self._script_path = Path(script_path)
        else:
            self._script_path = (
                Path(__file__).resolve().parents[3] / "tools" / "voip_probe" / "main.py"
            )

    async def run_once(self) -> VoipProbeResult:
        payload = await self._run_json_command(["run-once", "--json"])
        return self._parse_result(payload)

    async def list_logs(self, *, limit: int = 10) -> list[VoipProbeLogEntry]:
        safe_limit = max(1, min(50, int(limit)))
        payload = await self._run_json_command(["logs", "--limit", str(safe_limit), "--json"])
        raw_items = payload.get("logs")
        if not isinstance(raw_items, list):
            raise RuntimeError("Resposta invalida do voip probe (logs).")
        output: list[VoipProbeLogEntry] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            output.append(
                VoipProbeLogEntry(
                    ok=bool(item.get("ok")),
                    target_number=str(item.get("target_number") or ""),
                    setup_latency_ms=_to_optional_int(item.get("setup_latency_ms")),
                    sip_final_code=_to_optional_int(item.get("sip_final_code")),
                    error=str(item.get("error") or "") or None,
                    started_at_utc=str(item.get("started_at_utc") or ""),
                    finished_at_utc=str(item.get("finished_at_utc") or ""),
                    run_id=str(item.get("run_id") or "") or None,
                    category=str(item.get("category") or "") or None,
                    reason=str(item.get("reason") or "") or None,
                    failure_destination_number=str(
                        item.get("failure_destination_number") or ""
                    )
                    or None,
                    failure_stage=str(item.get("failure_stage") or "") or None,
                )
            )
        return output

    async def _run_json_command(self, args: list[str]) -> dict:
        command = [self._python_bin, str(self._script_path), *args]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(),
                timeout=self._timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            if "process" in locals():
                try:
                    if process.returncode is None:
                        process.kill()
                        await process.communicate()
                except Exception:
                    pass
            raise RuntimeError(
                "timeout ao executar ferramenta VoIP (processo encerrado)"
            ) from exc
        except FileNotFoundError as exc:
            raise RuntimeError("python/script do VoIP probe nao encontrado") from exc

        stdout_text = (stdout_raw or b"").decode(errors="replace").strip()
        stderr_text = (stderr_raw or b"").decode(errors="replace").strip()
        try:
            payload = json.loads(stdout_text) if stdout_text else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"saida JSON invalida do VoIP probe: {stdout_text[:250]}"
            ) from exc
        if process.returncode != 0:
            payload_error = (
                str(payload.get("error") or "").strip()
                if isinstance(payload, dict)
                else ""
            )
            raise RuntimeError(
                _format_nonzero_exit_error(
                    command_name=args[0] if args else "unknown",
                    return_code=int(process.returncode),
                    stderr_text=stderr_text,
                    stdout_text=stdout_text,
                    payload_error=payload_error,
                )
            )
        if not isinstance(payload, dict):
            raise RuntimeError("resposta invalida do VoIP probe.")
        return payload

    @staticmethod
    def _parse_result(payload: dict) -> VoipProbeResult:
        required = {
            "ok",
            "completed_call",
            "no_issues",
            "target_number",
            "hold_seconds",
            "total_duration_ms",
            "started_at_utc",
            "finished_at_utc",
        }
        if not required.issubset(payload.keys()):
            raise RuntimeError("Resposta invalida do voip probe (run-once).")
        return VoipProbeResult(
            ok=bool(payload.get("ok")),
            completed_call=bool(payload.get("completed_call")),
            no_issues=bool(payload.get("no_issues")),
            target_number=str(payload.get("target_number") or ""),
            hold_seconds=int(payload.get("hold_seconds") or 0),
            setup_latency_ms=_to_optional_int(payload.get("setup_latency_ms")),
            total_duration_ms=int(payload.get("total_duration_ms") or 0),
            sip_final_code=_to_optional_int(payload.get("sip_final_code")),
            error=str(payload.get("error") or "") or None,
            started_at_utc=str(payload.get("started_at_utc") or ""),
            finished_at_utc=str(payload.get("finished_at_utc") or ""),
            mode=str(payload.get("mode") or "") or None,
            run_id=str(payload.get("run_id") or "") or None,
            category=str(payload.get("category") or "") or None,
            reason=str(payload.get("reason") or "") or None,
            prechecks=payload.get("prechecks")
            if isinstance(payload.get("prechecks"), dict)
            else None,
            destinations=payload.get("destinations")
            if isinstance(payload.get("destinations"), list)
            else None,
            summary=payload.get("summary")
            if isinstance(payload.get("summary"), dict)
            else None,
            failure_destination_number=str(
                payload.get("failure_destination_number") or ""
            )
            or None,
            failure_stage=str(payload.get("failure_stage") or "") or None,
        )


def _to_optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _format_nonzero_exit_error(
    *,
    command_name: str,
    return_code: int,
    stderr_text: str,
    stdout_text: str,
    payload_error: str,
) -> str:
    detail = _pick_error_detail(
        payload_error=payload_error,
        stderr_text=stderr_text,
        stdout_text=stdout_text,
    )
    if return_code < 0:
        signal_name = _signal_name(return_code)
        base = (
            f"voip probe terminated by {signal_name} (rc={return_code})"
            if signal_name
            else f"voip probe terminated (rc={return_code})"
        )
    else:
        base = f"voip probe failed (rc={return_code})"
    message = f"{base} [{command_name}]"
    if detail:
        message += f": {detail}"
    return message


def _pick_error_detail(
    *,
    payload_error: str,
    stderr_text: str,
    stdout_text: str,
) -> str:
    for candidate in (payload_error, stderr_text, stdout_text):
        value = candidate.strip()
        if value:
            return value[-200:]
    return ""


def _signal_name(return_code: int) -> str | None:
    if return_code >= 0:
        return None
    signum = -return_code
    try:
        return signal.Signals(signum).name
    except Exception:
        return None
