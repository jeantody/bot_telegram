from __future__ import annotations

import asyncio
from dataclasses import dataclass
import platform
import re


@dataclass(frozen=True)
class PingResult:
    ok: bool
    command: str
    packet_loss_pct: int | None
    min_ms: int | None
    avg_ms: int | None
    max_ms: int | None
    output_excerpt: str
    error: str | None


@dataclass(frozen=True)
class TracerouteResult:
    ok: bool
    command: str
    hops: list[str]
    output_excerpt: str
    error: str | None


@dataclass(frozen=True)
class NetworkDiagnostics:
    host: str
    ping: PingResult
    traceroute: TracerouteResult


class NetworkDiagnosticsProvider:
    HOST_REGEX = re.compile(r"^[a-zA-Z0-9.\-]+$")

    def __init__(
        self,
        ping_count: int,
        ping_timeout_seconds: int,
        traceroute_max_hops: int,
        traceroute_timeout_seconds: int,
    ) -> None:
        self._ping_count = max(1, ping_count)
        self._ping_timeout_seconds = max(1, ping_timeout_seconds)
        self._traceroute_max_hops = max(1, traceroute_max_hops)
        self._traceroute_timeout_seconds = max(1, traceroute_timeout_seconds)

    async def run(self, raw_host: str) -> NetworkDiagnostics:
        host = self._normalize_host(raw_host)
        ping_result, trace_result = await asyncio.gather(
            self._run_ping(host),
            self._run_traceroute(host),
        )
        return NetworkDiagnostics(host=host, ping=ping_result, traceroute=trace_result)

    def _normalize_host(self, raw_host: str) -> str:
        host = (raw_host or "").strip()
        host = host.split("/", maxsplit=1)[0]
        if ":" in host and host.count(":") == 1:
            host = host.split(":", maxsplit=1)[0]
        if not host or not self.HOST_REGEX.match(host):
            raise ValueError("Host invalido.")
        return host

    async def _run_ping(self, host: str) -> PingResult:
        if platform.system().lower().startswith("win"):
            args = [
                "ping",
                "-n",
                str(self._ping_count),
                "-w",
                str(self._ping_timeout_seconds * 1000),
                host,
            ]
        else:
            args = [
                "ping",
                "-c",
                str(self._ping_count),
                "-W",
                str(self._ping_timeout_seconds),
                host,
            ]
        command = " ".join(args)
        ok, output, error = await self._run_subprocess(
            args=args,
            timeout_seconds=self._ping_timeout_seconds + 2,
        )
        packet_loss = self._parse_packet_loss(output)
        min_ms, avg_ms, max_ms = self._parse_latencies(output)
        return PingResult(
            ok=ok,
            command=command,
            packet_loss_pct=packet_loss,
            min_ms=min_ms,
            avg_ms=avg_ms,
            max_ms=max_ms,
            output_excerpt=_truncate_output(output),
            error=error,
        )

    async def _run_traceroute(self, host: str) -> TracerouteResult:
        if platform.system().lower().startswith("win"):
            args = [
                "tracert",
                "-d",
                "-h",
                str(self._traceroute_max_hops),
                host,
            ]
        else:
            args = [
                "traceroute",
                "-n",
                "-m",
                str(self._traceroute_max_hops),
                host,
            ]
        command = " ".join(args)
        ok, output, error = await self._run_subprocess(
            args=args,
            timeout_seconds=self._traceroute_timeout_seconds,
        )
        hops = []
        for raw in output.splitlines():
            line = raw.strip()
            if re.match(r"^\d+\s", line):
                hops.append(line)
            if len(hops) >= self._traceroute_max_hops:
                break
        return TracerouteResult(
            ok=ok,
            command=command,
            hops=hops,
            output_excerpt=_truncate_output(output),
            error=error,
        )

    async def _run_subprocess(
        self,
        *,
        args: list[str],
        timeout_seconds: int,
    ) -> tuple[bool, str, str | None]:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_raw, stderr_raw = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
            output = (stdout_raw or b"").decode(errors="replace").strip()
            stderr = (stderr_raw or b"").decode(errors="replace").strip()
            ok = process.returncode == 0
            err = None if ok else (stderr or output or f"rc={process.returncode}")
            return ok, output, err
        except asyncio.TimeoutError:
            return False, "", "timeout"
        except FileNotFoundError:
            return False, "", "comando indisponivel no servidor"
        except Exception as exc:
            return False, "", str(exc)

    @staticmethod
    def _parse_packet_loss(output: str) -> int | None:
        patterns = [
            r"\((\d+)% de\s+perda\)",
            r"(\d+)%\s+packet loss",
            r"Lost = \d+ \((\d+)% loss\)",
        ]
        for pattern in patterns:
            match = re.search(pattern, output, flags=re.IGNORECASE)
            if match:
                return int(match.group(1))
        return None

    @staticmethod
    def _parse_latencies(output: str) -> tuple[int | None, int | None, int | None]:
        # Windows PT/EN patterns.
        match = re.search(
            r"M[íi]nimo\s*=\s*(\d+)ms.*M[áa]ximo\s*=\s*(\d+)ms.*M[ée]dia\s*=\s*(\d+)ms",
            output,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return int(match.group(1)), int(match.group(3)), int(match.group(2))
        match = re.search(
            r"Minimum\s*=\s*(\d+)ms.*Maximum\s*=\s*(\d+)ms.*Average\s*=\s*(\d+)ms",
            output,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if match:
            return int(match.group(1)), int(match.group(3)), int(match.group(2))
        # Linux style: min/avg/max/mdev = 4.543/5.575/6.629/0.761 ms
        match = re.search(
            r"=\s*([\d.]+)/([\d.]+)/([\d.]+)/",
            output,
            flags=re.IGNORECASE,
        )
        if match:
            return int(float(match.group(1))), int(float(match.group(2))), int(float(match.group(3)))
        return None, None, None


def _truncate_output(output: str, max_chars: int = 900) -> str:
    compact = "\n".join(line.rstrip() for line in output.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip()
