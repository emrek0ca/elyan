import asyncio
from playwright.async_api import async_playwright
from typing import Dict, Any, Optional
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("cdp_client")

class CDPClient:
    """Advanced browser automation using CDP and Playwright."""
    
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None

    async def start(self, profile_path: Optional[str] = None):
        """Start browser with optional persistent profile."""
        self.playwright = await async_playwright().start()
        
        if profile_path:
            logger.info(f"Starting browser with profile: {profile_path}")
            self.context = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=profile_path,
                headless=True,
                args=["--remote-debugging-port=9222"]
            )
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        else:
            self.browser = await self.playwright.chromium.launch(headless=True)
            self.context = await self.browser.new_context()
            self.page = await self.context.new_page()
            
        logger.info("Browser automation ready.")

    async def navigate(self, url: str):
        await self.page.goto(url, wait_until="networkidle")
        return f"Navigated to {url}"

    async def screenshot(self, path: str):
        await self.page.screenshot(path=path, full_page=True)
        return f"Screenshot saved to {path}"

    async def click(self, selector: str):
        await self.page.click(selector)
        return f"Clicked {selector}"

    async def type(self, selector: str, text: str):
        await self.page.fill(selector, text)
        return f"Typed in {selector}"

    async def extract_text(self) -> str:
        return await self.page.content()

    async def stop(self):
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser stopped.")

# Global dynamic instance helper
async def get_browser_session(profile_id: str = "default"):
    client = CDPClient()
    profile_path = Path.home() / ".elyan" / "browser" / "profiles" / profile_id
    profile_path.mkdir(parents=True, exist_ok=True)
    await client.start(str(profile_path))
    return client
