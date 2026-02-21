"""
Browser automation types and constants
"""

from typing import TypedDict, Optional, Literal
from dataclasses import dataclass


BrowserType = Literal["chromium", "firefox", "webkit"]
ScreenshotFormat = Literal["png", "jpeg"]


class BrowserConfig(TypedDict, total=False):
    """Browser configuration"""
    headless: bool
    timeout: int
    viewport_width: int
    viewport_height: int
    user_agent: Optional[str]


class PageResult(TypedDict):
    """Page interaction result"""
    success: bool
    url: str
    title: str
    screenshot_path: Optional[str]
    error: Optional[str]


class ScrapeResult(TypedDict):
    """Scraping result"""
    success: bool
    data: dict
    error: Optional[str]


@dataclass
class BrowserSession:
    """Browser session info"""
    session_id: str
    url: str
    title: str
    created_at: float
    last_used: float
    headless: bool
