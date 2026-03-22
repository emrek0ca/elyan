"""
Browser Automation Tools

Provides web automation capabilities using Playwright-backed runtime when
available, with HTTP parsing as a lightweight fallback for text extraction.
"""

import asyncio
import httpx
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional, List
from urllib.parse import urljoin, urlparse
from utils.logger import get_logger

logger = get_logger("tools.browser_automation")


class SimpleBrowser:
    """
    Simple browser automation using HTTP requests
    
    For basic web scraping and data extraction
    Uses the browser runtime for screenshots when a live page is available.
    """
    
    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"
            }
        )
        self.current_url: Optional[str] = None
        self.current_html: Optional[str] = None
        self.current_soup: Optional[BeautifulSoup] = None
    
    async def goto(self, url: str) -> Dict[str, Any]:
        """
        Navigate to a URL
        
        Args:
            url: URL to visit
        
        Returns:
            Page information
        """
        logger.info(f"Navigating to: {url}")
        
        try:
            response = await self.client.get(url)
            response.raise_for_status()
            
            self.current_url = str(response.url)
            self.current_html = response.text
            self.current_soup = BeautifulSoup(self.current_html, 'html.parser')
            
            # Extract page info
            title = self.current_soup.title.string if self.current_soup.title else ""
            
            return {
                "success": True,
                "url": self.current_url,
                "status_code": response.status_code,
                "title": title,
                "content_length": len(self.current_html)
            }
        
        except httpx.HTTPError as e:
            return {
                "success": False,
                "error": f"HTTP error: {e}",
                "url": url
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Navigation error: {e}",
                "url": url
            }
    
    async def get_text(self, selector: str = None) -> Dict[str, Any]:
        """
        Get text content from page
        
        Args:
            selector: CSS selector (if None, gets all text)
        
        Returns:
            Text content
        """
        if not self.current_soup:
            return {
                "success": False,
                "error": "No page loaded"
            }
        
        try:
            if selector:
                elements = self.current_soup.select(selector)
                text = "\n".join(el.get_text(strip=True) for el in elements)
            else:
                text = self.current_soup.get_text(strip=True)
            
            return {
                "success": True,
                "text": text,
                "selector": selector,
                "length": len(text)
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Text extraction error: {e}"
            }
    
    async def get_links(self, filter_domain: bool = True) -> Dict[str, Any]:
        """
        Extract all links from current page
        
        Args:
            filter_domain: Only return links from same domain
        
        Returns:
            List of links
        """
        if not self.current_soup:
            return {
                "success": False,
                "error": "No page loaded"
            }
        
        try:
            links = []
            current_domain = urlparse(self.current_url).netloc if self.current_url else ""
            
            for a_tag in self.current_soup.find_all('a', href=True):
                href = a_tag['href']
                absolute_url = urljoin(self.current_url, href)
                link_domain = urlparse(absolute_url).netloc
                
                if filter_domain and current_domain and link_domain != current_domain:
                    continue
                
                links.append({
                    "url": absolute_url,
                    "text": a_tag.get_text(strip=True),
                    "title": a_tag.get('title', '')
                })
            
            return {
                "success": True,
                "links": links,
                "count": len(links),
                "filtered": filter_domain
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Link extraction error: {e}"
            }
    
    async def extract_data(self, selectors: Dict[str, str]) -> Dict[str, Any]:
        """
        Extract structured data from page
        
        Args:
            selectors: Dict of field_name -> CSS selector
        
        Returns:
            Extracted data
        """
        if not self.current_soup:
            return {
                "success": False,
                "error": "No page loaded"
            }
        
        try:
            data = {}
            
            for field, selector in selectors.items():
                elements = self.current_soup.select(selector)
                if elements:
                    if len(elements) == 1:
                        data[field] = elements[0].get_text(strip=True)
                    else:
                        data[field] = [el.get_text(strip=True) for el in elements]
                else:
                    data[field] = None
            
            return {
                "success": True,
                "data": data,
                "fields_extracted": len([v for v in data.values() if v is not None])
            }
        
        except Exception as e:
            return {
                "success": False,
                "error": f"Data extraction error: {e}"
            }
    
    async def screenshot(self, file_path: str) -> Dict[str, Any]:
        """
        Take a screenshot of the current page using the browser runtime.
        
        Args:
            file_path: Where to save screenshot
        
        Returns:
            Result
        """
        target_url = str(self.current_url or "").strip()
        if not target_url:
            return {
                "success": False,
                "error": "No page loaded",
                "suggestion": "Call goto(url) first before requesting a screenshot.",
            }
        try:
            from core.capabilities.browser import run_browser_runtime

            result = await run_browser_runtime(action="open", url=target_url, screenshot=True)
            screenshots = [str(path).strip() for path in list(result.get("screenshots") or []) if str(path).strip()]
            if file_path and screenshots:
                from pathlib import Path
                import shutil

                target = Path(file_path).expanduser().resolve()
                target.parent.mkdir(parents=True, exist_ok=True)
                source = Path(screenshots[-1]).expanduser().resolve()
                if source != target:
                    shutil.copyfile(source, target)
                else:
                    target = source
                result = dict(result)
                result["screenshot_path"] = str(target)
                result["screenshots"] = [str(target)]
            return result
        except Exception as e:
            return {
                "success": False,
                "error": f"Screenshot error: {e}",
            }
    
    async def close(self):
        """Close the browser client"""
        await self.client.aclose()


# Tool functions

async def browse_url(url: str) -> Dict[str, Any]:
    """
    Browse to a URL and get page information
    
    Args:
        url: URL to visit
    
    Returns:
        Page information
    """
    browser = SimpleBrowser()
    try:
        result = await browser.goto(url)
        
        if result["success"]:
            # Also get page text preview
            text_result = await browser.get_text()
            if text_result["success"]:
                # Get first 500 chars as preview
                result["text_preview"] = text_result["text"][:500]
        
        return result
    finally:
        await browser.close()


async def extract_webpage_text(url: str, selector: str = None) -> Dict[str, Any]:
    """
    Extract text from a webpage
    
    Args:
        url: URL to scrape
        selector: Optional CSS selector
    
    Returns:
        Extracted text
    """
    browser = SimpleBrowser()
    try:
        nav_result = await browser.goto(url)
        if not nav_result["success"]:
            return nav_result
        
        text_result = await browser.get_text(selector)
        text_result["url"] = url
        return text_result
    finally:
        await browser.close()


async def extract_webpage_links(url: str, same_domain_only: bool = True) -> Dict[str, Any]:
    """
    Extract all links from a webpage
    
    Args:
        url: URL to scrape
        same_domain_only: Only return links from same domain
    
    Returns:
        List of links
    """
    browser = SimpleBrowser()
    try:
        nav_result = await browser.goto(url)
        if not nav_result["success"]:
            return nav_result
        
        links_result = await browser.get_links(filter_domain=same_domain_only)
        links_result["source_url"] = url
        return links_result
    finally:
        await browser.close()


async def scrape_structured_data(url: str, selectors: Dict[str, str]) -> Dict[str, Any]:
    """
    Scrape structured data from a webpage
    
    Args:
        url: URL to scrape
        selectors: Dict mapping field names to CSS selectors
    
    Returns:
        Extracted structured data
    """
    browser = SimpleBrowser()
    try:
        nav_result = await browser.goto(url)
        if not nav_result["success"]:
            return nav_result
        
        data_result = await browser.extract_data(selectors)
        data_result["url"] = url
        return data_result
    finally:
        await browser.close()


async def download_webpage(url: str, output_path: str) -> Dict[str, Any]:
    """
    Download a webpage's HTML content
    
    Args:
        url: URL to download
        output_path: Where to save the HTML
    
    Returns:
        Download result
    """
    from pathlib import Path
    
    browser = SimpleBrowser()
    try:
        nav_result = await browser.goto(url)
        if not nav_result["success"]:
            return nav_result
        
        # Save HTML
        output = Path(output_path).expanduser()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(browser.current_html, encoding='utf-8')
        
        return {
            "success": True,
            "url": url,
            "file": str(output),
            "size": len(browser.current_html)
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Download error: {e}"
        }
    finally:
        await browser.close()
