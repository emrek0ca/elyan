"""
Browser automation tools

Compatibility wrappers over the V3 browser runtime.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from utils.logger import get_logger

logger = get_logger("browser_automation")


def _screen_runner():
    from core.runtime.hosts import get_desktop_host

    return get_desktop_host().run_screen_operator


async def browser_open(url: str, headless: bool = True) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="open",
            url=url,
            headless=headless,
            expected_url_contains=str(url or "").strip(),
            screenshot=True,
            screen_operator_runner=_screen_runner(),
        )
        return {
            "success": bool(result.get("success")),
            "url": str(result.get("url") or ""),
            "title": str(result.get("title") or ""),
            "status": (result.get("action_result") if isinstance(result.get("action_result"), dict) else {}).get("status_code"),
            "message": str(result.get("message") or ""),
            "artifacts": list(result.get("artifacts") or []),
            "verification": (list(result.get("verifier_outcomes") or [{}]) or [{}])[0],
            "fallback": dict(result.get("fallback") or {}),
            **({"error": str(result.get("error") or "")} if not result.get("success") else {}),
        }
    except Exception as e:
        logger.error(f"browser_open error: {e}")
        return {"success": False, "error": str(e)}


async def browser_click(selector: str) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="click",
            selector=selector,
            screenshot=True,
            screen_operator_runner=_screen_runner(),
        )
        return {
            "success": bool(result.get("success")),
            "clicked": bool(result.get("success")),
            "message": str(result.get("message") or ""),
            "verification": (list(result.get("verifier_outcomes") or [{}]) or [{}])[0],
            "artifacts": list(result.get("artifacts") or []),
            **({"error": str(result.get("error") or "")} if not result.get("success") else {}),
        }
    except Exception as e:
        logger.error(f"browser_click error: {e}")
        return {"success": False, "error": str(e)}


async def browser_type(selector: str, text: str) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="type",
            selector=selector,
            text=text,
            screenshot=True,
            screen_operator_runner=_screen_runner(),
        )
        return {
            "success": bool(result.get("success")),
            "message": str(result.get("message") or ""),
            "verification": (list(result.get("verifier_outcomes") or [{}]) or [{}])[0],
            "artifacts": list(result.get("artifacts") or []),
            **({"error": str(result.get("error") or "")} if not result.get("success") else {}),
        }
    except Exception as e:
        logger.error(f"browser_type error: {e}")
        return {"success": False, "error": str(e)}


async def browser_screenshot(selector: Optional[str] = None) -> Optional[str]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="screenshot",
            selector=selector or "",
            screenshot=True,
            screen_operator_runner=_screen_runner(),
        )
        screenshots = [str(path).strip() for path in list(result.get("screenshots") or []) if str(path).strip()]
        return screenshots[-1] if screenshots else None
    except Exception as e:
        logger.error(f"browser_screenshot error: {e}")
        return None


async def browser_get_text(selector: str) -> Optional[str]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="extract",
            selector=selector,
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        if not result.get("success"):
            return None
        return str(result.get("extracted_text") or "")
    except Exception as e:
        logger.error(f"browser_get_text error: {e}")
        return None


async def browser_scroll(direction: str = "down", amount: int = 500) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="scroll",
            selector=str(direction or "down"),
            text=str(int(amount or 500)),
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        return {
            "success": bool(result.get("success")),
            "message": str(result.get("message") or ""),
            **({"error": str(result.get("error") or "")} if not result.get("success") else {}),
        }
    except Exception as e:
        logger.error(f"browser_scroll error: {e}")
        return {"success": False, "error": str(e)}


async def browser_wait(selector: str, timeout: int = 10000) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(
            action="wait",
            selector=selector,
            timeout_ms=int(timeout or 10000),
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        return {
            "success": bool(result.get("success")),
            "found": bool(result.get("success")),
            "message": str(result.get("message") or ""),
            **({"error": str(result.get("error") or "")} if not result.get("success") else {}),
        }
    except Exception as e:
        logger.error(f"browser_wait error: {e}")
        return {"success": False, "found": False, "error": str(e)}


async def browser_close() -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(action="close", screenshot=False)
        return {"success": bool(result.get("success")), **({"error": str(result.get("message") or result.get("error") or "")} if not result.get("success") else {})}
    except Exception as e:
        logger.error(f"browser_close error: {e}")
        return {"success": False, "error": str(e)}


async def browser_status() -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        result = await run_browser_runtime(action="status", screenshot=False)
        state = result.get("browser_state") if isinstance(result.get("browser_state"), dict) else {}
        running = bool(result.get("success")) and bool(state.get("url") or state.get("title"))
        return {
            "success": bool(result.get("success")),
            "running": running,
            "url": state.get("url"),
            "title": state.get("title"),
            "session_id": state.get("session_id"),
            "headless": state.get("headless"),
            **({"error": str(result.get("message") or result.get("error") or "")} if not result.get("success") else {}),
        }
    except Exception as e:
        logger.error(f"browser_status error: {e}")
        return {"success": False, "error": str(e)}
