"""Web Search - Search the internet for information"""

import asyncio
from typing import Any
from urllib.parse import quote_plus
from utils.logger import get_logger

logger = get_logger("web.search")

# Rate limiting
RATE_LIMIT_SECONDS = 5
_last_search_time = 0


async def web_search(
    query: str,
    num_results: int = 5,
    language: str = "tr"
) -> dict[str, Any]:
    """Search the web for information

    Args:
        query: Search query
        num_results: Number of results to return (max 10)
        language: Search language (tr, en)

    Note: This uses DuckDuckGo HTML search as it doesn't require API keys.
          For production use, consider Google Custom Search API or Bing API.
    """
    global _last_search_time

    try:
        import time

        # Rate limiting
        current_time = time.time()
        elapsed = current_time - _last_search_time
        if elapsed < RATE_LIMIT_SECONDS:
            wait_time = RATE_LIMIT_SECONDS - elapsed
            await asyncio.sleep(wait_time)

        _last_search_time = time.time()

        try:
            import aiohttp
            from bs4 import BeautifulSoup
        except ImportError:
            return {
                "success": False,
                "error": "aiohttp ve beautifulsoup4 kurulu değil. 'pip install aiohttp beautifulsoup4' çalıştırın."
            }

        # DuckDuckGo HTML search URL
        encoded_query = quote_plus(query)
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

        if language == "tr":
            url += "&kl=tr-tr"

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": f"{language}-{language.upper()},{language};q=0.9,en;q=0.8",
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    return {
                        "success": False,
                        "error": f"Arama hatası: HTTP {response.status}"
                    }

                html = await response.text()

        # Parse results
        soup = BeautifulSoup(html, "html.parser")
        results = []

        # DuckDuckGo result structure
        for result in soup.select(".result"):
            if len(results) >= min(num_results, 10):
                break

            title_elem = result.select_one(".result__title a")
            snippet_elem = result.select_one(".result__snippet")
            url_elem = result.select_one(".result__url")

            if title_elem:
                title = title_elem.get_text(strip=True)
                href = title_elem.get("href", "")

                # DuckDuckGo wraps URLs
                if "uddg=" in href:
                    import urllib.parse
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
                    href = parsed.get("uddg", [href])[0]

                snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                display_url = url_elem.get_text(strip=True) if url_elem else href

                results.append({
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                    "display_url": display_url
                })

        logger.info(f"Search '{query}': found {len(results)} results")

        return {
            "success": True,
            "query": query,
            "results": results,
            "count": len(results)
        }

    except asyncio.TimeoutError:
        return {"success": False, "error": "Arama zaman aşımına uğradı"}
    except Exception as e:
        logger.error(f"Search error: {e}")
        return {"success": False, "error": str(e)}
