from __future__ import annotations

from argparse import ArgumentParser
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tools.voip_probe.config import load_settings_from_env
from tools.voip_probe.sipp_runner import run_voip_probe
from tools.voip_probe.storage import VoipProbeStorage


def build_parser() -> ArgumentParser:
    parser = ArgumentParser(description="VoIP probe tool.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_once = subparsers.add_parser("run-once", help="Run a single SIP probe.")
    run_once.add_argument("--json", action="store_true", dest="as_json")

    logs = subparsers.add_parser("logs", help="Read probe history.")
    logs.add_argument("--limit", type=int, default=10)
    logs.add_argument("--json", action="store_true", dest="as_json")

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        settings = load_settings_from_env(validate=args.command == "run-once")
        storage = VoipProbeStorage(settings.results_db_path)
    except Exception as exc:
        return _print_error_and_exit(exc, as_json=getattr(args, "as_json", False))

    try:
        if args.command == "run-once":
            result = run_voip_probe(settings)
            payload = result.to_dict()
            _apply_baseline(payload=payload, storage=storage, settings=settings)
            storage.insert_result(payload)
            storage.purge_older_than_days(settings.retention_days)
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                status = "OK" if payload["ok"] else "FALHA"
                print(
                    f"[{status}] target={payload['target_number']} "
                    f"latency={payload['setup_latency_ms']}ms "
                    f"sip={payload['sip_final_code']} "
                    f"error={payload['error'] or '-'}"
                )
            return 0

        if args.command == "logs":
            logs = storage.list_results(limit=args.limit, only_mode="matrix_v1")
            payload = {"logs": logs}
            if args.as_json:
                print(json.dumps(payload, ensure_ascii=False))
            else:
                for item in logs:
                    status = "OK" if item.get("ok") else "FALHA"
                    print(
                        f"{item.get('finished_at_utc')} | {status} | "
                        f"lat={item.get('setup_latency_ms')}ms | "
                        f"sip={item.get('sip_final_code')} | "
                        f"erro={item.get('error') or '-'}"
                    )
            return 0

        return _print_error_and_exit("comando invalido", as_json=getattr(args, "as_json", False))
    except Exception as exc:
        return _print_error_and_exit(exc, as_json=getattr(args, "as_json", False))
    finally:
        storage.close()


def _print_error_and_exit(exc: Exception | str, *, as_json: bool) -> int:
    message = str(exc)
    if as_json:
        payload = {
            "ok": False,
            "completed_call": False,
            "no_issues": False,
            "target_number": "",
            "hold_seconds": 0,
            "setup_latency_ms": None,
            "total_duration_ms": 0,
            "sip_final_code": None,
            "error": message,
            "started_at_utc": "",
            "finished_at_utc": "",
        }
        print(json.dumps(payload, ensure_ascii=False))
    else:
        print(f"ERROR: {message}", file=sys.stderr)
    return 1


def _apply_baseline(*, payload: dict, storage: VoipProbeStorage, settings) -> None:
    destinations = payload.get("destinations")
    if not isinstance(destinations, list):
        return
    finished_at = _parse_iso_datetime(payload.get("finished_at_utc"))
    now_utc = finished_at or datetime.now(timezone.utc)
    hour_local = now_utc.hour
    if settings.baseline_timezone:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            hour_local = now_utc.astimezone(ZoneInfo(settings.baseline_timezone)).hour
        except ZoneInfoNotFoundError:
            hour_local = now_utc.hour

    baseline_entries: list[dict] = []
    deviation_reasons: list[str] = []
    deviation_alert = False
    for item in destinations:
        if not isinstance(item, dict):
            continue
        number = str(item.get("number") or "")
        if not number:
            continue
        baseline = storage.baseline_for_destination(
            destination_number=number,
            now_utc=now_utc,
            timezone_name=settings.baseline_timezone,
            window_days=settings.baseline_window_days,
            hour_local=hour_local,
        )
        current_latency = _to_optional_int(item.get("setup_latency_ms"))
        current_success_pct = 100.0 if bool(item.get("no_issues")) else 0.0
        entry = {
            "key": str(item.get("key") or ""),
            "number": number,
            "samples": baseline["samples"],
            "baseline_success_rate_pct": baseline["success_rate_pct"],
            "baseline_avg_latency_ms": baseline["avg_latency_ms"],
            "current_success_pct": current_success_pct,
            "current_latency_ms": current_latency,
            "alert": False,
            "reasons": [],
        }
        if baseline["samples"] >= settings.baseline_min_samples:
            baseline_success = baseline["success_rate_pct"]
            if baseline_success is not None:
                success_drop = baseline_success - current_success_pct
                entry["success_drop_pct_points"] = round(success_drop, 2)
                if success_drop >= settings.success_drop_alert_pct_points:
                    entry["alert"] = True
                    reason = (
                        f"queda de sucesso em {number}: {success_drop:.1f} p.p. "
                        f"(baseline {baseline_success:.1f}% -> atual {current_success_pct:.1f}%)"
                    )
                    entry["reasons"].append(reason)
                    deviation_reasons.append(reason)
            baseline_latency = baseline["avg_latency_ms"]
            if baseline_latency is not None and current_latency is not None:
                limit = max(
                    settings.latency_alert_ms,
                    baseline_latency * settings.latency_baseline_multiplier,
                )
                entry["latency_limit_ms"] = round(limit, 2)
                if current_latency > limit:
                    entry["alert"] = True
                    reason = (
                        f"latencia acima do baseline em {number}: {current_latency}ms "
                        f"(limite {limit:.0f}ms)"
                    )
                    entry["reasons"].append(reason)
                    deviation_reasons.append(reason)
        baseline_entries.append(entry)
        if entry["alert"]:
            deviation_alert = True

    summary = payload.get("summary")
    if not isinstance(summary, dict):
        summary = {}
    summary["baseline"] = baseline_entries
    summary["deviation_alert"] = deviation_alert
    summary["deviation_reasons"] = deviation_reasons
    payload["summary"] = summary


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _to_optional_int(value) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    raise SystemExit(main())
