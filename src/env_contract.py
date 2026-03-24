from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

OPTIONAL_EMPTY_ENV_KEYS = frozenset(
    {
        "TELEGRAM_ALLOWED_CHAT_ID",
        "HOST_SITE_TARGETS_JSON",
        "NOTE_TAB_CHAT_IDS_JSON",
        "ALERT_PRIORITY_RULES_JSON",
        "VOIP_ALERT_CHAT_ID",
        "ZABBIX_BASE_URL",
        "ZABBIX_API_TOKEN",
        "ZABBIXH_HOST_TARGETS_JSON",
        "ISSABEL_AMI_RAWMAN_URL",
        "ISSABEL_AMI_HOST",
        "ISSABEL_AMI_USERNAME",
        "ISSABEL_AMI_SECRET",
    }
)


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return PROJECT_ROOT / candidate


def parse_env_assignments(path: str | Path) -> dict[str, str]:
    entries: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        normalized_key = key.strip()
        if normalized_key.startswith("export "):
            normalized_key = normalized_key[len("export ") :].strip()
        if not normalized_key:
            continue
        entries[normalized_key] = value.strip()
    return entries


def validate_env_contract(
    *,
    example_path: str | Path = ".env.example",
    env_path: str | Path = ".env",
    optional_empty_keys: set[str] | frozenset[str] = OPTIONAL_EMPTY_ENV_KEYS,
) -> None:
    example_file = resolve_project_path(example_path)
    env_file = resolve_project_path(env_path)

    if not example_file.exists():
        raise ValueError("Missing .env.example in repository.")
    if not env_file.exists():
        raise ValueError("Missing .env file. Copy .env.example to .env before starting the bot.")

    example_entries = parse_env_assignments(example_file)
    env_entries = parse_env_assignments(env_file)

    missing_keys = [key for key in example_entries if key not in env_entries]
    empty_required_keys = [
        key
        for key in example_entries
        if key in env_entries and key not in optional_empty_keys and not env_entries[key]
    ]

    errors: list[str] = []
    if missing_keys:
        errors.append(f"Missing keys in .env: {', '.join(missing_keys)}.")
    if empty_required_keys:
        errors.append(
            "Empty required keys in .env: "
            f"{', '.join(empty_required_keys)}."
        )
    if errors:
        raise ValueError(" ".join(errors))
