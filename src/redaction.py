from __future__ import annotations

import re
from typing import Any


_SENSITIVE_KEY_RE = re.compile(
    r"(password|pass|token|secret|api[_-]?key|authorization|cookie|senha)",
    re.IGNORECASE,
)

# Example: https://api.telegram.org/bot123:ABCDEF/getMe
_TELEGRAM_BOT_TOKEN_URL_RE = re.compile(
    r"(api\.telegram\.org/bot)(\d+:[A-Za-z0-9_-]+)",
    re.IGNORECASE,
)

_GENERIC_KV_RE = re.compile(
    r"(?i)\b(token|password|secret|api_key)\s*=\s*([^\s&]+)"
)
_GENERIC_COLON_RE = re.compile(
    r"(?i)\b(token|password|secret|api_key)\s*:\s*([^\s]+)"
)


def redact_text(text: str) -> str:
    if not text:
        return text
    value = _TELEGRAM_BOT_TOKEN_URL_RE.sub(r"\1<redacted>", text)
    value = _GENERIC_KV_RE.sub(r"\1=<redacted>", value)
    value = _GENERIC_COLON_RE.sub(r"\1: <redacted>", value)
    return value


def redact_payload(obj: Any) -> Any:
    if obj is None:
        return None
    if isinstance(obj, str):
        return redact_text(obj)
    if isinstance(obj, (int, float, bool)):
        return obj
    if isinstance(obj, dict):
        out: dict[Any, Any] = {}
        for key, value in obj.items():
            key_str = str(key)
            if _SENSITIVE_KEY_RE.search(key_str):
                out[key] = "<redacted>"
                continue
            out[key] = redact_payload(value)
        return out
    if isinstance(obj, (list, tuple)):
        return [redact_payload(item) for item in obj]
    return obj

