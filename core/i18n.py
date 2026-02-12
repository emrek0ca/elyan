"""Lightweight internationalization helpers for Wiqo."""

from __future__ import annotations

import re

SUPPORTED_LANGUAGES = {
    "auto": "Auto Detect",
    "tr": "Turkce",
    "en": "English",
    "es": "Espanol",
    "de": "Deutsch",
    "fr": "Francais",
    "it": "Italiano",
    "pt": "Portugues",
    "ar": "Arabic",
    "ru": "Russian",
}


LANG_HINTS = {
    "tr": {"ve", "bir", "için", "ile", "merhaba", "nasılsın", "neden", "çünkü"},
    "en": {"the", "and", "for", "with", "hello", "please", "what", "why"},
    "es": {"hola", "gracias", "porque", "para", "con", "como", "que"},
    "de": {"hallo", "danke", "warum", "mit", "und", "für", "wie"},
    "fr": {"bonjour", "merci", "pourquoi", "avec", "et", "pour", "comment"},
    "it": {"ciao", "grazie", "perche", "con", "e", "per", "come"},
    "pt": {"ola", "obrigado", "porque", "com", "e", "para", "como"},
    "ar": {"مرحبا", "شكرا", "لماذا", "كيف", "مع"},
    "ru": {"привет", "спасибо", "почему", "как", "и", "с"},
}


def normalize_language_code(code: str | None, default: str = "auto") -> str:
    raw = str(code or "").strip().lower()
    if raw in SUPPORTED_LANGUAGES:
        return raw
    aliases = {
        "turkish": "tr",
        "türkçe": "tr",
        "english": "en",
        "spanish": "es",
        "german": "de",
        "french": "fr",
        "italian": "it",
        "portuguese": "pt",
        "arabic": "ar",
        "russian": "ru",
    }
    return aliases.get(raw, default)


def detect_language(message: str) -> str:
    text = str(message or "").strip()
    if not text:
        return "en"

    # Script-based fast path.
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    if re.search(r"[\u0400-\u04FF]", text):
        return "ru"

    lowered = text.lower()
    tokens = set(re.findall(r"[a-zA-ZçğıöşüÇĞİÖŞÜ]+", lowered))
    if not tokens:
        return "en"

    best_lang = "en"
    best_score = 0
    for lang, hints in LANG_HINTS.items():
        score = len(tokens.intersection(hints))
        if score > best_score:
            best_score = score
            best_lang = lang

    # Turkish chars are strong indicators.
    if any(ch in text for ch in "çğıöşüÇĞİÖŞÜ"):
        return "tr"

    return best_lang

