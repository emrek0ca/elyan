"""
Turkish NLP Module

Morphological analysis, case detection, verb stems, number parsing.
For better Turkish language understanding in intent classification.
"""

import re
from typing import Dict, List, Tuple, Optional
from utils.logger import get_logger

logger = get_logger("turkish_nlp")

# Turkish verb stems and infinitive forms
TURKISH_VERBS = {
    "yap": {"infinitive": "yapmak", "stem": "yap"},
    "git": {"infinitive": "gitmek", "stem": "git"},
    "gel": {"infinitive": "gelmek", "stem": "gel"},
    "al": {"infinitive": "almak", "stem": "al"},
    "ver": {"infinitive": "vermek", "stem": "ver"},
    "tut": {"infinitive": "tutmak", "stem": "tut"},
    "koy": {"infinitive": "koymak", "stem": "koy"},
    "kalk": {"infinitive": "kalkmak", "stem": "kalk"},
    "otur": {"infinitive": "oturmak", "stem": "otur"},
    "bak": {"infinitive": "bakmak", "stem": "bak"},
    "aç": {"infinitive": "açmak", "stem": "aç"},
    "kapat": {"infinitive": "kapatmak", "stem": "kapat"},
    "aşar": {"infinitive": "aşarmak", "stem": "aşar"},
    "oku": {"infinitive": "okumak", "stem": "oku"},
    "yaz": {"infinitive": "yazmak", "stem": "yaz"},
    "söyle": {"infinitive": "söylemek", "stem": "söyle"},
    "söyle": {"infinitive": "söylemek", "stem": "söyle"},
    "ara": {"infinitive": "aramak", "stem": "ara"},
    "bul": {"infinitive": "bulmak", "stem": "bul"},
    "gönder": {"infinitive": "göndermek", "stem": "gönder"},
}

# Turkish number words
TURKISH_NUMBERS = {
    "sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4, "beş": 5,
    "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "yirmi": 20, "otuz": 30, "kırk": 40, "elli": 50, "altmış": 60,
    "yetmiş": 70, "seksen": 80, "doksan": 90, "yüz": 100,
    "bin": 1000, "milyon": 1000000
}

# Turkish case suffixes
CASE_SUFFIXES = {
    # Nominative (base): no suffix
    "nominative": "",
    # Accusative (direct object): -ı/-i/-u/-ü
    "accusative": ["ı", "i", "u", "ü"],
    # Dative (indirect object, to/for): -a/-e
    "dative": ["a", "e"],
    # Locative (location, at/in): -da/-de
    "locative": ["da", "de"],
    # Ablative (from): -dan/-den
    "ablative": ["dan", "den"],
    # Instrumental (with): -la/-le
    "instrumental": ["la", "le"],
    # Possessive: varies
    "possessive": ["im", "in", "i", "ım", "ın", "ı", "um", "un", "u", "ümüz", "ınız", "ız", "umuş", "unuz", "uz"],
}


class TurkishNLPAnalyzer:
    """Turkish morphological analysis and NLP utilities."""

    @staticmethod
    def analyze_morpheme(token: str) -> Dict[str, any]:
        """
        Analyze Turkish morpheme.

        Args:
            token: Turkish word to analyze

        Returns:
            Analysis dict with stem, case, suffix, etc.
        """
        normalized = token.lower().strip()

        result = {
            "original": token,
            "normalized": normalized,
            "stem": normalized,
            "case": "nominative",
            "suffix": "",
            "is_verb": False,
            "is_noun": True,
            "confidence": 0.5
        }

        # Check if verb stem
        if normalized in TURKISH_VERBS:
            result["is_verb"] = True
            result["is_noun"] = False
            result["stem"] = normalized
            result["confidence"] = 0.95
            return result

        # Try to extract case suffix - check longer suffixes first
        suffix_order = [
            ("ablative", CASE_SUFFIXES["ablative"]),  # -dan/-den (longest)
            ("locative", CASE_SUFFIXES["locative"]),  # -da/-de
            ("instrumental", CASE_SUFFIXES["instrumental"]),  # -la/-le
            ("dative", CASE_SUFFIXES["dative"]),  # -a/-e
            ("accusative", CASE_SUFFIXES["accusative"]),  # -ı/-i/-u/-ü (shortest)
        ]

        for case, suffixes in suffix_order:
            for suffix in (suffixes if isinstance(suffixes, list) else [suffixes]):
                if normalized.endswith(suffix) and len(suffix) > 0:
                    stem = normalized[:-len(suffix)]
                    if len(stem) >= 2:
                        result["stem"] = stem
                        result["case"] = case
                        result["suffix"] = suffix
                        result["confidence"] = 0.7
                        return result

        return result

    @staticmethod
    def extract_stem(word: str) -> str:
        """
        Extract root word from Turkish word.

        Args:
            word: Turkish word with suffixes

        Returns:
            Root word
        """
        analysis = TurkishNLPAnalyzer.analyze_morpheme(word)
        return analysis["stem"]

    @staticmethod
    def parse_turkish_number(text: str) -> Optional[int]:
        """
        Parse Turkish number words to integer.

        Args:
            text: Turkish number text (e.g., "elli beş")

        Returns:
            Integer value or None
        """
        text = text.lower().strip()

        # Try direct lookup
        if text in TURKISH_NUMBERS:
            return TURKISH_NUMBERS[text]

        # Try compound numbers (e.g., "elli beş" = 55)
        words = text.split()
        total = 0
        current = 0

        for word in words:
            if word in TURKISH_NUMBERS:
                value = TURKISH_NUMBERS[word]
                if value >= 100:
                    current += value
                    total += current
                    current = 0
                else:
                    current += value

        if current > 0:
            total += current

        return total if total > 0 else None

    @staticmethod
    def normalize_turkish_text(text: str) -> str:
        """
        Normalize Turkish text.

        Args:
            text: Raw Turkish text

        Returns:
            Normalized text
        """
        # Lowercase
        normalized = text.lower().strip()

        # Remove extra whitespace
        normalized = re.sub(r"\s+", " ", normalized)

        # Remove common punctuation
        normalized = re.sub(r"[,.;:!?]", "", normalized)

        return normalized

    @staticmethod
    def analyze_sentence(text: str) -> List[Dict[str, any]]:
        """
        Analyze Turkish sentence into tokens.

        Args:
            text: Turkish sentence

        Returns:
            List of token analyses
        """
        normalized = TurkishNLPAnalyzer.normalize_turkish_text(text)
        tokens = normalized.split()

        analyses = []
        for token in tokens:
            analyses.append(TurkishNLPAnalyzer.analyze_morpheme(token))

        return analyses

    @staticmethod
    def detect_case(text: str) -> str:
        """
        Detect Turkish grammatical case from text.

        Args:
            text: Turkish text

        Returns:
            Case name
        """
        text = text.lower().strip()

        # Check for case endings - longer suffixes first
        if text.endswith(("dan", "den")):
            return "ablative"
        if text.endswith(("da", "de")):
            return "locative"
        if text.endswith(("la", "le")):
            return "instrumental"
        if text.endswith(("a", "e")):
            return "dative"
        if text.endswith(("ı", "i", "u", "ü")):
            return "accusative"

        return "nominative"

    @staticmethod
    def extract_object(sentence: str) -> Optional[str]:
        """
        Extract grammatical object from Turkish sentence.

        Args:
            sentence: Turkish sentence

        Returns:
            Object word or None
        """
        words = TurkishNLPAnalyzer.analyze_sentence(sentence)
        for word in words:
            if word["case"] == "accusative":
                return word["stem"]

        return None

    @staticmethod
    def extract_location(sentence: str) -> Optional[str]:
        """
        Extract location from Turkish sentence.

        Args:
            sentence: Turkish sentence

        Returns:
            Location word or None
        """
        words = TurkishNLPAnalyzer.analyze_sentence(sentence)
        for word in words:
            if word["case"] == "locative":
                return word["stem"]

        return None

    @staticmethod
    def similarity_score(text1: str, text2: str) -> float:
        """
        Calculate similarity between Turkish texts (0.0-1.0).

        Args:
            text1: First text
            text2: Second text

        Returns:
            Similarity score
        """
        from difflib import SequenceMatcher
        n1 = TurkishNLPAnalyzer.normalize_turkish_text(text1)
        n2 = TurkishNLPAnalyzer.normalize_turkish_text(text2)
        return SequenceMatcher(None, n1, n2).ratio()
