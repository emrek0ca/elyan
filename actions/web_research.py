from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from runtime.capability_registry import SafeCapabilityError


@dataclass(frozen=True)
class ResearchSource:
    title: str
    url: str
    summary: str


def _http_client():
    try:
        import httpx  # type: ignore[reportMissingImports]

        return httpx
    except Exception:
        return None


def _trafilatura():
    try:
        import trafilatura  # type: ignore[reportMissingImports]

        return trafilatura
    except Exception:
        return None


def _fetch_text(url: str) -> str:
    httpx = _http_client()
    if httpx is None:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Web research için httpx gerekli.")
    response = httpx.get(url, headers={"User-Agent": "Elyan/1.0"}, timeout=15)
    response.raise_for_status()
    html_text = response.text or ""
    trafilatura = _trafilatura()
    if trafilatura is not None:
        extracted = trafilatura.extract(html_text, include_links=False, include_images=False, favor_precision=True)
        if extracted and str(extracted).strip():
            return str(extracted).strip()
    cleaned = re.sub(r"(?is)<script.*?>.*?</script>", " ", html_text)
    cleaned = re.sub(r"(?is)<style.*?>.*?</style>", " ", cleaned)
    cleaned = re.sub(r"(?is)<[^>]+>", " ", cleaned)
    cleaned = html.unescape(cleaned)
    return " ".join(cleaned.split())


def _playwright_search(query: str, limit: int = 5) -> list[tuple[str, str]]:
    try:
        from playwright.sync_api import sync_playwright  # type: ignore[reportMissingImports]
    except Exception as exc:
        raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "Playwright bulunamadı.") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(
                f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                wait_until="domcontentloaded",
                timeout=15_000,
            )
            links = page.locator("a.result__a")
            results: list[tuple[str, str]] = []
            for index in range(min(limit, links.count())):
                link = links.nth(index)
                title = " ".join((link.inner_text(timeout=5_000) or "").split())
                href = str(link.get_attribute("href") or "").strip()
                if href.startswith("//"):
                    href = f"https:{href}"
                if href:
                    results.append((title or href, href))
            return results
        finally:
            browser.close()


def _duckduckgo_search(query: str, limit: int = 5) -> list[tuple[str, str]]:
    httpx = _http_client()
    if httpx is None:
        return _playwright_search(query, limit)
    try:
        response = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Elyan/1.0"},
            timeout=15,
        )
        response.raise_for_status()
        html_text = response.text or ""
    except Exception:
        return _playwright_search(query, limit)
    results: list[tuple[str, str]] = []
    for match in re.finditer(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        raw_url = html.unescape(match.group(1))
        title = re.sub(r"(?is)<.*?>", " ", match.group(2))
        title = " ".join(html.unescape(title).split())
        parsed = urlparse(raw_url)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.startswith("/l/"):
            target = parse_qs(parsed.query).get("uddg", [""])[0]
            if target:
                raw_url = unquote(target)
        if raw_url.startswith("//"):
            raw_url = f"https:{raw_url}"
        if raw_url and title:
            results.append((title, raw_url))
        if len(results) >= limit:
            break
    return results or _playwright_search(query, limit)


def _summarize(text: str, max_chars: int = 800) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "…"


def web_research(query: str, max_results: int = 4, language_hint: str = "") -> dict[str, Any]:
    topic = str(query or "").strip()
    if not topic:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Araştırma için konu belirtilmedi.")

    try:
        search_results = _duckduckgo_search(topic, max(1, min(int(max_results or 4), 6)))
    except Exception as exc:
        fallback = str(exc)
        raise SafeCapabilityError("WEB_RESEARCH_FAILED", f"Web araştırması başlatılamadı: {fallback}") from exc

    sources: list[ResearchSource] = []
    for title, url in search_results:
        try:
            content = _fetch_text(url)
        except Exception:
            continue
        if not content:
            continue
        sources.append(
            ResearchSource(
                title=title,
                url=url,
                summary=_summarize(content, 700),
            )
        )
        if len(sources) >= max(1, min(int(max_results or 4), 6)):
            break

    if not sources:
        raise SafeCapabilityError("WEB_RESEARCH_FAILED", "Araştırma için güvenilir kaynak alınamadı.")

    summary_lines = [
        f"{index + 1}. {source.title}: {source.summary}"
        for index, source in enumerate(sources[:3])
    ]
    summary = "\n".join(summary_lines)
    return {
        "text": f"Web araştırması tamamlandı: {topic}",
        "result": {
            "kind": "web_research",
            "query": topic,
            "languageHint": language_hint,
            "summary": summary,
            "sources": [source.__dict__ for source in sources],
        },
        "artifacts": [],
    }
