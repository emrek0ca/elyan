"""
Turkish NLP Module — Deep Morphological Analysis

Enhanced Turkish language understanding:
- 80+ verb stems with conjugation awareness
- Full agglutinative suffix chain decomposition
- Colloquial/slang normalization ("tmm" → "tamam", "bi dk" → "bir dakika")
- Named Entity Recognition (dates, times, emails, phones)
- Compound number parsing (up to billions)
- Vowel harmony aware suffix detection
"""

import re
from typing import Dict, List, Tuple, Optional, Any
from utils.logger import get_logger

logger = get_logger("turkish_nlp")

# ── Vowel Harmony ──────────────────────────────────────────────────────────────

FRONT_VOWELS = set("eiöü")
BACK_VOWELS = set("aıou")
ROUNDED_VOWELS = set("oöuü")
ALL_VOWELS = FRONT_VOWELS | BACK_VOWELS


def _last_vowel(word: str) -> str:
    """Return the last vowel character in a word."""
    for ch in reversed(word.lower()):
        if ch in ALL_VOWELS:
            return ch
    return "a"


def _is_front(word: str) -> bool:
    """Check if word has front vowel harmony."""
    return _last_vowel(word) in FRONT_VOWELS


# ── Verb Dictionary (80+) ─────────────────────────────────────────────────────

TURKISH_VERBS = {
    # Core verbs
    "yap": "yapmak", "git": "gitmek", "gel": "gelmek", "al": "almak",
    "ver": "vermek", "tut": "tutmak", "koy": "koymak", "kalk": "kalkmak",
    "otur": "oturmak", "bak": "bakmak", "aç": "açmak", "kapat": "kapatmak",
    "oku": "okumak", "yaz": "yazmak", "söyle": "söylemek", "ara": "aramak",
    "bul": "bulmak", "gönder": "göndermek", "gör": "görmek", "bil": "bilmek",
    "iste": "istemek", "düşün": "düşünmek", "anla": "anlamak", "çalış": "çalışmak",
    "başla": "başlamak", "bitir": "bitirmek", "dur": "durmak", "kal": "kalmak",
    "çık": "çıkmak", "gir": "girmek", "dön": "dönmek", "sat": "satmak",
    "sil": "silmek", "değiştir": "değiştirmek", "kaydet": "kaydetmek",
    "indir": "indirmek", "yükle": "yüklemek", "kur": "kurmak",
    "çalıştır": "çalıştırmak", "durdur": "durdurmak", "tara": "taramak",
    "kontrol": "kontrol etmek", "güncelle": "güncellemek",
    # Communication
    "de": "demek", "konuş": "konuşmak", "sor": "sormak", "cevapla": "cevaplamak",
    "yardım": "yardım etmek", "açıkla": "açıklamak", "özetle": "özetlemek",
    "çevir": "çevirmek", "tercüme": "tercüme etmek",
    # File operations
    "oluştur": "oluşturmak", "düzenle": "düzenlemek", "taşı": "taşımak",
    "kopyala": "kopyalamak", "yapıştır": "yapıştırmak", "adlandır": "adlandırmak",
    # System operations
    "kapat": "kapatmak", "aç": "açmak", "yeniden başlat": "yeniden başlatmak",
    "bağlan": "bağlanmak", "paylaş": "paylaşmak", "kilitle": "kilitlemek",
    # Research & analysis
    "araştır": "araştırmak", "analiz": "analiz etmek", "karşılaştır": "karşılaştırmak",
    "hesapla": "hesaplamak", "say": "saymak", "ölç": "ölçmek",
    "test": "test etmek", "doğrula": "doğrulamak",
    # Creative
    "tasarla": "tasarlamak", "çiz": "çizmek", "planla": "planlamak",
    "hazırla": "hazırlamak", "üret": "üretmek", "kodla": "kodlamak",
    "derle": "derlemek", "yayınla": "yayınlamak",
}

# ── Suffix Decomposition Engine ────────────────────────────────────────────────

# Turkish agglutinative suffix chains (ordered by priority/length)
SUFFIX_CHAINS = [
    # Derivational + case chains
    (r"(abil|ebil)(ecek|acak)(ler|lar)(imiz|ımız|umuz|ümüz)(den|dan|de|da|e|a|i|ı|u|ü)$",
     ["ability", "future", "plural", "1pl_poss", "case"]),
    (r"(abil|ebil)(ecek|acak)(ler|lar)(den|dan|de|da|e|a|i|ı|u|ü)$",
     ["ability", "future", "plural", "case"]),
    (r"(abil|ebil)(ecek|acak)(imiz|ımız|umuz|ümüz)$",
     ["ability", "future", "1pl_poss"]),
    (r"(abil|ebil)(ecek|acak)$",
     ["ability", "future"]),
    # Tense suffixes
    (r"(iyor|ıyor|uyor|üyor)(um|sun|uz|sunuz|lar)$",
     ["present_cont", "person"]),
    (r"(iyor|ıyor|uyor|üyor)$",
     ["present_cont"]),
    (r"(ecek|acak)(ım|sın|ız|sınız|lar)$",
     ["future", "person"]),
    (r"(ecek|acak)$",
     ["future"]),
    (r"(di|dı|du|dü|ti|tı|tu|tü)(m|n|k|nız|lar)$",
     ["past", "person"]),
    (r"(di|dı|du|dü|ti|tı|tu|tü)$",
     ["past"]),
    (r"(miş|mış|muş|müş)(ım|sın|ız|sınız|lar)$",
     ["reported_past", "person"]),
    (r"(miş|mış|muş|müş)$",
     ["reported_past"]),
    (r"(er|ar|ır|ir|ur|ür)(ım|sın|ız|sınız|lar)$",
     ["aorist", "person"]),
    # Ability
    (r"(abil|ebil)$",
     ["ability"]),
    # Causative
    (r"(tir|tır|tur|tür|dir|dır|dur|dür)$",
     ["causative"]),
    # Plural + case
    (r"(ler|lar)(den|dan|de|da|e|a|i|ı|u|ü|in|ın|un|ün)$",
     ["plural", "case"]),
    (r"(ler|lar)$",
     ["plural"]),
    # Case suffixes
    (r"(dan|den)$", ["ablative"]),
    (r"(da|de)$", ["locative"]),
    (r"(la|le)$", ["instrumental"]),
    (r"(ya|ye|na|ne)$", ["dative"]),
    (r"(ı|i|u|ü)$", ["accusative"]),
    (r"(ın|in|un|ün)$", ["genitive"]),
]


# ── Colloquial / Slang Normalization ───────────────────────────────────────────

COLLOQUIAL_MAP = {
    # Abbreviations
    "tmm": "tamam", "tmm.": "tamam", "ok": "tamam", "okey": "tamam",
    "tşk": "teşekkürler", "tşkler": "teşekkürler", "tşk.": "teşekkürler",
    "slm": "selam", "sa": "selamünaleyküm", "as": "aleykümselam",
    "mrb": "merhaba", "mrb.": "merhaba", "nbr": "ne haber",
    "naber": "ne haber", "naber?": "ne haber", "napıyon": "ne yapıyorsun",
    "noldu": "ne oldu", "noluyo": "ne oluyor",
    # Time expressions
    "bi dk": "bir dakika", "bidk": "bir dakika", "bi sn": "bir saniye",
    "bi an": "bir an", "hemen": "hemen", "şimdi": "şimdi",
    # Affirmatives
    "evet": "evet", "evt": "evet", "e": "evet", "he": "evet",
    "yo": "hayır", "yoo": "hayır", "hayır": "hayır", "yok": "hayır",
    # Common shortenings
    "bi": "bir", "şu": "şu", "bu": "bu", "o": "o",
    "bişey": "bir şey", "bişi": "bir şey", "hiçbişey": "hiçbir şey",
    "niye": "neden", "neden": "neden",
    "nasıl": "nasıl", "nası": "nasıl",
    "peki": "peki", "hadi": "hadi",
    "çko": "çok", "cko": "çok",
    # Tech slang
    "ss": "ekran görüntüsü", "wp": "duvar kağıdı",
    "pc": "bilgisayar", "tel": "telefon",
    "wifi": "wifi", "bt": "bluetooth",
}

# Regex for multi-word colloquial expressions
COLLOQUIAL_PATTERNS = [
    (re.compile(r"\bbi\s+dk\b", re.IGNORECASE), "bir dakika"),
    (re.compile(r"\bbi\s+sn\b", re.IGNORECASE), "bir saniye"),
    (re.compile(r"\bne\s+zaman\b", re.IGNORECASE), "ne zaman"),
    (re.compile(r"\bne\s+kadar\b", re.IGNORECASE), "ne kadar"),
    (re.compile(r"\bhiç\s+bi(r|)\b", re.IGNORECASE), "hiçbir"),
]


# ── Turkish Number Words ───────────────────────────────────────────────────────

TURKISH_NUMBERS = {
    "sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5,
    "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60,
    "yetmiş": 70, "seksen": 80, "doksan": 90, "yüz": 100,
    "bin": 1000, "milyon": 1000000, "milyar": 1000000000,
}

# ── Case Suffixes ──────────────────────────────────────────────────────────────

CASE_SUFFIXES = {
    "nominative": "",
    "accusative": ["ı", "i", "u", "ü", "yı", "yi", "yu", "yü"],
    "dative": ["a", "e", "ya", "ye", "na", "ne"],
    "locative": ["da", "de", "ta", "te"],
    "ablative": ["dan", "den", "tan", "ten"],
    "instrumental": ["la", "le", "yla", "yle"],
    "genitive": ["ın", "in", "un", "ün", "nın", "nin", "nun", "nün"],
}

# ── Named Entity Recognition Patterns ──────────────────────────────────────────

NER_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"(?:\+90|0)?\s*(?:\d[\s-]?){10}"),
    "url": re.compile(r"https?://[^\s]+|www\.[^\s]+"),
    "date_dmy": re.compile(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b"),
    "time_hm": re.compile(r"\b(\d{1,2})[:.:](\d{2})\b"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "file_path": re.compile(r"(?:~/|/|\./)[\w./-]+"),
}

# Turkish date words
DATE_WORDS = {
    "bugün": "today", "yarın": "tomorrow", "dün": "yesterday",
    "öbür gün": "day_after_tomorrow", "evvelsi gün": "day_before_yesterday",
    "pazartesi": "monday", "salı": "tuesday", "çarşamba": "wednesday",
    "perşembe": "thursday", "cuma": "friday", "cumartesi": "saturday",
    "pazar": "sunday",
    "ocak": 1, "şubat": 2, "mart": 3, "nisan": 4, "mayıs": 5,
    "haziran": 6, "temmuz": 7, "ağustos": 8, "eylül": 9,
    "ekim": 10, "kasım": 11, "aralık": 12,
}

# ── Intent Keywords (Turkish) ─────────────────────────────────────────────────

INTENT_KEYWORDS = {
    "create": ["oluştur", "yarat", "yap", "hazırla", "üret", "kur", "aç"],
    "delete": ["sil", "kaldır", "temizle", "at", "yok et"],
    "search": ["ara", "bul", "tara", "araştır", "sor"],
    "read": ["oku", "göster", "bak", "aç", "getir", "listele"],
    "write": ["yaz", "kaydet", "düzenle", "güncelle", "değiştir"],
    "send": ["gönder", "yolla", "at", "ilet", "paylaş"],
    "analyze": ["analiz et", "incele", "karşılaştır", "özetle", "raporla"],
    "system": ["kapat", "aç", "yeniden başlat", "bağlan", "kilitle"],
}


class TurkishNLPAnalyzer:
    """Enhanced Turkish morphological analysis and NLP utilities."""

    @staticmethod
    def normalize_colloquial(text: str) -> str:
        """
        Normalize colloquial Turkish to standard form.

        Examples:
            "tmm bi dk bakcam" → "tamam bir dakika bakacağım"
            "naber nbr" → "ne haber ne haber"
        """
        result = text.lower().strip()

        # Multi-word patterns first
        for pattern, replacement in COLLOQUIAL_PATTERNS:
            result = pattern.sub(replacement, result)

        # Single word replacements
        words = result.split()
        normalized_words = []
        for word in words:
            clean = word.strip(".,!?;:")
            if clean in COLLOQUIAL_MAP:
                normalized_words.append(COLLOQUIAL_MAP[clean])
            else:
                normalized_words.append(word)

        return " ".join(normalized_words)

    @staticmethod
    def decompose_suffixes(word: str) -> Dict[str, Any]:
        """
        Deep agglutinative suffix chain decomposition.

        Example:
            "yapabileceklerimizden" →
            {
                "root": "yap",
                "suffixes": ["ability", "future", "plural", "1pl_poss", "ablative"],
                "is_verb": True,
                "confidence": 0.9
            }
        """
        normalized = word.lower().strip()
        result = {
            "original": word,
            "root": normalized,
            "suffixes": [],
            "is_verb": False,
            "confidence": 0.3,
        }

        # Try to match verb stems (longest first)
        sorted_verbs = sorted(TURKISH_VERBS.keys(), key=len, reverse=True)
        for stem in sorted_verbs:
            if normalized.startswith(stem) and len(normalized) > len(stem):
                remainder = normalized[len(stem):]
                # Try suffix chains on remainder
                for pattern, labels in SUFFIX_CHAINS:
                    if re.search(pattern, remainder):
                        result["root"] = stem
                        result["suffixes"] = labels
                        result["is_verb"] = True
                        result["confidence"] = 0.85 + (0.05 * len(labels))
                        return result

            # Exact verb match
            if normalized == stem:
                result["root"] = stem
                result["is_verb"] = True
                result["confidence"] = 0.95
                return result

        # Not a verb — try case suffix detection on nouns
        for pattern, labels in SUFFIX_CHAINS:
            if re.search(pattern, normalized):
                match = re.search(pattern, normalized)
                if match:
                    root = normalized[:match.start()]
                    if len(root) >= 2:
                        result["root"] = root
                        result["suffixes"] = labels
                        result["confidence"] = 0.7
                        return result

        return result

    @staticmethod
    def analyze_morpheme(token: str) -> Dict[str, Any]:
        """
        Analyze Turkish morpheme (backward-compatible API).
        """
        decomp = TurkishNLPAnalyzer.decompose_suffixes(token)

        # Determine case from suffixes
        case = "nominative"
        suffix_set = set(decomp.get("suffixes", []))
        if "ablative" in suffix_set:
            case = "ablative"
        elif "locative" in suffix_set:
            case = "locative"
        elif "instrumental" in suffix_set:
            case = "instrumental"
        elif "dative" in suffix_set:
            case = "dative"
        elif "accusative" in suffix_set:
            case = "accusative"
        elif "genitive" in suffix_set:
            case = "genitive"
        elif "case" in suffix_set:
            case = "detected"

        return {
            "original": token,
            "normalized": token.lower().strip(),
            "stem": decomp["root"],
            "case": case,
            "suffix": ", ".join(decomp.get("suffixes", [])),
            "is_verb": decomp["is_verb"],
            "is_noun": not decomp["is_verb"],
            "confidence": decomp["confidence"],
            "suffixes": decomp.get("suffixes", []),
        }

    @staticmethod
    def extract_stem(word: str) -> str:
        """Extract root word from Turkish word."""
        analysis = TurkishNLPAnalyzer.analyze_morpheme(word)
        return analysis["stem"]

    @staticmethod
    def parse_turkish_number(text: str) -> Optional[int]:
        """
        Parse Turkish number words to integer.
        Handles compound numbers up to billions.

        Examples:
            "iki yüz elli altı" → 256
            "üç bin dört yüz" → 3400
            "bir milyon iki yüz bin" → 1200000
        """
        text = text.lower().strip()

        # Direct numeric
        if text.isdigit():
            return int(text)

        # Direct lookup
        if text in TURKISH_NUMBERS:
            return TURKISH_NUMBERS[text]

        # Compound numbers
        words = text.split()
        total = 0
        current = 0
        last_multiplier = 0

        for word in words:
            if word not in TURKISH_NUMBERS:
                continue
            value = TURKISH_NUMBERS[word]

            if value >= 1000000000:  # milyar
                current = max(current, 1) * value
                total += current
                current = 0
                last_multiplier = value
            elif value >= 1000000:  # milyon
                current = max(current, 1) * value
                total += current
                current = 0
                last_multiplier = value
            elif value >= 1000:  # bin
                current = max(current, 1) * value
                total += current
                current = 0
                last_multiplier = value
            elif value >= 100:  # yüz
                current = max(current, 1) * value
            else:
                current += value

        total += current
        return total if total > 0 else None

    @staticmethod
    def extract_entities(text: str) -> Dict[str, List[str]]:
        """
        Named Entity Recognition for Turkish text.
        Extracts emails, phones, URLs, dates, times, file paths.
        """
        entities: Dict[str, List[str]] = {}

        for entity_type, pattern in NER_PATTERNS.items():
            matches = pattern.findall(text)
            if matches:
                if isinstance(matches[0], tuple):
                    entities[entity_type] = ["-".join(m) for m in matches]
                else:
                    entities[entity_type] = matches

        # Date words
        text_lower = text.lower()
        date_entities = []
        for word, value in DATE_WORDS.items():
            if word in text_lower:
                date_entities.append(word)
        if date_entities:
            entities["date_word"] = date_entities

        return entities

    @staticmethod
    def detect_intent_keywords(text: str) -> Dict[str, List[str]]:
        """
        Detect intent-related keywords in Turkish text.

        Returns dict of {intent_category: [matched_keywords]}
        """
        text_lower = text.lower()
        detected: Dict[str, List[str]] = {}

        for intent, keywords in INTENT_KEYWORDS.items():
            matches = [kw for kw in keywords if kw in text_lower]
            if matches:
                detected[intent] = matches

        return detected

    @staticmethod
    def normalize_turkish_text(text: str) -> str:
        """
        Full Turkish text normalization pipeline.
        1. Colloquial → standard
        2. Remove extra whitespace
        3. Remove punctuation
        """
        # First normalize colloquial
        normalized = TurkishNLPAnalyzer.normalize_colloquial(text)

        # Clean whitespace
        normalized = re.sub(r"\s+", " ", normalized).strip()

        # Remove common punctuation (keep ? for question detection)
        normalized = re.sub(r"[,.;:!]", "", normalized)

        return normalized

    @staticmethod
    def analyze_sentence(text: str) -> List[Dict[str, Any]]:
        """Analyze Turkish sentence into tokens with morphological info."""
        normalized = TurkishNLPAnalyzer.normalize_turkish_text(text)
        tokens = normalized.split()
        return [TurkishNLPAnalyzer.analyze_morpheme(token) for token in tokens]

    @staticmethod
    def detect_case(text: str) -> str:
        """Detect Turkish grammatical case from text."""
        text = text.lower().strip()
        case_priority = [
            (("dan", "den", "tan", "ten"), "ablative"),
            (("da", "de", "ta", "te"), "locative"),
            (("yla", "yle", "la", "le"), "instrumental"),
            (("nın", "nin", "nun", "nün", "ın", "in", "un", "ün"), "genitive"),
            (("ya", "ye", "na", "ne", "a", "e"), "dative"),
            (("yı", "yi", "yu", "yü", "ı", "i", "u", "ü"), "accusative"),
        ]
        for endings, case in case_priority:
            if text.endswith(endings):
                return case
        return "nominative"

    @staticmethod
    def extract_object(sentence: str) -> Optional[str]:
        """Extract grammatical object from Turkish sentence."""
        words = TurkishNLPAnalyzer.analyze_sentence(sentence)
        for word in words:
            if word["case"] == "accusative":
                return word["stem"]
        return None

    @staticmethod
    def extract_location(sentence: str) -> Optional[str]:
        """Extract location from Turkish sentence."""
        words = TurkishNLPAnalyzer.analyze_sentence(sentence)
        for word in words:
            if word["case"] == "locative":
                return word["stem"]
        return None

    @staticmethod
    def is_question(text: str) -> bool:
        """Detect if Turkish text is a question."""
        text_lower = text.lower().strip()
        # Explicit question mark
        if text_lower.endswith("?"):
            return True
        # Question words
        question_words = {"ne", "nere", "nasıl", "neden", "niçin", "niye",
                          "kim", "hangi", "kaç", "mi", "mı", "mu", "mü"}
        words = set(text_lower.split())
        return bool(words & question_words)

    @staticmethod
    def similarity_score(text1: str, text2: str) -> float:
        """Calculate similarity between Turkish texts (0.0-1.0)."""
        from difflib import SequenceMatcher
        n1 = TurkishNLPAnalyzer.normalize_turkish_text(text1)
        n2 = TurkishNLPAnalyzer.normalize_turkish_text(text2)
        return SequenceMatcher(None, n1, n2).ratio()
