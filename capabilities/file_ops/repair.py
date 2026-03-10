from __future__ import annotations

from typing import Any


def repair_file_ops_runtime(ctx: Any, verify_result: dict[str, Any] | None = None) -> dict[str, Any]:
    result = dict(verify_result or {})
    failed = list(result.get("failed") or [])
    if not failed:
        return {"repaired": False, "strategy": "noop", "failed": []}
    return {
        "repaired": False,
        "strategy": "controlled_file_ops_failure",
        "failed": failed,
        "message": "Dosya sistemi görevi doğrulama kapısından geçmedi.",
    }

