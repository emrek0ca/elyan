from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DEFAULT_MASK = "[REDACTED]"
DEFAULT_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "authorization",
    "bearer",
    "credit_card",
    "email",
    "jwt",
    "password",
    "phone",
    "refresh_token",
    "secret",
    "ssn",
    "tc_kimlik",
    "token",
}


@dataclass(frozen=True)
class RedactionResult:
    value: Any
    redacted: bool
    matches: list[str] = field(default_factory=list)


class PIIRedactor:
    def __init__(self, *, mask: str = DEFAULT_MASK, sensitive_keys: set[str] | None = None) -> None:
        self.mask = str(mask or DEFAULT_MASK)
        self.sensitive_keys = {str(item).strip().lower() for item in (sensitive_keys or DEFAULT_SENSITIVE_KEYS) if str(item).strip()}
        self._patterns: tuple[tuple[str, re.Pattern[str]], ...] = (
            ("EMAIL", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)),
            ("PHONE", re.compile(r"(?<!\w)(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3,4}\)?[\s.-]?)\d{3}[\s.-]?\d{2,4}(?!\w)")),
            ("TC_KIMLIK", re.compile(r"(?<!\d)([1-9]\d{10})(?!\d)")),
            ("IP_ADDRESS", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
            ("CREDIT_CARD", re.compile(r"(?<!\d)(?:\d[ -]?){13,19}(?!\d)")),
            ("URL_WITH_TOKEN", re.compile(r"\bhttps?://[^\s?#]+(?:\?[^#\s]*(?:token|key|secret|signature|sig|auth)=[^&#\s]+(?:&[^#\s]*)?)", re.IGNORECASE)),
            ("JWT_TOKEN", re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9._-]+\.[A-Za-z0-9._-]+\b")),
        )

    def redact(self, value: Any) -> RedactionResult:
        text = "" if value is None else str(value)
        matches: list[str] = []
        redacted_text = text
        for label, pattern in self._patterns:
            if not pattern.search(redacted_text):
                continue
            redacted_text = pattern.sub(self.mask, redacted_text)
            matches.append(label)
        return RedactionResult(value=redacted_text, redacted=(redacted_text != text), matches=matches)

    def redact_dict(self, payload: Any) -> RedactionResult:
        matches: list[str] = []
        changed = False

        def _walk(value: Any, *, key: str = "") -> Any:
            nonlocal changed
            key_name = str(key or "").strip().lower()
            if key_name and key_name in self.sensitive_keys:
                changed = True
                matches.append(f"KEY:{key_name}")
                return self.mask
            if isinstance(value, dict):
                return {str(k): _walk(v, key=str(k)) for k, v in value.items()}
            if isinstance(value, list):
                return [_walk(item, key=key) for item in value]
            if isinstance(value, tuple):
                return tuple(_walk(item, key=key) for item in value)
            if isinstance(value, str):
                result = self.redact(value)
                if result.redacted:
                    changed = True
                    matches.extend(result.matches)
                return result.value
            return value

        redacted_value = _walk(payload)
        return RedactionResult(value=redacted_value, redacted=changed, matches=matches)

    def is_clean(self, value: Any) -> bool:
        result = self.redact(value)
        return not result.redacted


_redactor: PIIRedactor | None = None


def get_redactor() -> PIIRedactor:
    global _redactor
    if _redactor is None:
        _redactor = PIIRedactor()
    return _redactor


__all__ = ["DEFAULT_MASK", "DEFAULT_SENSITIVE_KEYS", "PIIRedactor", "RedactionResult", "get_redactor"]
