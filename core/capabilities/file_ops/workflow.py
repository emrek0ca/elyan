from __future__ import annotations

from typing import Any

from .repair import repair_file_ops_runtime
from .schema import build_file_ops_contract
from .verifier import verify_file_ops_runtime


def evaluate_file_ops_runtime(ctx: Any) -> dict[str, Any]:
    intent = getattr(ctx, "intent", {}) if isinstance(getattr(ctx, "intent", {}), dict) else {}
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    contract = build_file_ops_contract(action=str(getattr(ctx, "action", "") or ""), params=params)
    verify = verify_file_ops_runtime(ctx)
    repair = repair_file_ops_runtime(ctx, verify)
    return {"contract": contract, "verify": verify, "repair": repair}
