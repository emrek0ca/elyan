from .web_scraper import fetch_page, extract_text
from .search_engine import web_search
from .background_research import start_research, get_research_status
from .smart_fetch import close_smart_fetch_browser, smart_fetch_html, smart_fetch_page

__all__ = [
    "fetch_page", "extract_text",
    "web_search",
    "start_research", "get_research_status",
    "smart_fetch_html", "smart_fetch_page", "close_smart_fetch_browser",
]
