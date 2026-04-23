from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re
from urllib.parse import quote, urlsplit

from bs4 import BeautifulSoup
import httpx


URL_RE = re.compile(r"^https?://[^\s<>]+$", re.IGNORECASE)


class LinkSummaryError(RuntimeError):
    pass


@dataclass(frozen=True)
class LinkScrapeResult:
    url: str
    final_url: str
    title: str | None
    description: str | None
    extracted_text: str


@dataclass(frozen=True)
class LinkSummaryResult:
    url: str
    final_url: str
    title: str | None
    summary: str
    discord_status_code: int


def extract_standalone_url(text: str) -> str | None:
    candidate = (text or "").strip()
    if candidate.startswith("<") and candidate.endswith(">"):
        candidate = candidate[1:-1].strip()
    if not candidate or any(char.isspace() for char in candidate):
        return None
    if not URL_RE.fullmatch(candidate):
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return candidate


class LinkSummaryProvider:
    BROWSER_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.7",
    }

    def __init__(
        self,
        *,
        ollama_base_url: str,
        ollama_model: str,
        discord_webhook_url: str,
        timeout_seconds: int,
        max_text_chars: int,
    ) -> None:
        self._ollama_base_url = ollama_base_url.rstrip("/")
        self._ollama_model = ollama_model.strip()
        self._discord_webhook_url = discord_webhook_url.strip()
        self._timeout_seconds = timeout_seconds
        self._max_text_chars = max(500, max_text_chars)

    async def summarize_and_save(
        self,
        url: str,
        *,
        source_label: str | None = None,
    ) -> LinkSummaryResult:
        if not self._ollama_base_url:
            raise LinkSummaryError("Ollama nao configurado.")
        if not self._ollama_model:
            raise LinkSummaryError("Modelo Ollama nao configurado.")
        if not self._discord_webhook_url:
            raise LinkSummaryError("Webhook do Discord nao configurado.")

        scrape = await self.scrape(url)
        summary = await self.summarize(scrape)
        status_code = await self.send_to_discord(
            scrape=scrape,
            summary=summary,
            source_label=source_label,
        )
        return LinkSummaryResult(
            url=scrape.url,
            final_url=scrape.final_url,
            title=scrape.title,
            summary=summary,
            discord_status_code=status_code,
        )

    async def scrape(self, url: str) -> LinkScrapeResult:
        normalized = extract_standalone_url(url)
        if normalized is None:
            raise LinkSummaryError("URL invalida. Envie apenas um link http/https.")

        async with httpx.AsyncClient(
            timeout=self._timeout_seconds,
            follow_redirects=True,
            headers=self.BROWSER_HEADERS,
        ) as client:
            try:
                response = await client.get(normalized)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise LinkSummaryError(
                    f"Scraping falhou: HTTP {exc.response.status_code}."
                ) from exc
            except httpx.HTTPError as exc:
                raise LinkSummaryError(f"Scraping falhou: {exc}") from exc
            github_readme_context = await self._fetch_github_readme_context(
                client, str(response.url)
            )

        title, description, extracted_text = self._extract_page_text(response.text)
        if github_readme_context:
            extracted_text = _join_limited_text(
                [extracted_text, github_readme_context],
                self._max_text_chars,
            )
        if not extracted_text:
            extracted_text = response.text[: self._max_text_chars].strip()
        if not extracted_text:
            raise LinkSummaryError("Nao foi possivel extrair texto da pagina.")

        return LinkScrapeResult(
            url=normalized,
            final_url=str(response.url),
            title=title,
            description=description,
            extracted_text=extracted_text[: self._max_text_chars],
        )

    async def summarize(self, scrape: LinkScrapeResult) -> str:
        prompt = self._build_prompt(scrape)
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(
                    f"{self._ollama_base_url}/api/generate",
                    json={
                        "model": self._ollama_model,
                        "prompt": prompt,
                        "stream": False,
                    },
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _response_error_detail(exc.response)
                raise LinkSummaryError(f"Ollama falhou: {detail}") from exc
            except httpx.HTTPError as exc:
                raise LinkSummaryError(f"Ollama indisponivel: {exc}") from exc
            payload = response.json()

        summary = str(payload.get("response") or "").strip()
        if not summary:
            raise LinkSummaryError("Ollama retornou resposta vazia.")
        return summary[:1800]

    async def send_to_discord(
        self,
        *,
        scrape: LinkScrapeResult,
        summary: str,
        source_label: str | None,
    ) -> int:
        title = _truncate(scrape.title or "Site util", 256)
        fields = [
            {
                "name": "URL",
                "value": _truncate(scrape.final_url or scrape.url, 1024),
                "inline": False,
            }
        ]
        if source_label:
            fields.append(
                {
                    "name": "Origem",
                    "value": _truncate(source_label, 1024),
                    "inline": False,
                }
            )
        payload = {
            "embeds": [
                {
                    "title": title,
                    "url": scrape.final_url or scrape.url,
                    "description": _truncate(summary, 4096),
                    "fields": fields,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            ]
        }
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(self._discord_webhook_url, json=payload)
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = _response_error_detail(exc.response)
                raise LinkSummaryError(f"Discord falhou: {detail}") from exc
            except httpx.HTTPError as exc:
                raise LinkSummaryError(f"Discord indisponivel: {exc}") from exc
            return response.status_code

    def _extract_page_text(self, html_text: str) -> tuple[str | None, str | None, str]:
        soup = BeautifulSoup(html_text, "html.parser")
        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        title = _clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
        description = ""
        meta = soup.select_one("meta[name='description'], meta[property='og:description']")
        if meta is not None:
            description = _clean_text(str(meta.get("content") or ""))

        parts: list[str] = []
        for value in (title, description):
            if value:
                parts.append(value)

        for selector in ("h1", "h2", "p"):
            for node in soup.select(selector):
                value = _clean_text(node.get_text(" ", strip=True))
                if value and value not in parts:
                    parts.append(value)
                if len("\n".join(parts)) >= self._max_text_chars:
                    break
            if len("\n".join(parts)) >= self._max_text_chars:
                break

        return title or None, description or None, "\n".join(parts)[: self._max_text_chars]

    def _build_prompt(self, scrape: LinkScrapeResult) -> str:
        title = scrape.title or "indisponivel"
        description = scrape.description or "indisponivel"
        return (
            "Voce vai analisar uma pagina web enviada pelo Telegram.\n"
            "Responda em portugues do Brasil, em 3 a 5 frases curtas.\n"
            "Explique objetivamente do que se trata o link e qual a utilidade provavel.\n"
            "Se for um repositorio, catalogo, lista ou diretorio, cite os tipos "
            "de software, categorias ou usos principais presentes no conteudo.\n"
            "Nao invente informacoes que nao estejam no conteudo extraido.\n\n"
            f"URL: {scrape.final_url or scrape.url}\n"
            f"Titulo: {title}\n"
            f"Descricao: {description}\n"
            "Conteudo extraido:\n"
            f"{scrape.extracted_text}"
        )

    async def _fetch_github_readme_context(
        self,
        client: httpx.AsyncClient,
        final_url: str,
    ) -> str:
        repo = _github_repo_from_url(final_url)
        if repo is None:
            return ""

        owner, repo_name = repo
        api_url = (
            "https://api.github.com/repos/"
            f"{quote(owner, safe='')}/{quote(repo_name, safe='')}/readme"
        )
        try:
            response = await client.get(
                api_url,
                headers={
                    "Accept": "application/vnd.github.raw",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
            if response.status_code == 404:
                return ""
            response.raise_for_status()
        except httpx.HTTPError:
            return ""

        return _extract_markdown_context(response.text, self._max_text_chars)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _join_limited_text(parts: list[str], limit: int) -> str:
    joined_parts = [part.strip() for part in parts if part and part.strip()]
    return "\n".join(joined_parts)[:limit]


def _github_repo_from_url(url: str) -> tuple[str, str] | None:
    parsed = urlsplit(url)
    host = parsed.netloc.lower()
    if host not in {"github.com", "www.github.com"}:
        return None

    segments = [segment for segment in parsed.path.split("/") if segment]
    if len(segments) < 2:
        return None

    owner, repo = segments[0], segments[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    valid_segment = re.compile(r"^[A-Za-z0-9_.-]+$")
    if not valid_segment.fullmatch(owner) or not valid_segment.fullmatch(repo):
        return None
    return owner, repo


def _extract_markdown_context(markdown_text: str, limit: int) -> str:
    lines = markdown_text.splitlines()
    title = _extract_markdown_title(lines)
    intro = _extract_markdown_intro(lines)
    categories = _extract_markdown_categories(lines)

    parts: list[str] = []
    if title:
        parts.append(f"README: {title}")
    if intro:
        parts.append(f"Descricao do README: {_truncate(intro, 1400)}")
    if categories:
        parts.append(
            "Categorias/tipos de software: "
            f"{'; '.join(categories)}."
        )
    return _join_limited_text(parts, limit)


def _extract_markdown_title(lines: list[str]) -> str:
    for raw_line in lines:
        line = raw_line.strip()
        if line.startswith("# "):
            return _clean_markdown_inline(line[2:])
    return ""


def _extract_markdown_intro(lines: list[str]) -> str:
    intro_lines: list[str] = []
    saw_title = False
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("# "):
            saw_title = True
            continue
        if not saw_title:
            continue
        if line.startswith("## "):
            break
        if line.startswith("---") or line.startswith("***"):
            continue
        if line.startswith("[![") or line.startswith("!["):
            continue

        clean = _clean_markdown_inline(line)
        if clean:
            intro_lines.append(clean)
        if len(" ".join(intro_lines)) >= 1400:
            break
    return _clean_text(" ".join(intro_lines))


def _extract_markdown_categories(lines: list[str], limit: int = 36) -> list[str]:
    categories: list[str] = []
    in_toc = False
    in_software = False

    for raw_line in lines:
        stripped = raw_line.strip()
        if re.match(
            r"^##\s+(table of contents|contents|sum[aá]rio)\s*$",
            stripped,
            re.I,
        ):
            in_toc = True
            continue
        if in_toc and stripped.startswith("## "):
            break
        if not in_toc:
            continue

        match = re.match(r"^[-*]\s+\[([^\]]+)\]\([^)]+\)", stripped)
        if not match:
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        label = _clean_markdown_inline(match.group(1))
        normalized = label.lower()

        if normalized == "software":
            in_software = True
            continue
        if normalized in {"external links", "contributing", "list of licenses"}:
            if categories:
                break
            continue

        if in_software and indent == 0:
            if categories:
                break
            continue
        if in_software and indent > 0:
            _append_unique(categories, label, limit)
        elif not in_software:
            _append_unique(categories, label, limit)
        if len(categories) >= limit:
            return categories

    if categories:
        return categories
    return _extract_markdown_heading_categories(lines, limit)


def _extract_markdown_heading_categories(lines: list[str], limit: int) -> list[str]:
    categories: list[str] = []
    ignored = {
        "about",
        "contributing",
        "installation",
        "license",
        "readme",
        "resources",
        "table of contents",
        "usage",
    }
    for raw_line in lines:
        stripped = raw_line.strip()
        match = re.match(r"^#{2,3}\s+(.+)$", stripped)
        if not match:
            continue
        label = _clean_markdown_inline(match.group(1))
        if not label or label.lower() in ignored:
            continue
        _append_unique(categories, label, limit)
        if len(categories) >= limit:
            break
    return categories


def _append_unique(values: list[str], value: str, limit: int) -> None:
    clean = _clean_text(value)
    if clean and clean not in values and len(values) < limit:
        values.append(clean)


def _clean_markdown_inline(value: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", value)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("`", "")
    text = re.sub(r"[*_~]+", "", text)
    return _clean_text(text)


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 3)].rstrip() + "..."


def _response_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        message = payload.get("error") or payload.get("message")
        if message:
            return f"HTTP {response.status_code}: {_truncate(str(message), 500)}"
    text = (response.text or "").strip()
    if text:
        return f"HTTP {response.status_code}: {_truncate(text, 500)}"
    return f"HTTP {response.status_code}"
