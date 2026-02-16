from __future__ import annotations

from argparse import ArgumentParser
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
            logs = storage.list_results(limit=args.limit)
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


if __name__ == "__main__":
    raise SystemExit(main())
