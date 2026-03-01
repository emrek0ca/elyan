"""
tools/free_apis/free_search_apis.py
─────────────────────────────────────────────────────────────────────────────
Free Search & Discovery APIs — Zero cost, no API key required.
DuckDuckGo Instant Answer, Crossref Academic Search.
"""

import httpx
from utils.logger import get_logger

logger = get_logger("free_search_apis")

TIMEOUT = 10


async def ddg_instant_answer(query: str) -> dict:
    """
    DuckDuckGo Instant Answer API ile hızlı arama yapar.
    Parametreler: query (str) — Arama sorgusu.
    """
    try:
        url = "https://api.duckduckgo.com/"
        params = {"q": query, "format": "json", "no_redirect": "1", "no_html": "1"}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params)
            if resp.status_code not in (200, 202):
                return {"success": False, "error": f"DuckDuckGo hatası: {resp.status_code}"}
            
            data = resp.json()
            
            # Primary answer
            abstract = data.get("Abstract", "")
            abstract_url = data.get("AbstractURL", "")
            answer = data.get("Answer", "")
            definition = data.get("Definition", "")
            
            # Related topics
            related = []
            for topic in data.get("RelatedTopics", [])[:5]:
                if isinstance(topic, dict) and "Text" in topic:
                    related.append({
                        "text": topic.get("Text", "")[:200],
                        "url": topic.get("FirstURL", ""),
                    })
            
            # Build best result
            best_answer = answer or abstract or definition or ""
            
            return {
                "success": True,
                "query": query,
                "answer": best_answer,
                "source": data.get("AbstractSource", ""),
                "url": abstract_url or data.get("DefinitionURL", ""),
                "type": data.get("Type", ""),
                "related": related,
                "image": data.get("Image", ""),
            }
    except Exception as e:
        logger.error(f"DuckDuckGo API error: {e}")
        return {"success": False, "error": str(e)}


async def search_academic_papers(query: str, limit: int = 5) -> dict:
    """
    Crossref üzerinden akademik makale/araştırma arar.
    Parametreler: query (str), limit (int, varsayılan: 5).
    """
    try:
        url = "https://api.crossref.org/works"
        params = {"query": query, "rows": min(limit, 10), "select": "title,author,DOI,published-print,container-title,URL"}
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params=params, headers={"User-Agent": "Elyan/1.0 (AI Agent)"})
            if resp.status_code != 200:
                return {"success": False, "error": f"Crossref hatası: {resp.status_code}"}
            
            data = resp.json()
            items = data.get("message", {}).get("items", [])
            
            papers = []
            for item in items:
                title = item.get("title", [""])[0] if item.get("title") else ""
                authors = []
                for a in item.get("author", [])[:3]:
                    name = f"{a.get('given', '')} {a.get('family', '')}".strip()
                    if name:
                        authors.append(name)
                
                published = item.get("published-print", {})
                date_parts = published.get("date-parts", [[]])[0] if published else []
                year = date_parts[0] if date_parts else ""
                
                papers.append({
                    "title": title,
                    "authors": authors,
                    "year": year,
                    "journal": item.get("container-title", [""])[0] if item.get("container-title") else "",
                    "doi": item.get("DOI", ""),
                    "url": item.get("URL", ""),
                })
            
            return {
                "success": True,
                "query": query,
                "total_results": data.get("message", {}).get("total-results", 0),
                "papers": papers,
            }
    except Exception as e:
        logger.error(f"Crossref API error: {e}")
        return {"success": False, "error": str(e)}
