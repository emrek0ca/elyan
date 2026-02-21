"""
Web scraping utilities
"""

from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from .manager import get_browser_manager

logger = get_logger("browser_scraper")

try:
    from bs4 import BeautifulSoup
    BS4_AVAILABLE = True
except ImportError:
    BS4_AVAILABLE = False


async def scrape_page(url: str, selectors: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Scrape page content.
    
    Args:
        url: URL to scrape
        selectors: Optional list of CSS selectors to extract
    
    Returns:
        {"success": bool, "data": dict}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser:
            return {"success": False, "error": "Browser not available"}
        
        # Navigate
        nav_result = await browser.navigate(url)
        if not nav_result.get("success"):
            return nav_result
        
        # Get page content
        content = await browser.page.content()
        
        data = {
            "url": nav_result["url"],
            "title": nav_result["title"]
        }
        
        # Extract specific selectors or full text
        if selectors:
            for selector in selectors:
                text = await browser.page.text_content(selector)
                data[selector] = text
        else:
            # Extract all text
            text = await browser.page.evaluate("() => document.body.innerText")
            data["text"] = text
        
        logger.info(f"Scraped {url}: {len(selectors or [])} selectors")
        return {"success": True, "data": data}
    
    except Exception as e:
        logger.error(f"scrape_page error: {e}")
        return {"success": False, "error": str(e)}


async def scrape_links(url: str, pattern: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract all links from page.
    
    Args:
        url: URL to scrape
        pattern: Optional URL pattern filter
    
    Returns:
        {"success": bool, "links": list}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser:
            return {"success": False, "error": "Browser not available"}
        
        # Navigate
        await browser.navigate(url)
        
        # Extract links
        links = await browser.page.evaluate("""
            () => {
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                return anchors.map(a => ({
                    href: a.href,
                    text: a.innerText.trim()
                }));
            }
        """)
        
        # Filter by pattern if provided
        if pattern:
            links = [link for link in links if pattern in link['href']]
        
        logger.info(f"Extracted {len(links)} links from {url}")
        return {"success": True, "links": links}
    
    except Exception as e:
        logger.error(f"scrape_links error: {e}")
        return {"success": False, "error": str(e)}


async def scrape_table(url: str, table_selector: str = "table") -> Dict[str, Any]:
    """
    Extract table data as JSON.
    
    Args:
        url: URL to scrape
        table_selector: CSS selector for table
    
    Returns:
        {"success": bool, "headers": list, "rows": list}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser:
            return {"success": False, "error": "Browser not available"}
        
        # Navigate
        await browser.navigate(url)
        
        # Extract table
        table_data = await browser.page.evaluate(f"""
            () => {{
                const table = document.querySelector('{table_selector}');
                if (!table) return null;
                
                const headers = Array.from(table.querySelectorAll('th')).map(th => th.innerText.trim());
                const rows = Array.from(table.querySelectorAll('tbody tr')).map(tr => {{
                    return Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim());
                }});
                
                return {{ headers, rows }};
            }}
        """)
        
        if not table_data:
            return {"success": False, "error": "Table not found"}
        
        logger.info(f"Extracted table: {len(table_data['rows'])} rows")
        return {"success": True, **table_data}
    
    except Exception as e:
        logger.error(f"scrape_table error: {e}")
        return {"success": False, "error": str(e)}
