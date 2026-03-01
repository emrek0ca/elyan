"""
tools/free_apis/free_knowledge_apis.py
─────────────────────────────────────────────────────────────────────────────
Free Knowledge & Language APIs — Zero cost, no API key required.
Wikipedia, Free Dictionary, Advice Slip, Useless Facts, Quotable.
"""

import httpx
from utils.logger import get_logger

logger = get_logger("free_knowledge_apis")

TIMEOUT = 8


async def get_wikipedia_summary(topic: str) -> dict:
    """
    Wikipedia'dan bir konu hakkında özet bilgi getirir.
    Parametreler: topic (str) — Aranacak konu.
    """
    try:
        from urllib.parse import quote
        encoded_topic = quote(topic.replace(' ', '_'), safe='/_')
        url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{encoded_topic}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, headers={"User-Agent": "Elyan/1.0"})
            if resp.status_code == 404:
                # Try Turkish Wikipedia
                url_tr = f"https://tr.wikipedia.org/api/rest_v1/page/summary/{encoded_topic}"
                resp = await client.get(url_tr, headers={"User-Agent": "Elyan/1.0"})
            
            if resp.status_code != 200:
                return {"success": False, "error": f"Bilgi bulunamadı: {topic}", "not_found": True}
            
            data = resp.json()
            return {
                "success": True,
                "title": data.get("title", ""),
                "summary": data.get("extract", ""),
                "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                "thumbnail": data.get("thumbnail", {}).get("source", ""),
            }
    except Exception as e:
        logger.error(f"Wikipedia API error: {e}")
        return {"success": False, "error": str(e)}


async def get_word_definition(word: str, lang: str = "en") -> dict:
    """
    Bir kelimenin tanımını, telaffuzunu ve eş anlamlılarını getirir.
    Parametreler: word (str), lang (str, varsayılan: 'en').
    """
    try:
        url = f"https://api.dictionaryapi.dev/api/v2/entries/{lang}/{word}"
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url)
            if resp.status_code != 200:
                return {"success": False, "error": f"Tanım bulunamadı: {word}", "not_found": True}
            
            data = resp.json()
            entry = data[0] if data else {}
            meanings = []
            for m in entry.get("meanings", []):
                for d in m.get("definitions", [])[:2]:
                    meanings.append({
                        "part_of_speech": m.get("partOfSpeech", ""),
                        "definition": d.get("definition", ""),
                        "example": d.get("example", ""),
                        "synonyms": d.get("synonyms", [])[:5],
                    })
            
            phonetics = [p.get("text", "") for p in entry.get("phonetics", []) if p.get("text")]
            
            return {
                "success": True,
                "word": entry.get("word", word),
                "phonetics": phonetics,
                "meanings": meanings,
            }
    except Exception as e:
        logger.error(f"Dictionary API error: {e}")
        return {"success": False, "error": str(e)}


async def get_random_advice() -> dict:
    """Rastgele bir hayat tavsiyesi getirir. Parametre gerekmez."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get("https://api.adviceslip.com/advice")
            data = resp.json()
            slip = data.get("slip", {})
            return {"success": True, "advice": slip.get("advice", ""), "id": slip.get("id", 0)}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_random_fact() -> dict:
    """Rastgele ilginç bir bilgi getirir. Parametre gerekmez."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                "https://uselessfacts.jsph.pl/api/v2/facts/random",
                headers={"Accept": "application/json"}
            )
            data = resp.json()
            return {"success": True, "fact": data.get("text", ""), "source": data.get("source", "")}
    except Exception as e:
        return {"success": False, "error": str(e)}


async def get_random_quote() -> dict:
    """Rastgele bir motivasyon alıntısı getirir. Parametre gerekmez."""
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get("https://api.quotable.io/quotes/random")
            data = resp.json()
            if isinstance(data, list) and data:
                q = data[0]
                return {"success": True, "quote": q.get("content", ""), "author": q.get("author", "")}
            return {"success": False, "error": "Alıntı bulunamadı"}
    except Exception as e:
        return {"success": False, "error": str(e)}
