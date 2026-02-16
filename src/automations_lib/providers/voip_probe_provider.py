from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from pathlib import Path
import sys


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


@dataclass(frozen=True)
class VoipProbeLogEntry:
    ok: bool
    target_number: str
    setup_latency_ms: int | None
    sip_final_code: int | None
    error: str | None
    started_at_utc: str
    finished_at_utc: str


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
            raise RuntimeError("timeout ao executar ferramenta VoIP") from exc
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
        if process.returncode != 0 and not isinstance(payload, dict):
            raise RuntimeError(stderr_text or f"voip probe rc={process.returncode}")
        if process.returncode != 0 and isinstance(payload, dict):
            error = str(payload.get("error") or stderr_text or f"voip probe rc={process.returncode}")
            raise RuntimeError(error)
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
        )


def _to_optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

