"""
Playwright browser manager

Handles browser lifecycle, context management, and session persistence.
"""

import asyncio
from typing import Optional, Dict
from datetime import datetime
import time
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("browser_manager")

# Playwright imports (optional)
try:
    from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    async_playwright = None


class BrowserManager:
    """Manages Playwright browser instances"""
    
    def __init__(self, headless: bool = True, timeout: int = 30000):
        """
        Initialize browser manager.
        
        Args:
            headless: Run browser headlessly
            timeout: Default timeout in milliseconds
        """
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright not installed. Run: pip install playwright && playwright install chromium")
            self.playwright = None
            return
        
        self.headless = headless
        self.timeout = timeout
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.session_id: Optional[str] = None
        self.created_at: Optional[float] = None
    
    async def start(self) -> bool:
        """Start Playwright and browser"""
        if not PLAYWRIGHT_AVAILABLE:
            return False
        
        try:
            # Start Playwright
            self.playwright = await async_playwright().start()
            
            # Launch browser (Chromium)
            self.browser = await self.playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox']
            )
            
            # Create context
            self.context = await self.browser.new_context(
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Wiqo/1.0'
            )
            
            # Set default timeout
            self.context.set_default_timeout(self.timeout)
            
            # Create page
            self.page = await self.context.new_page()
            
            self.session_id = f"browser_{int(time.time())}"
            self.created_at = time.time()
            
            logger.info(f"Browser started (headless={self.headless})")
            return True
        
        except Exception as e:
            logger.error(f"Failed to start browser: {e}")
            return False
    
    async def navigate(self, url: str) -> Dict:
        """Navigate to URL"""
        if not self.page:
            return {"success": False, "error": "Browser not started"}
        
        try:
            # Add protocol if missing
            if not url.startswith(('http://', 'https://')):
                url = 'https://' + url
            
            response = await self.page.goto(url, wait_until='domcontentloaded')
            
            title = await self.page.title()
            current_url = self.page.url
            
            logger.info(f"Navigated to: {current_url}")
            
            return {
                "success": True,
                "url": current_url,
                "title": title,
                "status": response.status if response else None
            }
        
        except Exception as e:
            logger.error(f"Navigation error: {e}")
            return {"success": False, "error": str(e)}
    
    async def screenshot(self, path: Optional[str] = None, selector: Optional[str] = None) -> Optional[str]:
        """
        Take screenshot.
        
        Args:
            path: Output file path
            selector: Optional element selector (for element screenshot)
        
        Returns:
            Screenshot file path or None
        """
        if not self.page:
            return None
        
        try:
            if path is None:
                path = f"/tmp/screenshot_{int(time.time())}.png"
            
            # Ensure directory exists
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            
            if selector:
                # Element screenshot
                element = await self.page.query_selector(selector)
                if element:
                    await element.screenshot(path=path)
                else:
                    return None
            else:
                # Full page screenshot
                await self.page.screenshot(path=path, full_page=True)
            
            logger.info(f"Screenshot saved: {path}")
            return path
        
        except Exception as e:
            logger.error(f"Screenshot error: {e}")
            return None
    
    async def close(self):
        """Close browser and cleanup"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            logger.info("Browser closed")
        
        except Exception as e:
            logger.error(f"Close error: {e}")
    
    def is_ready(self) -> bool:
        """Check if browser is ready"""
        return PLAYWRIGHT_AVAILABLE and self.page is not None
    
    async def get_current_url(self) -> Optional[str]:
        """Get current page URL"""
        if self.page:
            return self.page.url
        return None
    
    async def get_title(self) -> Optional[str]:
        """Get current page title"""
        if self.page:
            return await self.page.title()
        return None


# Global browser instance (singleton)
_browser_manager: Optional[BrowserManager] = None


async def get_browser_manager(headless: bool = True) -> Optional[BrowserManager]:
    """Get or create browser manager singleton"""
    global _browser_manager
    
    if _browser_manager is None:
        _browser_manager = BrowserManager(headless=headless)
        if not await _browser_manager.start():
            return None
    
    return _browser_manager if _browser_manager.is_ready() else None


async def close_browser_manager():
    """Close global browser manager"""
    global _browser_manager
    
    if _browser_manager:
        await _browser_manager.close()
        _browser_manager = None
