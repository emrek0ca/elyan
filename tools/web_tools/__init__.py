from .web_scraper import fetch_page, extract_text
from .search_engine import web_search
from .background_research import start_research, get_research_status

__all__ = [
    "fetch_page", "extract_text",
    "web_search",
    "start_research", "get_research_status"
]
