from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _runtime_dependency_error(module_name: str | None) -> str:
    dependency = module_name or "required module"
    return (
        f"Missing Python dependency '{dependency}'. "
        "Activate the project virtualenv or install requirements before starting the bot. "
        "Example: `.venv/bin/python -m pip install -r requirements.txt` "
        "then `.venv/bin/python src/main.py`."
    )


def _import_runtime_components():
    try:
        from src.config import load_settings
        from src.logging_utils import configure_logging
        from src.telegram_app import build_application
    except ModuleNotFoundError as exc:
        raise SystemExit(_runtime_dependency_error(exc.name)) from exc
    return load_settings, configure_logging, build_application


def main() -> None:
    load_settings, configure_logging, build_application = _import_runtime_components()
    settings = load_settings()
    configure_logging(settings.log_level)
    application = build_application(settings)
    application.run_polling()


if __name__ == "__main__":
    main()
