from __future__ import annotations

import logging

from src.logging_utils import configure_logging


def test_configure_logging_redacts_telegram_bot_token(capsys) -> None:
    root_logger = logging.getLogger()
    old_handlers = list(root_logger.handlers)
    old_level = root_logger.level
    try:
        configure_logging("INFO")
        logging.getLogger("httpx").info(
            'HTTP Request: POST https://api.telegram.org/bot123:ABCDEF/getMe "HTTP/1.1 200 OK"'
        )
        for handler in logging.getLogger().handlers:
            try:
                handler.flush()
            except Exception:
                pass
        captured = capsys.readouterr().out
        assert "bot123:ABCDEF" not in captured
        assert "api.telegram.org/bot<redacted>" in captured
    finally:
        root_logger.handlers.clear()
        for handler in old_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(old_level)

