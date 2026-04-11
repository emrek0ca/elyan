"""
Privacy Guard

Centralized helpers to prevent accidental sensitive data leakage in:
- logs
- memory/learning storage
- cloud LLM prompts
"""

from __future__ import annotations

import re
from typing import Any


_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b")),
    ("PHONE", re.compile(r"\b(?:\+?\d{1,3}[\s-]?)?(?:\(?\d{2,4}\)?[\s-]?)\d{3,4}[\s-]?\d{2,4}\b")),
    ("IBAN", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{10,30}\b")),
    ("IPV4", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("CARD", re.compile(r"\b(?:\d[ -]*?){13,19}\b")),
    ("SECRET_KEY", re.compile(r"\b(?:sk|pk|rk|api|token|key)[-_]?[a-zA-Z0-9]{12,}\b", re.IGNORECASE)),
    ("JWT", re.compile(r"\beyJ[a-zA-Z0-9_-]{10,}\.[a-zA-Z0-9._-]{10,}\.[a-zA-Z0-9._-]{10,}\b")),
]


def redact_text(text: str, max_len: int = 3000) -> str:
    """Mask common sensitive tokens while preserving task meaning."""
    if not text:
        return ""

    redacted = str(text)
    for label, pattern in _PATTERNS:
        redacted = pattern.sub(f"[REDACTED_{label}]", redacted)

    if len(redacted) > max_len:
        return redacted[:max_len] + "...[TRUNCATED]"
    return redacted


def sanitize_for_storage(text: str, max_len: int = 2000) -> str:
    return redact_text(text, max_len=max_len)


def sanitize_object(payload: Any, depth: int = 0, max_depth: int = 4) -> Any:
    """Recursively sanitize nested objects for safe logs/storage."""
    if depth > max_depth:
        return "[TRUNCATED_OBJECT]"

    if payload is None:
        return None
    if isinstance(payload, str):
        return redact_text(payload)
    if isinstance(payload, (int, float, bool)):
        return payload
    if isinstance(payload, list):
        return [sanitize_object(v, depth + 1, max_depth) for v in payload[:50]]
    if isinstance(payload, tuple):
        return tuple(sanitize_object(v, depth + 1, max_depth) for v in payload[:50])
    if isinstance(payload, dict):
        sanitized: dict[str, Any] = {}
        for idx, (k, v) in enumerate(payload.items()):
            if idx >= 100:
                sanitized["__truncated__"] = True
                break
            sanitized[str(k)] = sanitize_object(v, depth + 1, max_depth)
        return sanitized
    return redact_text(str(payload))


def is_external_provider(provider: str) -> bool:
    p = str(provider or "").strip().lower()
    return p in {"groq", "gemini", "google", "openai", "openrouter", "anthropic"}
