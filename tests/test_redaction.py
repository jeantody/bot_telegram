from __future__ import annotations

from src.redaction import redact_payload, redact_text


def test_redact_text_covers_multiple_secret_formats() -> None:
    raw = (
        "Authorization: Bearer abc123\n"
        "DISCORD_BOT_TOKEN=super-secret\n"
        "https://discord.com/api/webhooks/123/token-secret"
    )

    redacted = redact_text(raw)

    assert "abc123" not in redacted
    assert "super-secret" not in redacted
    assert "token-secret" not in redacted
    assert "Authorization: Bearer <redacted>" in redacted
    assert "DISCORD_BOT_TOKEN=<redacted>" in redacted
    assert "discord.com/api/webhooks/123/<redacted>" in redacted


def test_redact_payload_redacts_nested_secrets_recursively() -> None:
    payload = {
        "token": "abc",
        "headers": {
            "Authorization": "Bearer abc",
            "nested": [
                "DISCORD_BOT_TOKEN=secret",
                {"webhook_url": "https://discord.com/api/webhooks/1/token"},
            ],
        },
    }

    redacted = redact_payload(payload)

    assert redacted["token"] == "<redacted>"
    assert redacted["headers"]["Authorization"] == "<redacted>"
    assert redacted["headers"]["nested"][0] == "DISCORD_BOT_TOKEN=<redacted>"
    assert redacted["headers"]["nested"][1]["webhook_url"] == "<redacted>"
