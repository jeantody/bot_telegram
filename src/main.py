from __future__ import annotations

from src.config import load_settings
from src.telegram_app import build_application


def main() -> None:
    settings = load_settings()
    application = build_application(settings)
    application.run_polling()


if __name__ == "__main__":
    main()

