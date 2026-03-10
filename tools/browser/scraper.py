"""
Browser scraping wrappers over the V3 browser runtime.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger("browser_scraper")


def _screen_runner():
    from core.runtime.hosts import get_desktop_host

    return get_desktop_host().run_screen_operator


async def scrape_page(url: str, selectors: Optional[List[str]] = None) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        open_result = await run_browser_runtime(
            action="open",
            url=url,
            expected_url_contains=str(url or "").strip(),
            screenshot=True,
            screen_operator_runner=_screen_runner(),
        )
        if not open_result.get("success"):
            return {"success": False, "error": str(open_result.get("error") or open_result.get("message") or "browser_open_failed")}

        data = {
            "url": str(open_result.get("url") or ""),
            "title": str(open_result.get("title") or ""),
        }
        if selectors:
            for selector in list(selectors or []):
                extract_result = await run_browser_runtime(
                    action="extract",
                    selector=str(selector or ""),
                    screenshot=False,
                    screen_operator_runner=_screen_runner(),
                )
                data[str(selector or "")] = str(extract_result.get("extracted_text") or "") if extract_result.get("success") else None
        else:
            extract_result = await run_browser_runtime(
                action="extract",
                selector="",
                screenshot=False,
                screen_operator_runner=_screen_runner(),
            )
            data["text"] = str(extract_result.get("extracted_text") or "")
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"scrape_page error: {e}")
        return {"success": False, "error": str(e)}


async def scrape_links(url: str, pattern: Optional[str] = None) -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        open_result = await run_browser_runtime(
            action="open",
            url=url,
            expected_url_contains=str(url or "").strip(),
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        if not open_result.get("success"):
            return {"success": False, "error": str(open_result.get("error") or open_result.get("message") or "browser_open_failed")}
        link_result = await run_browser_runtime(
            action="links",
            pattern=str(pattern or ""),
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        if not link_result.get("success"):
            return {"success": False, "error": str(link_result.get("error") or link_result.get("message") or "link_extraction_failed")}
        return {"success": True, "links": list(link_result.get("links") or [])}
    except Exception as e:
        logger.error(f"scrape_links error: {e}")
        return {"success": False, "error": str(e)}


async def scrape_table(url: str, table_selector: str = "table") -> Dict[str, Any]:
    try:
        from core.capabilities.browser import run_browser_runtime

        open_result = await run_browser_runtime(
            action="open",
            url=url,
            expected_url_contains=str(url or "").strip(),
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        if not open_result.get("success"):
            return {"success": False, "error": str(open_result.get("error") or open_result.get("message") or "browser_open_failed")}
        table_result = await run_browser_runtime(
            action="table",
            table_selector=table_selector,
            screenshot=False,
            screen_operator_runner=_screen_runner(),
        )
        if not table_result.get("success"):
            return {"success": False, "error": str(table_result.get("error") or table_result.get("message") or "table_extraction_failed")}
        table = table_result.get("table") if isinstance(table_result.get("table"), dict) else {}
        return {"success": True, "headers": list(table.get("headers") or []), "rows": list(table.get("rows") or [])}
    except Exception as e:
        logger.error(f"scrape_table error: {e}")
        return {"success": False, "error": str(e)}
