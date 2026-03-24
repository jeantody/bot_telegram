from __future__ import annotations

from pathlib import Path
import stat

from src.env_contract import parse_env_assignments, resolve_project_path, validate_env_contract


def test_parse_env_assignments_ignores_comments_and_export(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# comentario\n\nexport TELEGRAM_BOT_TOKEN=token\nVOIP_ALERT_CHAT_ID=\n",
        encoding="utf-8",
    )

    entries = parse_env_assignments(env_path)

    assert entries == {
        "TELEGRAM_BOT_TOKEN": "token",
        "VOIP_ALERT_CHAT_ID": "",
    }


def test_gitignore_keeps_env_ignored() -> None:
    contents = Path(".gitignore").read_text(encoding="utf-8")

    assert ".env\n" in contents
    assert ".env.*\n" in contents
    assert "!.env.example\n" in contents


def test_env_example_is_not_executable() -> None:
    mode = stat.S_IMODE(Path(".env.example").stat().st_mode)

    assert mode & 0o111 == 0


def test_resolve_project_path_uses_repository_root_for_relative_paths() -> None:
    resolved = resolve_project_path(".env.example")

    assert resolved == Path(__file__).resolve().parent.parent / ".env.example"


def test_validate_env_contract_uses_repository_root_when_cwd_changes(monkeypatch, tmp_path: Path) -> None:
    nested = tmp_path / "src"
    nested.mkdir()
    monkeypatch.chdir(nested)

    validate_env_contract()
