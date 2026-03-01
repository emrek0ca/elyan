from __future__ import annotations

from typing import Any, Dict


CHANNEL_CAPABILITY_MATRIX: Dict[str, Dict[str, Any]] = {
    "telegram": {"markdown": True, "html": False, "buttons": True, "images": True, "files": True, "text_limit": 3900},
    "discord": {"markdown": True, "html": False, "buttons": True, "images": True, "files": True, "text_limit": 1900},
    "slack": {"markdown": True, "html": False, "buttons": True, "images": True, "files": True, "text_limit": 3800},
    "whatsapp": {"markdown": False, "html": False, "buttons": False, "images": True, "files": True, "text_limit": 3500},
    "signal": {"markdown": False, "html": False, "buttons": False, "images": True, "files": True, "text_limit": 3500},
    "matrix": {"markdown": True, "html": True, "buttons": False, "images": True, "files": True, "text_limit": 3500},
    "teams": {"markdown": True, "html": False, "buttons": True, "images": True, "files": True, "text_limit": 3500},
    "google_chat": {"markdown": False, "html": False, "buttons": True, "images": True, "files": True, "text_limit": 3500},
    "imessage": {"markdown": False, "html": False, "buttons": False, "images": True, "files": True, "text_limit": 3500},
    "webchat": {"markdown": True, "html": True, "buttons": True, "images": True, "files": True, "text_limit": 12000},
    "cli": {"markdown": True, "html": False, "buttons": False, "images": False, "files": False, "text_limit": 12000},
    "default": {"markdown": False, "html": False, "buttons": False, "images": False, "files": False, "text_limit": 3500},
}


def resolve_channel_capabilities(channel_type: str, adapter_caps: Dict[str, Any] | None = None) -> Dict[str, Any]:
    key = str(channel_type or "").strip().lower()
    base = dict(CHANNEL_CAPABILITY_MATRIX.get(key, CHANNEL_CAPABILITY_MATRIX["default"]))
    raw = adapter_caps if isinstance(adapter_caps, dict) else {}

    for name in ("markdown", "html", "buttons", "images", "files"):
        if name in raw:
            base[name] = bool(raw.get(name))

    text_limit = raw.get("text_limit", raw.get("max_length", raw.get("message_max_len", base.get("text_limit", 3500))))
    try:
        base["text_limit"] = max(300, int(text_limit))
    except Exception:
        base["text_limit"] = int(base.get("text_limit", 3500))

    return base


__all__ = ["CHANNEL_CAPABILITY_MATRIX", "resolve_channel_capabilities"]

