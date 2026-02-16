from __future__ import annotations

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config import load_settings
from src.logging_utils import configure_logging
from src.telegram_app import build_application


def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)
    application = build_application(settings)
    application.run_polling()


if __name__ == "__main__":
    main()
