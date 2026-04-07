from __future__ import annotations

import time
from typing import Any

from core.execution_guard import get_execution_guard

from .repair import repair_file_ops_runtime
from .schema import build_file_ops_contract
from .verifier import verify_file_ops_runtime


def evaluate_file_ops_runtime(ctx: Any) -> dict[str, Any]:
    started_at = time.monotonic()
    intent = getattr(ctx, "intent", {}) if isinstance(getattr(ctx, "intent", {}), dict) else {}
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    contract = build_file_ops_contract(action=str(getattr(ctx, "action", "") or ""), params=params)
    verify = verify_file_ops_runtime(ctx)
    repair = repair_file_ops_runtime(ctx, verify)
    workspace_id = str(
        params.get("workspace_id")
        or (params.get("metadata") if isinstance(params.get("metadata"), dict) else {}).get("workspace_id")
        or "local-workspace"
    ).strip() or "local-workspace"
    session_id = str(
        params.get("session_id")
        or (params.get("metadata") if isinstance(params.get("metadata"), dict) else {}).get("session_id")
        or ""
    ).strip()
    run_id = str(
        params.get("run_id")
        or (params.get("metadata") if isinstance(params.get("metadata"), dict) else {}).get("run_id")
        or ""
    ).strip()
    actor_id = str(
        params.get("actor_id")
        or params.get("user_id")
        or (params.get("metadata") if isinstance(params.get("metadata"), dict) else {}).get("actor_id")
        or ""
    ).strip()
    payload = {"contract": contract, "verify": verify, "repair": repair}
    get_execution_guard().observe_capability_runtime(
        capability="file_ops",
        action=str(getattr(ctx, "action", "") or "").strip().lower(),
        success=bool(verify.get("ok")),
        workspace_id=workspace_id,
        actor_id=actor_id,
        session_id=session_id,
        run_id=run_id,
        reason=str((verify.get("failed_codes") or [""])[0] or ""),
        verification=verify,
        metadata={
            "target_path": str(verify.get("target_path") or contract.get("target_path") or ""),
            "repair_available": bool(repair),
            "artifact_count": len(list(verify.get("artifact_manifest") or [])),
        },
        level="warning" if not verify.get("ok") else "info",
    )
    try:
        from core.learning.reward_shaper import RewardShaper
        from core.learning.tool_bandit import get_tool_bandit

        elapsed_ms = (time.monotonic() - started_at) * 1000.0
        success = bool(verify.get("ok"))
        reward = RewardShaper().compute_reward(
            task_completed=success,
            user_explicit_feedback=None,
            response_time_ms=elapsed_ms,
            approval_required=False,
            task_was_in_cache=False,
            error_occurred=not success,
        )
        get_tool_bandit().record_outcome(
            task_category="file_ops",
            tool_name=str(getattr(ctx, "action", "") or "unknown").strip().lower() or "unknown",
            success=success,
            latency_ms=elapsed_ms,
            user_satisfaction=max(0.0, (reward + 2.0) / 4.0),
        )
    except Exception:
        pass
    return payload
