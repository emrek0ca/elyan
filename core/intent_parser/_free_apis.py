"""
_free_apis.py — Ücretsiz API intent parser'ları
Kapsam: Wikipedia, Dictionary, Crypto, Currency, Weather (city), Country, DDG Search, Academic
"""
import re
from ._base import BaseParser


class FreeApiParser(BaseParser):

    # ── Wikipedia / Bilgi ─────────────────────────────────────────────────────
    def _parse_wikipedia(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["vikipedi", "wikipedia", "wiki'de", "vikide", "wiki bilgi", "kim", "kimdir"]
        if not any(t in text for t in triggers):
            return None
        # "X nedir" pattern
        m = re.search(r'(.+?)\s+(?:nedir|ne\s*demek|kimdir|ne\s*anlama?\s*gelir)', text)
        if m:
            topic = m.group(1).strip()
        else:
            topic = text
            for t in triggers:
                topic = topic.replace(t, "")
            topic = re.sub(r'\b(hakkında|hakkinda|bilgi|ver|getir|bul|ara)\b', '', topic).strip()
        if not topic or len(topic) < 2:
            return None
        return {"action": "get_wikipedia_summary", "params": {"topic": topic},
                "reply": f"'{topic}' hakkında bilgi araştırılıyor...", "confidence": 0.88}

    # ── Sözlük / Kelime Tanımı ────────────────────────────────────────────────
    def _parse_dictionary(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["kelime anlamı", "kelime anlami", "sözlük", "sozluk", "tanımı",
                     "tanimi", "definition", "meaning", "anlam", "anlamı ne",
                     "ne anlama gelir", "ne demektir", "ne demek"]
        if not any(t in text for t in triggers):
            return None
        m = re.search(r'["\'](.+?)["\']', text)
        if m:
            word = m.group(1).strip()
        else:
            word = text
            for t in triggers:
                word = word.replace(t, "")
            word = re.sub(r'\b(ne|bu|kelime|şu|kelimenin|sözcüğün|sozcugun)\b', '', word).strip()
        if not word or len(word) < 2:
            return None
        lang = "tr" if any(k in text for k in ["türkçe", "turkce"]) else "en"
        return {"action": "get_word_definition", "params": {"word": word, "lang": lang},
                "reply": f"'{word}' kelimesinin tanımı aranıyor...", "confidence": 0.87}

    # ── Kripto Fiyatı ─────────────────────────────────────────────────────────
    def _parse_crypto(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["bitcoin", "btc", "ethereum", "eth", "kripto", "crypto",
                     "solana", "sol fiyat", "dogecoin", "doge"]
        if not any(t in text for t in triggers):
            return None
        coin_map = {
            "bitcoin": "bitcoin", "btc": "bitcoin",
            "ethereum": "ethereum", "eth": "ethereum",
            "solana": "solana", "sol": "solana",
            "dogecoin": "dogecoin", "doge": "dogecoin",
            "ripple": "ripple", "xrp": "ripple",
            "cardano": "cardano", "ada": "cardano",
        }
        coins = []
        for kw, cid in coin_map.items():
            if kw in text and cid not in coins:
                coins.append(cid)
        if not coins:
            coins = ["bitcoin"]
        vs = "usd"
        if any(k in text for k in ["tl", "türk lirası", "turk lirasi", "try"]):
            vs = "try"
        elif "eur" in text or "euro" in text:
            vs = "eur"
        return {"action": "get_crypto_price",
                "params": {"coin_ids": ",".join(coins), "vs_currency": vs},
                "reply": f"Güncel piyasa verileri kontrol ediliyor...", "confidence": 0.92}

    # ── Döviz Kuru ────────────────────────────────────────────────────────────
    def _parse_exchange_rate(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["döviz", "doviz", "kur", "exchange rate", "dolar kuru",
                     "euro kuru", "currency", "para birimi", "döviz kuru"]
        if not any(t in text for t in triggers):
            return None
        base = "USD"
        if any(k in text for k in ["euro", "eur"]):
            base = "EUR"
        elif any(k in text for k in ["tl", "türk lirası", "try", "lira"]):
            base = "TRY"
        elif any(k in text for k in ["gbp", "sterlin", "pound"]):
            base = "GBP"
        return {"action": "get_exchange_rate", "params": {"base": base},
                "reply": f"{base} bazlı döviz kurları getiriliyor...", "confidence": 0.90}

    # ── Hava Durumu (Şehir) ───────────────────────────────────────────────────
    def _parse_weather_city(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["hava durumu", "hava nasıl", "hava nasil", "weather",
                     "hava sıcaklığı", "hava sicakligi", "derece", "yağmur yağacak mı",
                     "yagmur yagacak mi", "bugün hava", "bugun hava", "yarın hava", "yarin hava"]
        if not any(t in text for t in triggers):
            return None
        city = text
        for t in triggers:
            city = city.replace(t, "")
        city = re.sub(r'\b(ne|nasıl|nasil|kaç|kac|bugün|bugun|yarın|yarin|da|de|ta|te)\b', '', city).strip()
        if not city or len(city) < 2:
            city = "istanbul"
        return {"action": "get_weather_by_city", "params": {"city": city},
                "reply": f"{city.capitalize()} hava durumu getiriliyor...", "confidence": 0.90}

    # ── Ülke Bilgisi ──────────────────────────────────────────────────────────
    def _parse_country_info(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["ülke bilgisi", "ulke bilgisi", "country info", "ülke hakkında",
                     "nüfusu", "nufusu", "başkenti", "baskenti", "bayrağı", "bayragi"]
        if not any(t in text for t in triggers):
            return None
        country = text
        for t in triggers:
            country = country.replace(t, "")
        country = re.sub(r'\b(ne|nedir|kaç|kac|hangi|ülke|ulke)\b', '', country).strip()
        if not country or len(country) < 2:
            return None
        return {"action": "get_country_info", "params": {"country_name": country},
                "reply": f"'{country}' ülke bilgisi getiriliyor...", "confidence": 0.87}

    # ── DuckDuckGo Hızlı Arama ────────────────────────────────────────────────
    def _parse_ddg_search(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["hızlı ara", "hizli ara", "quick search", "ddg",
                     "duckduckgo", "hızlı arama", "hizli arama"]
        if not any(t in text for t in triggers):
            return None
        query = text
        for t in triggers:
            query = query.replace(t, "")
        query = query.strip()
        if not query or len(query) < 2:
            return None
        return {"action": "ddg_instant_answer", "params": {"query": query},
                "reply": f"'{query}' için hızlıca araştırma yapılıyor...", "confidence": 0.85}

    # ── Akademik Arama ────────────────────────────────────────────────────────
    def _parse_academic_search(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["makale ara", "akademik ara", "academic search", "paper search",
                     "bilimsel makale", "scholarly", "crossref", "akademik arama"]
        if not any(t in text for t in triggers):
            return None
        query = text
        for t in triggers:
            query = query.replace(t, "")
        query = query.strip()
        if not query or len(query) < 2:
            return None
        return {"action": "search_academic_papers", "params": {"query": query, "limit": 5},
                "reply": f"'{query}' için akademik kaynaklar taranıyor...", "confidence": 0.87}

    # ── Rastgele Alıntı / Tavsiye / Bilgi ─────────────────────────────────────
    def _parse_random_content(self, text: str, text_norm: str, original: str) -> dict | None:
        if any(k in text for k in ["tavsiye ver", "tavsiye", "advice", "öneri", "oneri"]):
            return {"action": "get_random_advice", "params": {},
                    "reply": "Rastgele bir tavsiye getiriliyor...", "confidence": 0.85}
        if any(k in text for k in ["ilginç bilgi", "ilginc bilgi", "fun fact", "ilginç", "eğlenceli bilgi"]):
            return {"action": "get_random_fact", "params": {},
                    "reply": "Rastgele ilginç bir bilgi getiriliyor...", "confidence": 0.85}
        if any(k in text for k in ["alıntı", "alinti", "quote", "motivasyon", "ilham"]):
            return {"action": "get_random_quote", "params": {},
                    "reply": "Rastgele bir alıntı getiriliyor...", "confidence": 0.85}
        return None
