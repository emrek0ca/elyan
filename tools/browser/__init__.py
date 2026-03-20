"""
Browser automation module
"""

from .manager import (
    BrowserManager,
    get_browser_manager,
    close_browser_manager,
    PLAYWRIGHT_AVAILABLE,
    is_playwright_available,
)

from .automation import (
    browser_open,
    browser_click,
    browser_type,
    browser_screenshot,
    browser_get_text,
    browser_scroll,
    browser_wait,
    browser_close,
    browser_status
)

from .scraper import (
    scrape_page,
    scrape_links,
    scrape_table
)

__all__ = [
    # Manager
    'BrowserManager',
    'get_browser_manager',
    'close_browser_manager',
    'PLAYWRIGHT_AVAILABLE',
    'is_playwright_available',
    
    # Automation
    'browser_open',
    'browser_click',
    'browser_type',
    'browser_screenshot',
    'browser_get_text',
    'browser_scroll',
    'browser_wait',
    'browser_close',
    'browser_status',
    
    # Scraping
    'scrape_page',
    'scrape_links',
    'scrape_table',
]
