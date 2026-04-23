from __future__ import annotations

import json

import httpx
import pytest

from src.automations_lib.providers.link_summary_provider import (
    LinkScrapeResult,
    LinkSummaryError,
    LinkSummaryProvider,
    extract_standalone_url,
)


def _make_async_client_factory(handler):
    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient

    def factory(*args, **kwargs):
        return real_async_client(*args, transport=transport, **kwargs)

    return factory


def test_extract_standalone_url_accepts_single_http_url() -> None:
    assert extract_standalone_url(" https://example.com/path?q=1 ") == (
        "https://example.com/path?q=1"
    )
    assert extract_standalone_url("<https://example.com>") == "https://example.com"


def test_extract_standalone_url_rejects_embedded_or_non_http_url() -> None:
    assert extract_standalone_url("veja https://example.com") is None
    assert extract_standalone_url("ftp://example.com/file") is None
    assert extract_standalone_url("https://example.com outra coisa") is None


@pytest.mark.asyncio
async def test_summarize_and_save_scrapes_ollama_and_discord(monkeypatch) -> None:
    seen_prompt: list[str] = []
    seen_discord_payload: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.host == "example.com":
            return httpx.Response(
                200,
                text=(
                    "<html><head><title>Docs ACME</title>"
                    "<meta name='description' content='Documentacao do produto'></head>"
                    "<body><h1>Produto ACME</h1><p>Pagina com guias de integracao.</p>"
                    "<script>ignore()</script></body></html>"
                ),
                request=request,
            )
        if request.method == "POST" and request.url.path == "/api/generate":
            payload = json.loads(request.read().decode("utf-8"))
            assert payload["model"] == "gemma4:e2b"
            assert payload["stream"] is False
            seen_prompt.append(payload["prompt"])
            return httpx.Response(
                200,
                json={"response": "E uma pagina de documentacao do produto ACME."},
                request=request,
            )
        if request.method == "POST" and request.url.host == "discord.com":
            seen_discord_payload.append(json.loads(request.read().decode("utf-8")))
            return httpx.Response(204, request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )

    result = await provider.summarize_and_save(
        "https://example.com/docs",
        source_label="Telegram chat_id=123",
    )

    assert result.title == "Docs ACME"
    assert result.summary == "E uma pagina de documentacao do produto ACME."
    assert result.discord_status_code == 204
    assert "Produto ACME" in seen_prompt[0]
    assert seen_discord_payload[0]["embeds"][0]["title"] == "Docs ACME"
    assert seen_discord_payload[0]["embeds"][0]["fields"][1]["value"] == (
        "Telegram chat_id=123"
    )


@pytest.mark.asyncio
async def test_github_repository_summary_uses_readme_categories(monkeypatch) -> None:
    seen_prompt: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.host == "github.com":
            return httpx.Response(
                200,
                text=(
                    "<html><head><title>GitHub - awesome-selfhosted</title>"
                    "<meta name='description' content='A list of Free Software "
                    "network services and web applications'></head>"
                    "<body><h1>awesome-selfhosted</h1></body></html>"
                ),
                request=request,
            )
        if request.method == "GET" and request.url.host == "api.github.com":
            assert request.url.path == (
                "/repos/awesome-selfhosted/awesome-selfhosted/readme"
            )
            return httpx.Response(
                200,
                text=(
                    "# Awesome-Selfhosted\n\n"
                    "Self-hosting is the practice of hosting and managing "
                    "applications on your own servers.\n\n"
                    "This is a list of Free Software network services and web "
                    "applications which can be hosted on your own servers.\n\n"
                    "## Table of contents\n\n"
                    "- [Software](#software)\n"
                    "  - [Analytics](#analytics)\n"
                    "  - [Backup](#backup)\n"
                    "  - [Communication - Email](#communication-email)\n"
                    "  - [Media Streaming](#media-streaming)\n"
                    "- [External Links](#external-links)\n"
                ),
                request=request,
            )
        if request.method == "POST" and request.url.path == "/api/generate":
            payload = json.loads(request.read().decode("utf-8"))
            seen_prompt.append(payload["prompt"])
            return httpx.Response(
                200,
                json={
                    "response": (
                        "E um catalogo de apps self-hosted. Inclui tipos como "
                        "analytics, backup, email e streaming de midia."
                    )
                },
                request=request,
            )
        if request.method == "POST" and request.url.host == "discord.com":
            return httpx.Response(204, request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )

    result = await provider.summarize_and_save(
        "https://github.com/awesome-selfhosted/awesome-selfhosted"
    )

    assert "Categorias/tipos de software: Analytics; Backup" in seen_prompt[0]
    assert "Communication - Email" in seen_prompt[0]
    assert "Media Streaming" in seen_prompt[0]
    assert "cite os tipos de software" in seen_prompt[0]
    assert "analytics, backup, email" in result.summary


@pytest.mark.asyncio
async def test_summarize_and_save_rejects_invalid_url() -> None:
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )

    with pytest.raises(LinkSummaryError, match="URL invalida"):
        await provider.summarize_and_save("veja https://example.com")


@pytest.mark.asyncio
async def test_scrape_reports_http_status_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(404, text="not found", request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )

    with pytest.raises(LinkSummaryError, match="Scraping falhou: HTTP 404"):
        await provider.scrape("https://example.com/missing")


@pytest.mark.asyncio
async def test_scrape_rejects_empty_page(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text="  \n\t ", request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )

    with pytest.raises(LinkSummaryError, match="Nao foi possivel extrair texto"):
        await provider.scrape("https://example.com/blank")


@pytest.mark.asyncio
async def test_summarize_reports_ollama_error_body(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/generate":
            return httpx.Response(
                500,
                json={
                    "error": (
                        "model requires more system memory (7.2 GiB) "
                        "than is available (4.5 GiB)"
                    )
                },
                request=request,
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )

    scrape = LinkScrapeResult(
        url="https://example.com",
        final_url="https://example.com",
        title="Example",
        description="Example page",
        extracted_text="Example page content",
    )

    with pytest.raises(LinkSummaryError, match="model requires more system memory"):
        await provider.summarize(scrape)


@pytest.mark.asyncio
async def test_summarize_rejects_empty_model_response(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "   "}, request=request)
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )
    scrape = LinkScrapeResult(
        url="https://example.com",
        final_url="https://example.com",
        title="Example",
        description="Example page",
        extracted_text="Example page content",
    )

    with pytest.raises(LinkSummaryError, match="Ollama retornou resposta vazia"):
        await provider.summarize(scrape)


@pytest.mark.asyncio
async def test_send_to_discord_reports_json_error(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.host == "discord.com":
            return httpx.Response(
                429,
                json={"message": "rate limited"},
                request=request,
            )
        raise AssertionError(f"unexpected request: {request.method} {request.url}")

    monkeypatch.setattr(
        "src.automations_lib.providers.link_summary_provider.httpx.AsyncClient",
        _make_async_client_factory(handler),
    )
    provider = LinkSummaryProvider(
        ollama_base_url="http://192.168.0.14:11434",
        ollama_model="gemma4:e2b",
        discord_webhook_url="https://discord.com/api/webhooks/1/token",
        timeout_seconds=10,
        max_text_chars=6000,
    )
    scrape = LinkScrapeResult(
        url="https://example.com",
        final_url="https://example.com/docs",
        title="Docs",
        description="Descricao",
        extracted_text="Texto",
    )

    with pytest.raises(LinkSummaryError, match="Discord falhou: HTTP 429: rate limited"):
        await provider.send_to_discord(
            scrape=scrape,
            summary="Resumo",
            source_label="Telegram chat_id=123",
        )
