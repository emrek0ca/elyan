from __future__ import annotations

import asyncio
import random
import time
from typing import Any

from core.dependencies import get_dependency_runtime

from ..base import BaseConnector, ConnectorResult, ConnectorSnapshot, ConnectorState


def _looks_like_url(value: str) -> bool:
    low = str(value or "").strip().lower()
    return low.startswith(("http://", "https://")) or "." in low or low.startswith("www.")


class BrowserConnector(BaseConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.client = None
        self.page = None
        self.context = None
        self._profile_id = str(self.metadata.get("profile_id") or self.session_id or self.provider or "default").strip() or "default"
        self._last_url = ""
        self._last_title = ""
        self._last_text = ""

    def _ensure_runtime(self) -> bool:
        runtime = get_dependency_runtime()
        record = runtime.ensure_module(
            "playwright",
            install_spec="playwright",
            source="pypi",
            trust_level="trusted",
            post_install=["playwright install chromium"],
            skill_name=self.capability.name or "browser",
            tool_name="browser_runtime",
            allow_install=True,
        )
        return str(record.status).lower() in {"installed", "ready"}

    async def _ensure_client(self) -> bool:
        if self.page is not None:
            return True
        if not self._ensure_runtime():
            return False
        from tools.browser.cdp_client import get_browser_session

        self.client = await get_browser_session(profile_id=self._profile_id)
        self.context = getattr(self.client, "context", None)
        self.page = getattr(self.client, "page", None)
        return self.page is not None

    async def _human_pause(self) -> None:
        await asyncio.sleep(max(0.03, random.gauss(0.12, 0.05)))

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        if not await self._ensure_client():
            return self._result(
                success=False,
                status="blocked",
                error="playwright_unavailable",
                message="browser_runtime_missing",
                retryable=True,
                fallback_reason="playwright_unavailable",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
            )
        target = str(app_name_or_url or "").strip()
        result = {"success": True, "status": "ready", "message": "browser_ready"}
        if target and _looks_like_url(target):
            await self._human_pause()
            result = await self.page.goto(target if target.startswith(("http://", "https://")) else f"https://{target}", wait_until="domcontentloaded")
            self._last_url = self.page.url
            self._last_title = await self.page.title()
        elif target:
            self._last_url = getattr(self.page, "url", "")
            self._last_title = await self.page.title()
        snapshot = await self.snapshot()
        return self._result(
            success=True,
            status="ready",
            message=f"connected:{target or self._profile_id}",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            result={"navigation": str(result or {})},
            snapshot=snapshot,
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )

    def _locator_from_action(self, action: dict[str, Any]):
        if self.page is None:
            return None
        target = action.get("target")
        selector = ""
        text = ""
        if isinstance(target, dict):
            selector = str(target.get("selector") or target.get("css") or target.get("xpath") or "").strip()
            text = str(target.get("text") or target.get("label") or target.get("name") or "").strip()
        else:
            selector = str(action.get("selector") or action.get("css") or action.get("xpath") or "").strip()
            text = str(action.get("target") or action.get("text") or action.get("label") or "").strip()
        if selector:
            return self.page.locator(selector)
        if text:
            return self.page.get_by_text(text, exact=False)
        return None

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        started = time.perf_counter()
        if not await self._ensure_client():
            return self._result(
                success=False,
                status="blocked",
                error="playwright_unavailable",
                retryable=True,
                fallback_reason="playwright_unavailable",
                latency_ms=(time.perf_counter() - started) * 1000.0,
            )
        payload = dict(action or {})
        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        result: dict[str, Any] = {}
        await self._human_pause()
        try:
            if kind in {"open_url", "navigate"}:
                url = str(payload.get("url") or payload.get("target") or payload.get("text") or "").strip()
                if url and not url.startswith(("http://", "https://")):
                    url = f"https://{url}"
                response = await self.page.goto(url, wait_until="domcontentloaded")
                self._last_url = self.page.url
                self._last_title = await self.page.title()
                result = {"success": True, "status": "success", "url": self.page.url, "title": self._last_title, "http_status": getattr(response, "status", None)}
            elif kind == "click":
                locator = self._locator_from_action(payload)
                if locator is not None:
                    await locator.first.click(timeout=5000)
                    result = {"success": True, "status": "success", "action": "click"}
                else:
                    x = float(payload.get("x", 0) or 0)
                    y = float(payload.get("y", 0) or 0)
                    await self.page.mouse.click(x, y, button=str(payload.get("button") or "left"), click_count=2 if bool(payload.get("double", False)) else 1)
                    result = {"success": True, "status": "success", "action": "click", "x": x, "y": y}
            elif kind in {"type", "fill"}:
                locator = self._locator_from_action(payload)
                text = str(payload.get("text") or payload.get("value") or "").strip()
                if locator is not None:
                    await locator.first.fill(text, timeout=5000)
                else:
                    await self.page.keyboard.type(text)
                if bool(payload.get("press_enter", False)):
                    await self.page.keyboard.press("Enter")
                result = {"success": True, "status": "success", "action": "type", "text": text}
            elif kind == "press_key":
                key = str(payload.get("key") or "").strip()
                modifiers = list(payload.get("modifiers") or [])
                if modifiers:
                    combo = "+".join([*modifiers, key])
                    await self.page.keyboard.press(combo)
                else:
                    await self.page.keyboard.press(key)
                result = {"success": True, "status": "success", "action": "press_key", "key": key}
            elif kind == "scroll":
                dx = float(payload.get("dx", 0) or 0)
                dy = float(payload.get("dy", payload.get("amount", 0)) or 0)
                await self.page.mouse.wheel(dx, dy)
                result = {"success": True, "status": "success", "action": "scroll", "dx": dx, "dy": dy}
            elif kind == "screenshot":
                path = str(payload.get("path") or payload.get("filename") or "")
                if not path:
                    path = f"/tmp/elyan_browser_{int(time.time() * 1000)}.png"
                await self.page.screenshot(path=path, full_page=bool(payload.get("full_page", True)))
                result = {"success": True, "status": "success", "path": path}
            elif kind == "extract_text":
                text = await self.page.content()
                self._last_text = text[:4000]
                result = {"success": True, "status": "success", "text": self._last_text}
            elif kind == "inspect":
                result = {
                    "success": True,
                    "status": "success",
                    "url": getattr(self.page, "url", self._last_url),
                    "title": await self.page.title() if self.page else self._last_title,
                    "text": (await self.page.content())[:4000],
                }
            elif kind == "wait":
                await asyncio.sleep(float(payload.get("seconds") or 0.2))
                result = {"success": True, "status": "success", "action": "wait"}
            else:
                locator = self._locator_from_action(payload)
                if locator is not None and kind in {"submit", "open"}:
                    await locator.first.click(timeout=5000)
                    result = {"success": True, "status": "success", "action": kind}
                else:
                    result = {"success": True, "status": "success", "action": kind or "noop"}
        except Exception as exc:
            return self._result(
                success=False,
                status="failed",
                error=str(exc),
                message=str(exc),
                retryable=True,
                latency_ms=(time.perf_counter() - started) * 1000.0,
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
                metadata={"action": payload},
            )
        snapshot = await self.snapshot()
        return self._result(
            success=bool(result.get("success", True)),
            status=str(result.get("status") or "success"),
            message=str(result.get("message") or ""),
            latency_ms=(time.perf_counter() - started) * 1000.0,
            evidence=[{"kind": "browser_state", "url": getattr(self.page, "url", self._last_url), "title": await self.page.title() if self.page else self._last_title}],
            artifacts=list(result.get("artifacts") or []),
            snapshot=snapshot,
            result=result,
            retryable=bool(result.get("retryable", False)),
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )

    async def snapshot(self) -> ConnectorSnapshot:
        if not await self._ensure_client():
            return self._snapshot(state="missing", metadata={"reason": "playwright_unavailable"}, auth_state=ConnectorState.MISSING)
        url = getattr(self.page, "url", self._last_url or "")
        title = self._last_title
        text = self._last_text
        try:
            title = await self.page.title()
        except Exception:
            pass
        try:
            if not text:
                text = await self.page.content()
        except Exception:
            pass
        return self._snapshot(
            state="ready",
            url=url,
            title=title,
            elements=[],
            artifacts=[],
            metadata={
                "profile_id": self._profile_id,
                "text_preview": (text or "")[:1000],
            },
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.NEEDS_INPUT,
        )

