"""Web Scraper - Fetch and extract content from web pages"""

import asyncio
import re
from typing import Any
from urllib.parse import urlparse
from utils.logger import get_logger

logger = get_logger("web.scraper")

# Security: Blocked URL patterns
BLOCKED_DOMAINS = [
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "192.168.",
    "10.",
    "172.16.",
    "169.254.",
    ".local",
    ".internal",
]

# Maximum content length
MAX_CONTENT_LENGTH = 50000

# Request timeout
REQUEST_TIMEOUT = 30


def _is_safe_url(url: str) -> tuple[bool, str]:
    """Check if URL is safe to fetch"""
    try:
        parsed = urlparse(url)

        # Must have http or https scheme
        if parsed.scheme not in ("http", "https"):
            return False, "Sadece HTTP/HTTPS destekleniyor"

        # Check blocked domains
        host = parsed.netloc.lower()
        for blocked in BLOCKED_DOMAINS:
            if blocked in host:
                return False, f"Bu URL'ye erişim engellenmiş: {blocked}"

        return True, ""

    except Exception as e:
        return False, f"URL geçersiz: {e}"


async def fetch_page(
    url: str,
    extract_content: bool = True,
    max_length: int = MAX_CONTENT_LENGTH
) -> dict[str, Any]:
    """Fetch a web page and optionally extract main content

    Args:
        url: URL to fetch
        extract_content: Whether to extract and clean the main content
        max_length: Maximum content length to return
    """
    try:
        # Validate URL
        is_safe, error = _is_safe_url(url)
        if not is_safe:
            return {"success": False, "error": error}

        # Ensure https
        if url.startswith("http://"):
            url = url.replace("http://", "https://", 1)

        try:
            import aiohttp
        except ImportError:
            return {"success": False, "error": "aiohttp kurulu değil. 'pip install aiohttp' çalıştırın."}

        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)) as session:
            async with session.get(url, headers=headers, allow_redirects=True) as response:
                if response.status != 200:
                    return {
                        "success": False,
                        "error": f"HTTP hatası: {response.status}",
                        "status_code": response.status
                    }

                content_type = response.headers.get("Content-Type", "")
                if "text/html" not in content_type and "text/plain" not in content_type:
                    return {
                        "success": False,
                        "error": f"Desteklenmeyen içerik türü: {content_type}"
                    }

                html = await response.text()

        # Extract content if requested
        if extract_content:
            result = await extract_text(html, url)
            if result.get("success"):
                text = result.get("text", "")[:max_length]
                return {
                    "success": True,
                    "url": url,
                    "title": result.get("title", ""),
                    "content": text,
                    "length": len(text),
                    "truncated": len(result.get("text", "")) > max_length
                }
            else:
                return result
        else:
            return {
                "success": True,
                "url": url,
                "html": html[:max_length],
                "length": len(html),
                "truncated": len(html) > max_length
            }

    except asyncio.TimeoutError:
        return {"success": False, "error": "Zaman aşımı - sayfa yanıt vermedi"}
    except Exception as e:
        logger.error(f"Fetch error: {e}")
        return {"success": False, "error": str(e)}


async def extract_text(html: str, url: str = "") -> dict[str, Any]:
    """Extract main text content from HTML

    Args:
        html: HTML content
        url: Source URL (for context)
    """
    try:
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return {"success": False, "error": "beautifulsoup4 kurulu değil. 'pip install beautifulsoup4' çalıştırın."}

        soup = BeautifulSoup(html, "html.parser")

        # Get title
        title = ""
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text().strip()

        # Remove unwanted elements
        for element in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "form", "iframe"]):
            element.decompose()

        # Try to find main content
        main_content = None

        # Look for common content containers
        for selector in ["article", "main", ".content", ".post", ".article", "#content", "#main"]:
            if selector.startswith(".") or selector.startswith("#"):
                main_content = soup.select_one(selector)
            else:
                main_content = soup.find(selector)
            if main_content:
                break

        # Fallback to body
        if not main_content:
            main_content = soup.find("body") or soup

        # Extract text
        text = main_content.get_text(separator="\n", strip=True)

        # Clean up whitespace
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)

        logger.info(f"Extracted {len(text)} chars from {url}")

        return {
            "success": True,
            "title": title,
            "text": text,
            "url": url
        }

    except Exception as e:
        logger.error(f"Extract error: {e}")
        return {"success": False, "error": str(e)}
