"""
ELYAN Multi-Language Support - Phase 10
Language detection, translation framework, locale management.
"""

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple


class Language(Enum):
    TURKISH = "tr"
    ENGLISH = "en"
    SPANISH = "es"
    GERMAN = "de"
    FRENCH = "fr"
    ARABIC = "ar"
    CHINESE = "zh"
    JAPANESE = "ja"
    KOREAN = "ko"
    RUSSIAN = "ru"
    PORTUGUESE = "pt"
    ITALIAN = "it"
    DUTCH = "nl"
    POLISH = "pl"


class TextDirection(Enum):
    LTR = "ltr"
    RTL = "rtl"


RTL_LANGUAGES = {Language.ARABIC}

LANGUAGE_NAMES = {
    Language.TURKISH: "Turkce",
    Language.ENGLISH: "English",
    Language.SPANISH: "Espanol",
    Language.GERMAN: "Deutsch",
    Language.FRENCH: "Francais",
    Language.ARABIC: "al-Arabiyyah",
    Language.CHINESE: "Zhongwen",
    Language.JAPANESE: "Nihongo",
    Language.KOREAN: "Hangugeo",
    Language.RUSSIAN: "Russkiy",
    Language.PORTUGUESE: "Portugues",
    Language.ITALIAN: "Italiano",
    Language.DUTCH: "Nederlands",
    Language.POLISH: "Polski",
}

LANGUAGE_INDICATORS: Dict[Language, Set[str]] = {
    Language.TURKISH: {
        "bir", "bu", "ve", "ile", "icin", "gibi", "kadar", "ama", "var",
        "yok", "daha", "cok", "nasil", "nerede", "ne", "bence", "tamam",
    },
    Language.ENGLISH: {
        "the", "is", "are", "was", "have", "has", "will", "can", "this",
        "that", "from", "with", "about", "please", "thanks", "yes", "no",
    },
    Language.SPANISH: {
        "el", "la", "los", "las", "un", "una", "es", "son", "tiene",
        "como", "que", "por", "para", "con", "pero", "mas", "muy",
    },
    Language.GERMAN: {
        "der", "die", "das", "ein", "eine", "ist", "sind", "hat",
        "mit", "und", "oder", "aber", "nicht", "auch", "noch",
    },
    Language.FRENCH: {
        "le", "la", "les", "un", "une", "est", "sont", "avec",
        "pour", "dans", "mais", "aussi", "plus", "tres", "que",
    },
}

CHAR_RANGES = {
    Language.ARABIC: re.compile(r"[\u0600-\u06FF]"),
    Language.CHINESE: re.compile(r"[\u4e00-\u9fff]"),
    Language.JAPANESE: re.compile(r"[\u3040-\u309f\u30a0-\u30ff]"),
    Language.KOREAN: re.compile(r"[\uac00-\ud7af]"),
    Language.RUSSIAN: re.compile(r"[\u0400-\u04FF]"),
    Language.TURKISH: re.compile(r"[cCgGiIoOsS\u00e7\u00c7\u011f\u011e\u0131\u0130\u00f6\u00d6\u015f\u015e\u00fc\u00dc]"),
}


@dataclass
class DetectionResult:
    primary_language: Language
    confidence: float
    scores: Dict[Language, float]
    is_multilingual: bool = False
    detected_languages: List[Language] = field(default_factory=list)
    text_direction: TextDirection = TextDirection.LTR


@dataclass
class TranslationRequest:
    text: str
    source_language: Language
    target_language: Language
    context: str = ""


@dataclass
class TranslationResult:
    original: str
    translated: str
    source_language: Language
    target_language: Language
    confidence: float = 0.0
    method: str = "dictionary"


@dataclass
class Locale:
    language: Language
    region: str = ""
    date_format: str = "YYYY-MM-DD"
    time_format: str = "HH:mm"
    number_separator: str = ","
    decimal_separator: str = "."
    currency: str = "USD"
    text_direction: TextDirection = TextDirection.LTR


DEFAULT_LOCALES = {
    Language.TURKISH: Locale(Language.TURKISH, "TR", "DD.MM.YYYY", "HH:mm", ".", ",", "TRY"),
    Language.ENGLISH: Locale(Language.ENGLISH, "US", "MM/DD/YYYY", "hh:mm A", ",", ".", "USD"),
    Language.SPANISH: Locale(Language.SPANISH, "ES", "DD/MM/YYYY", "HH:mm", ".", ",", "EUR"),
    Language.GERMAN: Locale(Language.GERMAN, "DE", "DD.MM.YYYY", "HH:mm", ".", ",", "EUR"),
    Language.FRENCH: Locale(Language.FRENCH, "FR", "DD/MM/YYYY", "HH:mm", " ", ",", "EUR"),
    Language.ARABIC: Locale(Language.ARABIC, "SA", "DD/MM/YYYY", "hh:mm", ",", ".", "SAR", TextDirection.RTL),
}


class LanguageDetector:
    """Detect language from text using character analysis and word matching."""

    def detect(self, text: str) -> DetectionResult:
        if not text.strip():
            return DetectionResult(Language.ENGLISH, 0.0, {}, False, [])
        scores: Dict[Language, float] = defaultdict(float)
        for lang, pattern in CHAR_RANGES.items():
            matches = len(pattern.findall(text))
            if matches > 0:
                scores[lang] += matches * 2
        words = text.lower().split()
        clean_words = [re.sub(r"[^a-z\u00e7\u011f\u0131\u00f6\u015f\u00fc]", "", w) for w in words]
        clean_words = [w for w in clean_words if w]
        for lang, indicators in LANGUAGE_INDICATORS.items():
            count = sum(1 for w in clean_words if w in indicators)
            if count > 0:
                scores[lang] += count * 3
        if not scores:
            return DetectionResult(Language.ENGLISH, 0.3, {}, False, [Language.ENGLISH])
        total = sum(scores.values()) or 1
        normalized = {lang: score / total for lang, score in scores.items()}
        primary = max(normalized, key=normalized.get)
        confidence = normalized[primary]
        detected = [lang for lang, score in normalized.items() if score > 0.15]
        is_multi = len(detected) > 1 and confidence < 0.7
        direction = TextDirection.RTL if primary in RTL_LANGUAGES else TextDirection.LTR
        return DetectionResult(
            primary_language=primary,
            confidence=round(confidence, 3),
            scores={k: round(v, 3) for k, v in normalized.items()},
            is_multilingual=is_multi,
            detected_languages=detected,
            text_direction=direction,
        )


class TranslationEngine:
    """Translation framework with dictionary-based fallback."""

    def __init__(self):
        self._dictionaries: Dict[Tuple[Language, Language], Dict[str, str]] = {}
        self._translation_count = 0
        self._load_basic_dictionaries()

    def _load_basic_dictionaries(self):
        tr_en = {
            "merhaba": "hello", "nasil": "how", "tesekkur": "thanks",
            "evet": "yes", "hayir": "no", "tamam": "ok", "lutfen": "please",
            "iyi": "good", "kotu": "bad", "buyuk": "big", "kucuk": "small",
            "yeni": "new", "eski": "old", "hizli": "fast", "yavas": "slow",
            "dosya": "file", "klasor": "folder", "proje": "project",
            "kod": "code", "hata": "error", "basarili": "successful",
            "kullanici": "user", "sistem": "system", "ayar": "setting",
        }
        self._dictionaries[(Language.TURKISH, Language.ENGLISH)] = tr_en
        self._dictionaries[(Language.ENGLISH, Language.TURKISH)] = {v: k for k, v in tr_en.items()}

    def translate(self, request: TranslationRequest) -> TranslationResult:
        pair = (request.source_language, request.target_language)
        dictionary = self._dictionaries.get(pair, {})
        words = request.text.split()
        translated_words = []
        matched = 0
        for word in words:
            clean = word.lower().strip(".,!?;:")
            if clean in dictionary:
                translated_words.append(dictionary[clean])
                matched += 1
            else:
                translated_words.append(word)
        self._translation_count += 1
        confidence = matched / max(1, len(words))
        return TranslationResult(
            original=request.text,
            translated=" ".join(translated_words),
            source_language=request.source_language,
            target_language=request.target_language,
            confidence=round(confidence, 3),
            method="dictionary",
        )

    def add_dictionary(self, source: Language, target: Language, entries: Dict[str, str]):
        pair = (source, target)
        if pair not in self._dictionaries:
            self._dictionaries[pair] = {}
        self._dictionaries[pair].update(entries)

    def get_supported_pairs(self) -> List[Tuple[Language, Language]]:
        return list(self._dictionaries.keys())

    def get_stats(self) -> Dict[str, Any]:
        return {
            "translation_count": self._translation_count,
            "dictionary_pairs": len(self._dictionaries),
            "total_entries": sum(len(d) for d in self._dictionaries.values()),
        }


class LocaleManager:
    """Manage user locale preferences."""

    def __init__(self):
        self._user_locales: Dict[str, Locale] = {}

    def set_locale(self, user_id: str, language: Language, region: str = ""):
        locale = DEFAULT_LOCALES.get(language, Locale(language, region))
        if region:
            locale.region = region
        self._user_locales[user_id] = locale

    def get_locale(self, user_id: str) -> Locale:
        return self._user_locales.get(user_id, DEFAULT_LOCALES[Language.ENGLISH])

    def format_number(self, number: float, user_id: str) -> str:
        locale = self.get_locale(user_id)
        int_part = int(number)
        dec_part = number - int_part
        int_str = f"{int_part:,}".replace(",", locale.number_separator)
        if dec_part > 0:
            dec_str = f"{dec_part:.2f}"[1:].replace(".", locale.decimal_separator)
            return f"{int_str}{dec_str}"
        return int_str

    def get_text_direction(self, user_id: str) -> TextDirection:
        locale = self.get_locale(user_id)
        return locale.text_direction


class MultiLanguageEngine:
    """Unified multi-language engine."""

    def __init__(self):
        self.detector = LanguageDetector()
        self.translator = TranslationEngine()
        self.locale_manager = LocaleManager()

    def process(self, text: str, user_id: Optional[str] = None) -> Dict[str, Any]:
        detection = self.detector.detect(text)
        result = {
            "text": text,
            "detected_language": detection.primary_language.value,
            "confidence": detection.confidence,
            "is_multilingual": detection.is_multilingual,
            "text_direction": detection.text_direction.value,
        }
        if user_id:
            locale = self.locale_manager.get_locale(user_id)
            result["user_locale"] = {
                "language": locale.language.value,
                "region": locale.region,
                "direction": locale.text_direction.value,
            }
        return result

    def auto_translate(self, text: str, target: Language) -> TranslationResult:
        detection = self.detector.detect(text)
        if detection.primary_language == target:
            return TranslationResult(text, text, target, target, 1.0, "same_language")
        request = TranslationRequest(
            text=text,
            source_language=detection.primary_language,
            target_language=target,
        )
        return self.translator.translate(request)


_multi_language_engine: Optional[MultiLanguageEngine] = None


def get_multi_language_engine() -> MultiLanguageEngine:
    global _multi_language_engine
    if _multi_language_engine is None:
        _multi_language_engine = MultiLanguageEngine()
    return _multi_language_engine
