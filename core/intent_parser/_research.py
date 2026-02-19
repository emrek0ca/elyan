"""
_research.py — Araştırma ve web içerik parser'ları
Kapsam: research, web_search, summarize, translate
"""
import re
from ._base import (BaseParser, _RE_RESEARCH_TOPICS, _RE_RESEARCH_CLEAN1,
                    _RE_RESEARCH_CLEAN2, _RE_RESEARCH_CLEAN3, _RE_RESEARCH_CLEAN4)


class ResearchParser(BaseParser):

    # ── Research ──────────────────────────────────────────────────────────────
    def _parse_research(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["araştırma", "araştır", "arastirma", "arastir", "research",
                    "inceleme", "incele", "hakkında bilgi", "hakkında araştır",
                    "araştırma yap", "arastirma yap", "inceleme yap"]
        if not any(t in text for t in triggers):
            return None
        topic = None
        for pat in _RE_RESEARCH_TOPICS:
            m = pat.search(text)
            if m:
                topic = m.group(1).strip()
                break
        if not topic:
            topic = _RE_RESEARCH_CLEAN1.sub("", text)
            topic = _RE_RESEARCH_CLEAN2.sub(" ", topic)
            topic = _RE_RESEARCH_CLEAN3.sub("", topic)
            topic = _RE_RESEARCH_CLEAN4.sub("", topic).strip()
        if not topic or len(topic) < 2:
            return None
        depth = "standard"
        if any(w in text for w in ["detaylı", "kapsamlı", "derin", "derinlemesine"]):
            depth = "deep"
        elif any(w in text for w in ["kısa", "hızlı", "özet"]):
            depth = "quick"
        return {"action": "research", "params": {"topic": topic, "depth": depth},
                "reply": f"'{topic}' hakkında araştırma yapılıyor..."}

    # ── Web Search ────────────────────────────────────────────────────────────
    def _parse_web_search(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["internette ara", "web'de ara", "webde ara", "google'da ara",
                    "googla", "google ara", "internette bul", "web search",
                    "internette araştır", "online ara"]
        if not any(t in text for t in triggers):
            return None
        query = ""
        for t in triggers:
            if t in text:
                parts = text.split(t)
                if len(parts) > 1:
                    query = parts[-1].strip()
                    break
        if not query:
            m = re.search(r'(?:ara|bul|araştır)\s+(.+)', text, re.IGNORECASE)
            if m:
                query = m.group(1).strip()
        if not query:
            return None
        return {"action": "web_search", "params": {"query": query},
                "reply": f"'{query}' internette aranıyor..."}

    # ── Summarize ─────────────────────────────────────────────────────────────
    def _parse_summarize(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["özetle", "ozetle", "özet", "ozet", "summarize", "summary",
                    "kısalt", "kisalt", "ana noktalar", "key points"]
        if not any(t in text for t in triggers):
            return None
        m = re.search(r'(https?://[^\s]+|www\.[^\s]+)', text)
        if m:
            url = m.group()
            if not url.startswith("http"):
                url = "https://" + url
            return {"action": "summarize_url", "params": {"url": url},
                    "reply": "URL içeriği özetleniyor..."}
        fm = re.search(r'[\w\-]+\.\w+', text)
        if fm:
            return {"action": "summarize_file", "params": {"path": fm.group()},
                    "reply": "Dosya içeriği özetleniyor..."}
        return {"action": "summarize_text", "params": {"text": text},
                "reply": "Metin özetleniyor..."}

    # ── Translate ─────────────────────────────────────────────────────────────
    def _parse_translate(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["çevir", "cevir", "translate", "tercüme", "tercume",
                    "ingilizceye çevir", "türkçeye çevir", "çeviri yap"]
        if not any(t in text for t in triggers):
            return None
        lang_map = {
            "ingilizce": "en", "english": "en", "türkçe": "tr", "turkish": "tr",
            "almanca": "de", "german": "de", "fransızca": "fr", "french": "fr",
            "ispanyolca": "es", "spanish": "es", "italyanca": "it", "italian": "it",
            "japonca": "ja", "japanese": "ja", "çince": "zh", "chinese": "zh",
            "rusça": "ru", "russian": "ru", "arapça": "ar", "arabic": "ar",
        }
        target_lang = "en"
        for lang_name, code in lang_map.items():
            if lang_name in text:
                target_lang = code
                break
        content = text
        for t in triggers:
            content = content.replace(t, "")
        for lang_name in lang_map:
            content = content.replace(lang_name, "")
        content = re.sub(r'\b(ye|e|a|ya|dan|den|na|ne)\b', "", content).strip()
        if not content:
            return None
        return {"action": "translate", "params": {"text": content, "target_lang": target_lang},
                "reply": f"Metin {target_lang.upper()} diline çevriliyor..."}
