"""Smart web fetching with static-first and optional browser rendering."""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from utils.logger import get_logger

logger = get_logger("web.smart_fetch")

MAX_CONTENT_LENGTH = 50000
STATIC_TIMEOUT_S = 8
RENDER_TIMEOUT_S = 20
BLOCKED_DOMAINS = (
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "192.168.",
    "10.",
    "172.16.",
    "169.254.",
    ".local",
    ".internal",
)
OFFICIAL_RENDER_HINTS = (
    "tuik.gov.tr",
    "data.tuik.gov.tr",
    "tcmb.gov.tr",
    "evds2.tcmb.gov.tr",
    "hmb.gov.tr",
    "sbb.gov.tr",
    "ticaret.gov.tr",
    "europa.eu",
    "ec.europa.eu",
    "eurostat.ec.europa.eu",
)
JS_REQUIRED_MARKERS = (
    "enable javascript",
    "enable java script",
    "you need to enable javascript",
    "you need to enable java script",
    "javascript gerekli",
    "java script gerekli",
    "requires javascript",
    "app-root",
    "__next_data__",
    "data-reactroot",
    "id=\"root\"",
    "id='root'",
)


def _is_safe_url(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return False, "Sadece HTTP/HTTPS destekleniyor"
        host = parsed.netloc.lower()
        for blocked in BLOCKED_DOMAINS:
            if blocked in host:
                return False, f"Bu URL'ye erişim engellenmiş: {blocked}"
        return True, ""
    except Exception as exc:
        return False, f"URL geçersiz: {exc}"


def _domain_from_url(url: str) -> str:
    try:
        host = urlparse(str(url or "")).netloc.lower().strip()
        return host[4:] if host.startswith("www.") else host
    except Exception:
        return ""


def _extract_text_density(html: str) -> float:
    if not html:
        return 0.0
    tagless = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    tagless = re.sub(r"(?is)<[^>]+>", " ", tagless)
    visible = re.sub(r"\s+", " ", tagless).strip()
    if not visible:
        return 0.0
    return len(visible) / max(len(html), 1)


def _extract_text(html: str, url: str = "") -> dict[str, Any]:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return {"success": False, "error": "beautifulsoup4 kurulu değil."}

    soup = BeautifulSoup(html, "html.parser")
    title_tag = soup.find("title")
    title = title_tag.get_text(" ", strip=True) if title_tag else ""

    for element in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
        element.decompose()

    main_content = None
    for selector in ("article", "main", ".content", ".post", ".article", "#content", "#main", ".container"):
        if selector.startswith((".", "#")):
            main_content = soup.select_one(selector)
        else:
            main_content = soup.find(selector)
        if main_content:
            break
    if not main_content:
        main_content = soup.find("body") or soup

    text = main_content.get_text(separator="\n", strip=True)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)

    return {"success": True, "title": title, "text": text, "url": url}


def _needs_browser_render(
    *,
    url: str,
    html: str,
    status_code: int,
    content_type: str = "",
    source_policy: str = "balanced",
) -> bool:
    if status_code >= 400:
        return False
    if not html:
        return True
    low_html = html.lower()
    domain = _domain_from_url(url)
    density = _extract_text_density(html)
    text_payload = re.sub(r"(?is)<[^>]+>", " ", html)
    text_payload = re.sub(r"\s+", " ", text_payload).strip()
    has_visible_text = len(text_payload) >= 500

    if any(marker in low_html for marker in JS_REQUIRED_MARKERS):
        return True
    if "text/html" in str(content_type or "").lower():
        if len(html) < 1800:
            return True
        if density < 0.07:
            return True
        if not has_visible_text:
            return True
    if any(token in domain for token in OFFICIAL_RENDER_HINTS):
        if density < 0.13 or len(text_payload) < 1200:
            return True
    if source_policy in {"official", "academic"} and density < 0.09:
        return True
    return False


async def _static_fetch_html(
    url: str,
    *,
    timeout_s: int = STATIC_TIMEOUT_S,
) -> dict[str, Any]:
    try:
        import aiohttp
    except ImportError:
        return {"success": False, "error": "aiohttp kurulu değil."}

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout_s)) as session:
        async with session.get(url, headers=headers, allow_redirects=True) as response:
            html = await response.text(errors="ignore")
            return {
                "success": response.status == 200,
                "status_code": int(response.status),
                "url": str(response.url),
                "html": html,
                "headers": dict(response.headers),
                "render_mode": "static",
            }


class _PlaywrightPool:
    def __init__(self) -> None:
        self._playwright = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def browser(self):
        async with self._lock:
            if self._browser is not None:
                return self._browser
            try:
                from playwright.async_api import async_playwright
            except Exception as exc:
                raise RuntimeError(f"playwright_unavailable:{exc}") from exc

            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(headless=True)
            return self._browser

    async def close(self) -> None:
        async with self._lock:
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    pass
                self._browser = None
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None


_POOL = _PlaywrightPool()


async def _browser_fetch_html(
    url: str,
    *,
    timeout_s: int = RENDER_TIMEOUT_S,
) -> dict[str, Any]:
    browser = await _POOL.browser()
    page = await browser.new_page()
    try:
        await page.goto(url, wait_until="networkidle", timeout=max(5000, int(timeout_s * 1000)))
        html = await page.content()
        return {
            "success": True,
            "status_code": 200,
            "url": page.url,
            "html": html,
            "headers": {},
            "render_mode": "browser",
        }
    finally:
        try:
            await page.close()
        except Exception:
            pass


async def smart_fetch_html(
    url: str,
    *,
    source_policy: str = "balanced",
    prefer_browser: bool = False,
    static_timeout_s: int = STATIC_TIMEOUT_S,
    render_timeout_s: int = RENDER_TIMEOUT_S,
) -> dict[str, Any]:
    is_safe, error = _is_safe_url(url)
    if not is_safe:
        return {"success": False, "error": error}

    if url.startswith("http://"):
        url = url.replace("http://", "https://", 1)

    static_result: dict[str, Any] = {}
    if not prefer_browser:
        try:
            static_result = await _static_fetch_html(url, timeout_s=static_timeout_s)
        except asyncio.TimeoutError:
            static_result = {"success": False, "error": "static_timeout", "render_mode": "static"}
        except Exception as exc:
            static_result = {"success": False, "error": str(exc), "render_mode": "static"}

        if static_result.get("success") and not _needs_browser_render(
            url=str(static_result.get("url") or url),
            html=str(static_result.get("html") or ""),
            status_code=int(static_result.get("status_code") or 0),
            content_type=str((static_result.get("headers") or {}).get("Content-Type") or ""),
            source_policy=source_policy,
        ):
            return static_result

    try:
        return await asyncio.wait_for(_browser_fetch_html(url, timeout_s=render_timeout_s), timeout=render_timeout_s + 3)
    except Exception as exc:
        logger.debug("browser_fetch_failed: %s", exc)
        if static_result:
            return {
                **static_result,
                "warnings": [f"browser_fetch_failed:{exc}"],
            }
        return {"success": False, "error": str(exc), "render_mode": "browser"}


async def smart_fetch_page(
    url: str,
    *,
    extract_content: bool = True,
    max_length: int = MAX_CONTENT_LENGTH,
    source_policy: str = "balanced",
    prefer_browser: bool = False,
) -> dict[str, Any]:
    fetch_result = await smart_fetch_html(
        url,
        source_policy=source_policy,
        prefer_browser=prefer_browser,
    )
    if not fetch_result.get("success"):
        return fetch_result

    html = str(fetch_result.get("html") or "")
    if not extract_content:
        return {
            "success": True,
            "url": str(fetch_result.get("url") or url),
            "html": html[:max_length],
            "length": len(html),
            "truncated": len(html) > max_length,
            "render_mode": fetch_result.get("render_mode", "static"),
            "status_code": fetch_result.get("status_code", 200),
        }

    extracted = _extract_text(html, str(fetch_result.get("url") or url))
    if not extracted.get("success"):
        return extracted

    text = str(extracted.get("text") or "")[:max_length]
    density = _extract_text_density(html)
    return {
        "success": True,
        "url": str(fetch_result.get("url") or url),
        "title": str(extracted.get("title") or ""),
        "content": text,
        "length": len(text),
        "truncated": len(str(extracted.get("text") or "")) > max_length,
        "render_mode": fetch_result.get("render_mode", "static"),
        "status_code": fetch_result.get("status_code", 200),
        "text_density": round(float(density), 4),
    }


async def close_smart_fetch_browser() -> None:
    await _POOL.close()


__all__ = [
    "smart_fetch_html",
    "smart_fetch_page",
    "close_smart_fetch_browser",
]
