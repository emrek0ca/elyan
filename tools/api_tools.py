"""
Elyan API Test Tools — HTTP client, GraphQL, WebSocket testing

Full HTTP methods, header/body management, response analysis.
"""

import asyncio
import json
import time
from typing import Any, Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("api_tools")


async def http_request(
    url: str,
    method: str = "GET",
    headers: Dict[str, str] = None,
    body: Any = None,
    timeout: int = 30,
    retries: int = 2,
    backoff_ms: int = 300,
    circuit_breaker: bool = True,
) -> Dict[str, Any]:
    """Make an HTTP request and return structured response."""
    import httpx
    t0 = time.time()
    last_error: str = ""
    attempts = max(1, retries + 1)
    for attempt in range(1, attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                kwargs = {"headers": headers or {}}
                if body and method.upper() in ("POST", "PUT", "PATCH"):
                    if isinstance(body, (dict, list)):
                        kwargs["json"] = body
                    else:
                        kwargs["content"] = str(body)

                resp = await getattr(client, method.lower())(url, **kwargs)

                duration_ms = int((time.time() - t0) * 1000)
                content_type = resp.headers.get("content-type", "")

                # Try JSON parse
                response_body = resp.text[:50000]
                try:
                    if "json" in content_type:
                        response_body = resp.json()
                except Exception:
                    pass

                return {
                    "success": 200 <= resp.status_code < 400,
                    "status_code": resp.status_code,
                    "headers": dict(resp.headers),
                    "body": response_body,
                    "duration_ms": duration_ms,
                    "url": str(resp.url),
                }
        except Exception as e:
            last_error = str(e)
            if attempt < attempts:
                await asyncio.sleep(backoff_ms / 1000.0 * attempt)
                continue
    return {
        "success": False,
        "error": last_error or "HTTP request failed",
        "duration_ms": int((time.time() - t0) * 1000),
    }


async def graphql_query(url: str, query: str, variables: Dict = None, headers: Dict = None) -> Dict[str, Any]:
    """Execute a GraphQL query."""
    body = {"query": query}
    if variables:
        body["variables"] = variables
    return await http_request(url, method="POST", headers=headers, body=body)


async def api_health_check(urls: List[str]) -> Dict[str, Any]:
    """Check health of multiple API endpoints."""
    t0 = time.time()
    normalized_urls = [str(u or "").strip() for u in list(urls or []) if str(u or "").strip()]
    results = {}
    for url in normalized_urls:
        result = await http_request(url, method="GET", timeout=10)
        results[url] = {
            "healthy": result.get("success", False),
            "status_code": result.get("status_code"),
            "duration_ms": result.get("duration_ms"),
            "error": result.get("error", ""),
        }
    healthy_count = sum(1 for r in results.values() if r["healthy"])
    total = len(normalized_urls)
    duration_ms = int((time.time() - t0) * 1000)
    return {
        "success": bool(total > 0 and healthy_count == total),
        "total": total,
        "healthy": healthy_count,
        "unhealthy": total - healthy_count,
        "duration_ms": duration_ms,
        "results": results,
    }
