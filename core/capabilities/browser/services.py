from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from tools.browser.manager import close_browser_manager, get_browser_manager, is_playwright_available


AsyncDictCallable = Callable[..., Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class BrowserRuntimeServices:
    ensure_session: AsyncDictCallable
    goto: AsyncDictCallable
    click: AsyncDictCallable
    fill: AsyncDictCallable
    press: AsyncDictCallable
    get_text: AsyncDictCallable
    get_value: AsyncDictCallable
    get_state: Callable[[], Awaitable[dict[str, Any]]]
    get_dom_snapshot: Callable[[], Awaitable[dict[str, Any]]]
    screenshot: AsyncDictCallable
    wait_for: AsyncDictCallable
    scroll: AsyncDictCallable
    query_links: AsyncDictCallable
    query_table: AsyncDictCallable
    close: Callable[[], Awaitable[dict[str, Any]]]


def _html_hash(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8", errors="ignore")).hexdigest()


async def _browser_page():
    browser = await get_browser_manager()
    if not browser or not browser.page:
        return None, {
            "success": False,
            "error": "Playwright browser not available",
            "error_code": "DOM_UNAVAILABLE",
            "dom_available": False,
        }
    return browser, {"success": True, "dom_available": True, "session_id": browser.session_id}


async def _ensure_session(headless: bool = True) -> dict[str, Any]:
    browser = await get_browser_manager(headless=headless)
    if not browser or not browser.page:
        return {
            "success": False,
            "error": "Playwright browser not available",
            "error_code": "DOM_UNAVAILABLE",
            "dom_available": False,
        }
    return {
        "success": True,
        "dom_available": True,
        "session_id": browser.session_id,
        "headless": bool(browser.headless),
    }


async def _goto(url: str, timeout_ms: int = 10000) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(url or "").strip()
    if not target:
        return {"success": False, "error": "url_missing", "error_code": "INTENT_PARAM_MISSING", "dom_available": True}
    if not target.startswith(("http://", "https://")):
        target = "https://" + target
    try:
        response = await browser.page.goto(target, wait_until="domcontentloaded", timeout=int(timeout_ms or 10000))
        await browser.page.wait_for_load_state("domcontentloaded")
        return {
            "success": True,
            "url": browser.page.url,
            "title": await browser.page.title(),
            "status_code": response.status if response else None,
            "dom_available": True,
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "NAVIGATION_FAILED", "dom_available": True}


async def _click(selector: str, timeout_ms: int = 5000) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(selector or "").strip()
    if not target:
        return {"success": False, "error": "selector_missing", "error_code": "INTENT_PARAM_MISSING", "dom_available": True}
    try:
        await browser.page.wait_for_selector(target, timeout=int(timeout_ms or 5000), state="visible")
        await browser.page.click(target)
        return {"success": True, "selector": target, "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_TARGET_NOT_FOUND", "selector": target, "dom_available": True}


async def _fill(selector: str, text: str, timeout_ms: int = 5000) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(selector or "").strip()
    try:
        await browser.page.wait_for_selector(target, timeout=int(timeout_ms or 5000), state="visible")
        await browser.page.fill(target, str(text or ""))
        return {"success": True, "selector": target, "text": str(text or ""), "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_TARGET_NOT_FOUND", "selector": target, "dom_available": True}


async def _press(selector: Optional[str] = None, key: str = "Enter", timeout_ms: int = 5000) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(selector or "").strip()
    try:
        if target:
            await browser.page.wait_for_selector(target, timeout=int(timeout_ms or 5000), state="visible")
            await browser.page.press(target, str(key or "Enter"))
        else:
            await browser.page.keyboard.press(str(key or "Enter"))
        return {"success": True, "selector": target, "key": str(key or "Enter"), "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_TARGET_NOT_FOUND", "selector": target, "dom_available": True}


async def _get_text(selector: Optional[str] = None) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(selector or "").strip()
    try:
        if target:
            await browser.page.wait_for_selector(target, timeout=5000, state="visible")
            text = await browser.page.text_content(target)
        else:
            text = await browser.page.evaluate("() => document.body ? document.body.innerText : ''")
        return {"success": True, "selector": target, "text": str(text or ""), "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_TARGET_NOT_FOUND", "selector": target, "dom_available": True}


async def _get_value(selector: str) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(selector or "").strip()
    try:
        await browser.page.wait_for_selector(target, timeout=5000, state="visible")
        value = await browser.page.input_value(target)
        return {"success": True, "selector": target, "value": str(value or ""), "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_TARGET_NOT_FOUND", "selector": target, "dom_available": True}


async def _get_state() -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    try:
        url = browser.page.url
        title = await browser.page.title()
        html = await browser.page.content()
        text = await browser.page.evaluate("() => document.body ? document.body.innerText : ''")
        return {
            "success": True,
            "dom_available": True,
            "url": str(url or ""),
            "title": str(title or ""),
            "visible_text": str(text or ""),
            "dom_hash": _html_hash(html),
            "session_id": browser.session_id,
            "headless": bool(browser.headless),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_STATE_FAILED", "dom_available": True}


async def _get_dom_snapshot() -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    try:
        html = await browser.page.content()
        text = await browser.page.evaluate("() => document.body ? document.body.innerText : ''")
        return {
            "success": True,
            "dom_available": True,
            "html": str(html or ""),
            "visible_text": str(text or ""),
            "url": browser.page.url,
            "title": await browser.page.title(),
            "dom_hash": _html_hash(html),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "DOM_SNAPSHOT_FAILED", "dom_available": True}


async def _screenshot(path: Optional[str] = None, selector: Optional[str] = None) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    output = str(path or "").strip() or f"/tmp/browser_runtime_{int(time.time() * 1000)}.png"
    try:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        if selector:
            await browser.page.locator(str(selector)).screenshot(path=output)
        else:
            await browser.page.screenshot(path=output, full_page=True)
        return {"success": True, "path": output, "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "SCREENSHOT_FAILED", "path": output, "dom_available": True}


async def _wait_for(selector: str, timeout_ms: int = 10000, state: str = "visible") -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    target = str(selector or "").strip()
    try:
        await browser.page.wait_for_selector(target, timeout=int(timeout_ms or 10000), state=state or "visible")
        return {"success": True, "found": True, "selector": target, "dom_available": True}
    except Exception as e:
        return {"success": False, "found": False, "error": str(e), "error_code": "DOM_TARGET_NOT_FOUND", "selector": target, "dom_available": True}


async def _scroll(direction: str = "down", amount: int = 500) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    delta = int(amount or 500)
    expr = {
        "down": f"window.scrollBy(0, {delta})",
        "up": f"window.scrollBy(0, {-delta})",
        "right": f"window.scrollBy({delta}, 0)",
        "left": f"window.scrollBy({-delta}, 0)",
    }.get(str(direction or "down").strip().lower(), f"window.scrollBy(0, {delta})")
    try:
        before = await browser.page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
        await browser.page.evaluate(f"() => {{ {expr}; }}")
        after = await browser.page.evaluate("() => ({x: window.scrollX, y: window.scrollY})")
        return {"success": True, "dom_available": True, "direction": direction, "amount": delta, "before": before, "after": after}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "SCROLL_FAILED", "dom_available": True}


async def _query_links(pattern: Optional[str] = None) -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    try:
        links = await browser.page.evaluate(
            """() => Array.from(document.querySelectorAll('a[href]')).map(a => ({
                href: a.href,
                text: (a.innerText || '').trim(),
                title: a.title || ''
            }))"""
        )
        if pattern:
            links = [item for item in list(links or []) if str(pattern) in str((item or {}).get("href") or "")]
        return {"success": True, "links": list(links or []), "count": len(list(links or [])), "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "LINK_EXTRACTION_FAILED", "dom_available": True}


async def _query_table(selector: str = "table") -> dict[str, Any]:
    browser, ready = await _browser_page()
    if not ready.get("success"):
        return ready
    table_selector = str(selector or "table").strip() or "table"
    try:
        table = await browser.page.evaluate(
            """(selector) => {
                const table = document.querySelector(selector);
                if (!table) return null;
                const headers = Array.from(table.querySelectorAll('th')).map(th => (th.innerText || '').trim());
                const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr =>
                    Array.from(tr.querySelectorAll('td')).map(td => (td.innerText || '').trim())
                );
                return {headers, rows};
            }""",
            table_selector,
        )
        if not table:
            return {"success": False, "error": "table_not_found", "error_code": "DOM_TARGET_NOT_FOUND", "dom_available": True}
        return {"success": True, "headers": list(table.get("headers") or []), "rows": list(table.get("rows") or []), "dom_available": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "TABLE_EXTRACTION_FAILED", "dom_available": True}


async def _close() -> dict[str, Any]:
    try:
        await close_browser_manager()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e), "error_code": "BROWSER_CLOSE_FAILED"}


def default_browser_runtime_services() -> BrowserRuntimeServices:
    return BrowserRuntimeServices(
        ensure_session=_ensure_session,
        goto=_goto,
        click=_click,
        fill=_fill,
        press=_press,
        get_text=_get_text,
        get_value=_get_value,
        get_state=_get_state,
        get_dom_snapshot=_get_dom_snapshot,
        screenshot=_screenshot,
        wait_for=_wait_for,
        scroll=_scroll,
        query_links=_query_links,
        query_table=_query_table,
        close=_close,
    )


__all__ = ["BrowserRuntimeServices", "default_browser_runtime_services", "is_playwright_available"]
