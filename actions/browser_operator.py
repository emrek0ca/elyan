from __future__ import annotations

from contextlib import contextmanager
import json
import os
from typing import Any

import requests

from runtime.capability_registry import SafeCapabilityError

try:
    from playwright.sync_api import sync_playwright
except Exception:  # pragma: no cover - optional dependency
    sync_playwright = None  # type: ignore[assignment]


SUPPORTED_BROWSER_APPS = {
    "google chrome",
    "chromium",
    "microsoft edge",
    "brave browser",
    "arc",
}
DEFAULT_CDP_ENDPOINTS = (
    "http://127.0.0.1:9222",
    "http://127.0.0.1:9223",
)


def _safe_text(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "..."
    return text


def _browser_app_key(value: str) -> str:
    return str(value or "").strip().lower()


def is_supported_browser_app(app_name: str) -> bool:
    return _browser_app_key(app_name) in SUPPORTED_BROWSER_APPS


def _cdp_candidates() -> list[str]:
    ordered: list[str] = []
    for candidate in (
        str(os.environ.get("ELYAN_BROWSER_CDP_URL", "") or "").strip(),
        *DEFAULT_CDP_ENDPOINTS,
    ):
        if candidate and candidate not in ordered:
            ordered.append(candidate.rstrip("/"))
    return ordered


def _probe_cdp_endpoint(endpoint: str) -> dict[str, Any] | None:
    try:
        response = requests.get(f"{endpoint}/json/version", timeout=1.5)
    except requests.RequestException:
        return None
    if not response.ok:
        return None
    try:
        payload = response.json() if response.text else {}
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    if not str(payload.get("webSocketDebuggerUrl", "") or "").strip():
        return None
    return payload


def runtime_status() -> dict[str, Any]:
    playwright_available = sync_playwright is not None
    cdp_endpoint = ""
    cdp_browser = ""
    for candidate in _cdp_candidates():
        payload = _probe_cdp_endpoint(candidate)
        if payload is None:
            continue
        cdp_endpoint = candidate
        cdp_browser = str(payload.get("Browser", "") or "").strip()
        break
    return {
        "playwrightAvailable": playwright_available,
        "cdpEndpoint": cdp_endpoint,
        "cdpReachable": bool(cdp_endpoint),
        "browserFirstReady": playwright_available and bool(cdp_endpoint),
        "browserName": cdp_browser,
        "lastErrorCode": "" if (playwright_available and cdp_endpoint) else (
            "playwright_unavailable" if not playwright_available else "browser_cdp_unavailable"
        ),
    }


@contextmanager
def _with_active_page(app_name: str, window_title: str = ""):
    status = runtime_status()
    if sync_playwright is None:
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Playwright bu kurulumda hazir degil.")
    if not is_supported_browser_app(app_name):
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Aktif pencere browser-first operator icin desteklenmiyor.")
    endpoint = str(status.get("cdpEndpoint", "") or "").strip()
    if not endpoint:
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Browser CDP baglantisi hazir degil.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(endpoint)
        page = None
        contexts = list(browser.contexts)
        title_hint = str(window_title or "").strip().lower()
        candidates = []
        for context in contexts:
            for candidate in context.pages:
                try:
                    page_title = str(candidate.title() or "").strip()
                    page_url = str(candidate.url or "").strip()
                except Exception:
                    continue
                score = 0
                if title_hint and title_hint in page_title.lower():
                    score += 20
                if page_url.startswith("http"):
                    score += 5
                candidates.append((score, candidate))
        if candidates:
            candidates.sort(key=lambda item: item[0], reverse=True)
            page = candidates[0][1]
        elif contexts and contexts[0].pages:
            page = contexts[0].pages[0]
        if page is None:
            browser.close()
            raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Browser sayfasi bulunamadi.")
        try:
            yield page
        finally:
            try:
                browser.close()
            except Exception:
                pass


def observe_browser_window(app_name: str, window_title: str = "") -> dict[str, Any]:
    with _with_active_page(app_name, window_title) as page:
        extracted = page.evaluate(
            """
            () => {
              const active = document.activeElement;
              const visible = (el) => {
                if (!(el instanceof HTMLElement)) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 1 && rect.height > 1;
              };
              const textFor = (el) => {
                const aria = el.getAttribute('aria-label') || '';
                const value = 'value' in el ? String(el.value || '') : '';
                const inner = (el.innerText || el.textContent || '').trim();
                return (aria || value || inner).replace(/\\s+/g, ' ').trim().slice(0, 160);
              };
              const selectorFor = (el) => {
                if (!(el instanceof HTMLElement)) return '';
                const escape = (value) => (window.CSS && CSS.escape ? CSS.escape(value) : value);
                if (el.id) return `#${escape(el.id)}`;
                const testId = el.getAttribute('data-testid');
                if (testId) return `[data-testid="${testId.replace(/"/g, '\\"')}"]`;
                const name = el.getAttribute('name');
                const tag = el.tagName.toLowerCase();
                if (name && ['input', 'textarea', 'select', 'button'].includes(tag)) {
                  return `${tag}[name="${name.replace(/"/g, '\\"')}"]`;
                }
                const aria = el.getAttribute('aria-label');
                if (aria && ['button', 'input', 'textarea', 'select', 'a'].includes(tag)) {
                  return `${tag}[aria-label="${aria.replace(/"/g, '\\"')}"]`;
                }
                return '';
              };
              const typeFor = (el) => {
                const role = (el.getAttribute('role') || '').toLowerCase();
                const tag = el.tagName.toLowerCase();
                const inputType = (el.getAttribute('type') || '').toLowerCase();
                if (role === 'button' || tag === 'button') return 'button';
                if (tag === 'input' || tag === 'textarea' || role === 'textbox' || role === 'searchbox') return 'input';
                if (tag === 'a' || role === 'link') return 'text';
                if (inputType === 'checkbox' || role === 'checkbox') return 'checkbox';
                if (role === 'menuitem' || role === 'menu') return 'menu';
                if (tag === 'img' || role === 'img') return 'image';
                return role || tag || 'unknown';
              };
              const nodes = Array.from(document.querySelectorAll('button, a, input, textarea, select, [role], [aria-label], [contenteditable="true"], label'));
              const items = [];
              for (const el of nodes) {
                if (!visible(el)) continue;
                const rect = el.getBoundingClientRect();
                const text = textFor(el);
                const role = (el.getAttribute('role') || '').toLowerCase();
                items.push({
                  id: selectorFor(el) || `${el.tagName.toLowerCase()}_${items.length + 1}`,
                  type: typeFor(el),
                  text,
                  bbox: {
                    x: Math.round(rect.x),
                    y: Math.round(rect.y),
                    w: Math.round(rect.width),
                    h: Math.round(rect.height),
                  },
                  confidence: 0.995,
                  source: 'browser_dom',
                  role,
                  enabled: !('disabled' in el) || !el.disabled,
                  focused: active === el,
                  browser: {
                    selector: selectorFor(el),
                    role,
                    name: text,
                    tag: el.tagName.toLowerCase(),
                  },
                });
                if (items.length >= 120) break;
              }
              return {
                pageTitle: document.title || '',
                pageUrl: location.href || '',
                elements: items,
              };
            }
            """
        )
    payload = extracted if isinstance(extracted, dict) else {}
    elements = payload.get("elements", []) if isinstance(payload.get("elements"), list) else []
    return {
        "pageTitle": _safe_text(payload.get("pageTitle", ""), 200),
        "pageUrl": _safe_text(payload.get("pageUrl", ""), 400),
        "elements": [dict(item) for item in elements if isinstance(item, dict)],
    }


def _selector_for_target(target: dict[str, Any]) -> str:
    browser = target.get("browser", {})
    browser = browser if isinstance(browser, dict) else {}
    return str(browser.get("selector", "") or "").strip()


def _role_for_target(target: dict[str, Any]) -> str:
    browser = target.get("browser", {})
    browser = browser if isinstance(browser, dict) else {}
    return str(browser.get("role", "") or target.get("role", "") or "").strip().lower()


def _name_for_target(target: dict[str, Any]) -> str:
    browser = target.get("browser", {})
    browser = browser if isinstance(browser, dict) else {}
    return _safe_text(browser.get("name", "") or target.get("text", ""), 160)


def execute_browser_action(
    *,
    app_name: str,
    window_title: str,
    action_type: str,
    target: dict[str, Any] | None,
    text: str = "",
    keys: list[str] | None = None,
    delta: float | int | None = None,
    duration: float | int | None = None,
) -> dict[str, Any]:
    normalized_action = str(action_type or "").strip().lower()
    with _with_active_page(app_name, window_title) as page:
        locator = None
        if target is not None:
            selector = _selector_for_target(target)
            if selector:
                try:
                    locator = page.locator(selector).first
                except Exception:
                    locator = None
            if locator is None:
                role = _role_for_target(target)
                name = _name_for_target(target)
                if role and name:
                    try:
                        locator = page.get_by_role(role, name=name).first
                    except Exception:
                        locator = None
            if locator is None:
                name = _name_for_target(target)
                if name:
                    try:
                        locator = page.get_by_text(name, exact=True).first
                    except Exception:
                        locator = None

        if normalized_action == "click":
            if locator is None:
                raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Browser hedefi Playwright ile secilemedi.")
            locator.click(timeout=2500)
        elif normalized_action == "double_click":
            if locator is None:
                raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Browser hedefi Playwright ile secilemedi.")
            locator.dblclick(timeout=2500)
        elif normalized_action == "right_click":
            if locator is None:
                raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Browser hedefi Playwright ile secilemedi.")
            locator.click(button="right", timeout=2500)
        elif normalized_action == "type_text":
            if locator is None:
                raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Browser input hedefi Playwright ile secilemedi.")
            locator.click(timeout=2500)
            locator.fill(str(text or ""), timeout=2500)
        elif normalized_action == "hotkey":
            combo = "+".join(str(item or "").strip() for item in (keys or []) if str(item or "").strip())
            if not combo:
                raise SafeCapabilityError("INVALID_ARGUMENT", "Browser hotkey icin tus kombinasyonu belirtilmedi.")
            page.keyboard.press(combo)
        elif normalized_action == "scroll":
            page.mouse.wheel(0, float(delta or -320))
        elif normalized_action == "wait":
            page.wait_for_timeout(max(0, int(float(duration or 0.4) * 1000)))
        else:
            raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Bu aksiyon browser-first operator tarafinda desteklenmiyor.")
        return {
            "ok": True,
            "actionType": normalized_action,
            "pageTitle": _safe_text(page.title(), 200),
            "pageUrl": _safe_text(page.url, 400),
            "targetSource": "browser_dom",
        }
