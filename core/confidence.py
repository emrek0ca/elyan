from __future__ import annotations

import unicodedata
from typing import Any


_CONFIDENCE_LABELS = {
    "very high": 0.92,
    "high": 0.82,
    "medium": 0.58,
    "med": 0.58,
    "low": 0.34,
    "very low": 0.18,
    "critical": 0.95,
}


def normalize_confidence_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return " ".join(normalized.lower().split())


def coerce_confidence(value: Any, default: float = 0.0) -> float:
    if isinstance(value, bool):
        score = float(default)
    elif isinstance(value, (int, float)):
        score = float(value)
    else:
        text = normalize_confidence_text(value)
        if not text:
            score = float(default)
        elif text in _CONFIDENCE_LABELS:
            score = _CONFIDENCE_LABELS[text]
        else:
            candidate = text.replace(",", ".").rstrip("%").strip()
            try:
                score = float(candidate)
            except Exception:
                score = float(default)
            if "%" in text or score > 1.0:
                score = score / 100.0
    return max(0.0, min(score, 1.0))


__all__ = ["coerce_confidence", "normalize_confidence_text"]
