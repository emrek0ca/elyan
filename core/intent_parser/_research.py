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
        # Remove common command/noise fragments to keep topic semantic.
        topic = re.sub(
            r"\b(aç|ac|başlat|baslat|çalıştır|calistir|open|launch|safari|chrome|tarayıcı|tarayici|browser)\b",
            " ",
            topic,
            flags=re.IGNORECASE,
        )
        topic = re.sub(
            r"\b(kaydet|yaz|oluştur|olustur|dosya|belge|word|excel|tablo|içine|icine)\b",
            " ",
            topic,
            flags=re.IGNORECASE,
        )
        topic = re.sub(r"\b(kopyala|copy|clipboard|pano|panoya)\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\s+", " ", topic).strip(" .,:;-")
        if not topic or len(topic) < 2:
            return None
        depth = "standard"
        if any(w in text for w in ["detaylı", "kapsamlı", "derin", "derinlemesine"]):
            depth = "deep"
        elif any(w in text for w in ["kısa", "hızlı", "özet"]):
            depth = "quick"

        params = {"topic": topic, "depth": depth}
        if any(k in text for k in ["akademik", "bilimsel", "hakemli", "makale", "journal", "paper"]):
            params["source_policy"] = "academic"
            params["min_reliability"] = 0.72
        elif any(
            k in text
            for k in [
                "official",
                "devlet",
                "bakanlık",
                "bakanlik",
                ".gov",
                "resmi kaynak",
                "resmi site",
                "resmi kurum",
                "resmi veri",
            ]
        ):
            params["source_policy"] = "official"
            params["min_reliability"] = 0.75
        elif any(k in text for k in ["güvenilir", "guvenilir", "trusted", "doğrulanmış", "dogrulanmis"]):
            params["source_policy"] = "trusted"
            params["min_reliability"] = 0.65

        m = re.search(r"%\s*(\d{1,3})", text)
        if not m:
            m = re.search(r"\b(\d{1,3})\s*%\b", text)
        if m:
            try:
                params["min_reliability"] = max(0.0, min(1.0, int(m.group(1)) / 100.0))
            except Exception:
                pass

        doc_markers = [
            "rapor", "belge", "dokuman", "doküman", "word", "docx", "excel", "xlsx", "tablo", "dosya",
        ]
        deliver_markers = [
            "gönder", "gonder", "kopya", "ilet", "paylaş", "paylas", "telegram", "whatsapp", "telefon",
        ]
        simple_answer_markers = [
            "kısaca", "kisaca", "kısa anlat", "kisa anlat", "sadece anlat", "özetle", "ozetle",
        ]
        wants_delivery = any(k in text for k in doc_markers) or not any(k in text for k in simple_answer_markers)
        if wants_delivery:
            depth_for_delivery = {
                "quick": "quick",
                "standard": "standard",
                "deep": "comprehensive",
            }.get(depth, "comprehensive")
            include_word = any(k in text for k in ["rapor", "belge", "word", "docx", "dokuman", "doküman"])
            include_excel = any(k in text for k in ["excel", "xlsx", "tablo", "csv"])
            if not include_word and not include_excel:
                include_word = True
                include_excel = True
            return {
                "action": "research_document_delivery",
                "params": {
                    "topic": topic,
                    "brief": original or text,
                    "depth": depth_for_delivery,
                    "language": "tr",
                    "include_word": include_word,
                    "include_excel": include_excel,
                    "include_report": True,
                    "deliver_copy": any(k in text for k in deliver_markers),
                    "source_policy": params.get("source_policy", "trusted"),
                    "min_reliability": params.get("min_reliability", 0.62),
                },
                "reply": f"'{topic}' için araştırma ve belge paketi hazırlanıyor...",
            }

        return {"action": "research", "params": params,
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
        command_patterns = [
            r"\bözetle\b",
            r"\bozetle\b",
            r"\bsummarize\b",
            r"\bsummary\b",
            r"\bkısalt\b",
            r"\bkisalt\b",
            r"\bana noktalar\b",
            r"\bkey points\b",
            r"\bözet çıkar\b",
            r"\bozet cikar\b",
        ]
        if not any(re.search(pat, text, re.IGNORECASE) for pat in command_patterns):
            return None
        # Avoid false positives in document creation prompts like
        # "word belgesi oluştur ... satış özeti yaz".
        if any(k in text for k in ["word", "excel", "belge", "dosya", "oluştur", "olustur", "kaydet"]):
            if not any(k in text for k in ["özetle", "ozetle", "summarize", "summary"]):
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
