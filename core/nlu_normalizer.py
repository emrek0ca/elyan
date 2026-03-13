from __future__ import annotations

import re


_TR_ASCII_MAP = str.maketrans("çğıöşüÇĞİÖŞÜ", "cgiosuCGIOSU")
_APOSTROPHES_RE = re.compile(r"[’`´]")
_NON_WORD_RE = re.compile(r"[^a-z0-9çğıöşü\s]+", re.IGNORECASE)
_MULTISPACE_RE = re.compile(r"\s+")
_COMMON_SUFFIXES = {
    "a",
    "e",
    "da",
    "de",
    "dan",
    "den",
    "ta",
    "te",
    "yi",
    "yı",
    "yu",
    "yü",
    "i",
    "ı",
    "u",
    "ü",
    "ya",
    "ye",
}
_SUFFIX_SPLIT_ROOTS = {
    "chrome",
    "safari",
    "terminal",
    "google",
    "youtube",
    "finder",
    "firefox",
    "arc",
    "desktop",
    "masaüstü",
    "masaustu",
    "masaüstünde",
    "masaustunde",
    "belgeler",
    "downloads",
    "indirilenler",
    "telegram",
    "discord",
    "slack",
}

_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bacip\b", re.IGNORECASE), "açıp"),
    (re.compile(r"\bcalistirip\b", re.IGNORECASE), "çalıştırıp"),
    (re.compile(r"\byazip\b", re.IGNORECASE), "yazıp"),
    (re.compile(r"\bgidip\b", re.IGNORECASE), "gidip"),
    (re.compile(r"\bgirip\b", re.IGNORECASE), "girip"),
    (re.compile(r"\bnap[ıi](?:y|yo|iyo|ıyo|i?o)?sun\b", re.IGNORECASE), "ne yapıyorsun"),
    (re.compile(r"\bnapi(?:y|yo|iyo|i?o)?sun\b", re.IGNORECASE), "ne yapıyorsun"),
    (re.compile(r"\bnap[ıi](?:y|yo|iyo|ıyo)?n\b", re.IGNORECASE), "ne yapıyorsun"),
    (re.compile(r"\bnapi(?:y|yo|iyo)?n\b", re.IGNORECASE), "ne yapıyorsun"),
    (re.compile(r"\bnapt[ıi]n\b", re.IGNORECASE), "ne yaptın"),
    (re.compile(r"\bnbr\b", re.IGNORECASE), "naber"),
    (re.compile(r"\bslm\b", re.IGNORECASE), "selam"),
    (re.compile(r"\bmrb\b", re.IGNORECASE), "merhaba"),
    (re.compile(r"\bsa\b", re.IGNORECASE), "selam"),
    (re.compile(r"\bas\b", re.IGNORECASE), "aleyküm selam"),
    (re.compile(r"\bkib\b", re.IGNORECASE), "kendine iyi bak"),
    (re.compile(r"\btmm\b", re.IGNORECASE), "tamam"),
    (re.compile(r"\bkanka\b", re.IGNORECASE), "arkadaş"),
    (re.compile(r"\babi\b", re.IGNORECASE), "arkadaş"),
    (re.compile(r"\bchromea\b", re.IGNORECASE), "chrome a"),
    (re.compile(r"\bsafariye\b", re.IGNORECASE), "safari ye"),
    (re.compile(r"\bchromeye\b", re.IGNORECASE), "chrome ye"),
)

_TOKEN_REPLACEMENTS = {
    "masaustu": "masaüstü",
    "masaustunde": "masaüstünde",
    "masaustundeki": "masaüstündeki",
    "arastir": "araştır",
    "arastirma": "araştırma",
    "nasilsin": "nasılsın",
    "nasilsin": "nasılsın",
    "kotu": "kötü",
    "guzel": "güzel",
    "olustur": "oluştur",
    "calistir": "çalıştır",
    "ac": "aç",
    "acip": "açıp",
    "calistirip": "çalıştırıp",
    "yazip": "yazıp",
    "kapatcam": "kapatacağım",
}


def normalize_turkish_text(text: str, *, ascii_fold: bool = False) -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return ""
    normalized = _APOSTROPHES_RE.sub("'", raw)
    normalized = normalized.replace("’", "'")
    for pattern, replacement in _PHRASE_REPLACEMENTS:
        normalized = pattern.sub(replacement, normalized)

    normalized = normalized.replace("'", " ")
    normalized = _NON_WORD_RE.sub(" ", normalized)

    tokens: list[str] = []
    for token in normalized.split():
        compact = _collapse_repeated_letters(token)
        token = _TOKEN_REPLACEMENTS.get(compact, compact)
        split_tokens = _split_attached_suffix(token)
        tokens.extend(split_tokens)

    normalized = " ".join(tokens)
    normalized = _MULTISPACE_RE.sub(" ", normalized).strip()
    if ascii_fold:
        normalized = normalized.translate(_TR_ASCII_MAP)
    return normalized


def normalize_turkish_ascii(text: str) -> str:
    return normalize_turkish_text(text, ascii_fold=True)


def _collapse_repeated_letters(token: str) -> str:
    if len(token) < 3:
        return token
    return re.sub(r"(.)\1{2,}", r"\1", token)


def _split_attached_suffix(token: str) -> list[str]:
    if len(token) < 4:
        return [token]
    for root in sorted(_SUFFIX_SPLIT_ROOTS, key=len, reverse=True):
        if not token.startswith(root) or token == root:
            continue
        suffix = token[len(root):]
        if suffix in _COMMON_SUFFIXES:
            return [root, suffix]
    return [token]


__all__ = ["normalize_turkish_text", "normalize_turkish_ascii"]
