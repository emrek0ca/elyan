"""
Browser automation tools

Provides browser control capabilities: click, type, scroll, extract text, etc.
"""

from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from .manager import get_browser_manager

logger = get_logger("browser_automation")


async def browser_open(url: str, headless: bool = True) -> Dict[str, Any]:
    """
    Open URL in browser.
    
    Args:
        url: URL to open
        headless: Run headlessly
    
    Returns:
        {"success": bool, "url": str, "title": str}
    """
    try:
        browser = await get_browser_manager(headless=headless)
        
        if not browser:
            return {"success": False, "error": "Browser not available"}
        
        result = await browser.navigate(url)
        return result
    
    except Exception as e:
        logger.error(f"browser_open error: {e}")
        return {"success": False, "error": str(e)}


async def browser_click(selector: str) -> Dict[str, Any]:
    """
    Click element by CSS selector.
    
    Args:
        selector: CSS selector
    
    Returns:
        {"success": bool, "clicked": bool}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser or not browser.page:
            return {"success": False, "error": "Browser not ready"}
        
        # Wait for element
        await browser.page.wait_for_selector(selector, timeout=5000)
        
        # Click
        await browser.page.click(selector)
        
        logger.info(f"Clicked: {selector}")
        return {"success": True, "clicked": True}
    
    except Exception as e:
        logger.error(f"browser_click error: {e}")
        return {"success": False, "error": str(e)}


async def browser_type(selector: str, text: str) -> Dict[str, Any]:
    """
    Type text into element.
    
    Args:
        selector: CSS selector
        text: Text to type
    
    Returns:
        {"success": bool}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser or not browser.page:
            return {"success": False, "error": "Browser not ready"}
        
        # Wait for element
        await browser.page.wait_for_selector(selector, timeout=5000)
        
        # Type
        await browser.page.fill(selector, text)
        
        logger.info(f"Typed into {selector}: {text[:20]}...")
        return {"success": True}
    
    except Exception as e:
        logger.error(f"browser_type error: {e}")
        return {"success": False, "error": str(e)}


async def browser_screenshot(selector: Optional[str] = None) -> Optional[str]:
    """
    Take screenshot.
    
    Args:
        selector: Optional element selector
    
    Returns:
        Screenshot file path or None
    """
    try:
        browser = await get_browser_manager()
        
        if not browser:
            return None
        
        path = await browser.screenshot(selector=selector)
        return path
    
    except Exception as e:
        logger.error(f"browser_screenshot error: {e}")
        return None


async def browser_get_text(selector: str) -> Optional[str]:
    """
    Extract text from element.
    
    Args:
        selector: CSS selector
    
    Returns:
        Element text or None
    """
    try:
        browser = await get_browser_manager()
        
        if not browser or not browser.page:
            return None
        
        # Wait for element
        await browser.page.wait_for_selector(selector, timeout=5000)
        
        # Get text
        text = await browser.page.text_content(selector)
        
        logger.info(f"Extracted text from {selector}: {len(text) if text else 0} chars")
        return text
    
    except Exception as e:
        logger.error(f"browser_get_text error: {e}")
        return None


async def browser_scroll(direction: str = "down", amount: int = 500) -> Dict[str, Any]:
    """
    Scroll page.
    
    Args:
        direction: "down", "up", "left", "right"
        amount: Scroll amount in pixels
    
    Returns:
        {"success": bool}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser or not browser.page:
            return {"success": False, "error": "Browser not ready"}
        
        # Scroll
        if direction == "down":
            await browser.page.evaluate(f"window.scrollBy(0, {amount})")
        elif direction == "up":
            await browser.page.evaluate(f"window.scrollBy(0, -{amount})")
        elif direction == "right":
            await browser.page.evaluate(f"window.scrollBy({amount}, 0)")
        elif direction == "left":
            await browser.page.evaluate(f"window.scrollBy(-{amount}, 0)")
        
        logger.info(f"Scrolled {direction} by {amount}px")
        return {"success": True}
    
    except Exception as e:
        logger.error(f"browser_scroll error: {e}")
        return {"success": False, "error": str(e)}


async def browser_wait(selector: str, timeout: int = 10000) -> Dict[str, Any]:
    """
    Wait for element to appear.
    
    Args:
        selector: CSS selector
        timeout: Timeout in milliseconds
    
    Returns:
        {"success": bool, "found": bool}
    """
    try:
        browser = await get_browser_manager()
        
        if not browser or not browser.page:
            return {"success": False, "error": "Browser not ready"}
        
        await browser.page.wait_for_selector(selector, timeout=timeout)
        
        logger.info(f"Element found: {selector}")
        return {"success": True, "found": True}
    
    except Exception as e:
        logger.error(f"browser_wait error: {e}")
        return {"success": False, "found": False, "error": str(e)}


async def browser_close() -> Dict[str, Any]:
    """Close browser"""
    try:
        from .manager import close_browser_manager
        await close_browser_manager()
        
        logger.info("Browser closed")
        return {"success": True}
    
    except Exception as e:
        logger.error(f"browser_close error: {e}")
        return {"success": False, "error": str(e)}


async def browser_status() -> Dict[str, Any]:
    """Get browser status"""
    try:
        browser = await get_browser_manager()
        
        if not browser or not browser.page:
            return {
                "success": True,
                "running": False,
                "url": None,
                "title": None
            }
        
        url = await browser.get_current_url()
        title = await browser.get_title()
        
        return {
            "success": True,
            "running": True,
            "url": url,
            "title": title,
            "session_id": browser.session_id,
            "headless": browser.headless
        }
    
    except Exception as e:
        logger.error(f"browser_status error: {e}")
        return {"success": False, "error": str(e)}
