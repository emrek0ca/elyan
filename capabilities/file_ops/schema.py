from __future__ import annotations

from pathlib import Path
from typing import Any


def build_file_ops_contract(*, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    clean = dict(params or {})
    path = str(
        clean.get("path")
        or clean.get("target_path")
        or clean.get("destination")
        or clean.get("source")
        or ""
    ).strip()
    file_name = Path(path).name if path else str(clean.get("file_name") or "").strip()
    return {
        "capability": "file_ops",
        "action": str(action or "").strip().lower(),
        "target_path": path,
        "file_name": file_name,
        "verify": True,
    }

