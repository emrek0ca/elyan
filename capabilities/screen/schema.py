from __future__ import annotations

from typing import Any


def build_screen_contract(*, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    clean = dict(params or {})
    return {
        "capability": "screen",
        "action": str(action or "").strip().lower(),
        "instruction": str(clean.get("instruction") or clean.get("prompt") or clean.get("objective") or "").strip(),
        "verify": True,
    }

