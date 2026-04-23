from __future__ import annotations

import os

import pytest

from src.automations_lib.providers.link_summary_provider import LinkSummaryProvider
from src.config import load_settings


@pytest.mark.asyncio
async def test_live_link_summary_ollama_and_discord_contract() -> None:
    if os.getenv("RUN_LINK_SUMMARY_LIVE_TESTS") != "1":
        pytest.skip(
            "set RUN_LINK_SUMMARY_LIVE_TESTS=1 to run the mandatory live link-summary gate"
        )

    settings = load_settings()
    provider = LinkSummaryProvider(
        ollama_base_url=settings.link_summary_ollama_base_url,
        ollama_model=settings.link_summary_ollama_model,
        discord_webhook_url=settings.link_summary_discord_webhook_url,
        timeout_seconds=settings.link_summary_timeout_seconds,
        max_text_chars=settings.link_summary_max_text_chars,
    )

    result = await provider.summarize_and_save(
        "https://example.com",
        source_label="TDD live test",
    )

    assert result.summary.strip()
    assert result.discord_status_code in {200, 204}
