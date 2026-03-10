from __future__ import annotations

from typing import Any, Callable

from .base import CapabilityRuntime
from .file_ops.workflow import evaluate_file_ops_runtime
from .screen_operator.workflow import evaluate_screen_operator_runtime


_FILE_OP_ACTIONS = frozenset({"create_folder", "write_file", "write_word", "write_excel", "read_file", "list_files"})
_SCREEN_ACTIONS = frozenset({"screen_workflow", "analyze_screen", "take_screenshot"})


_CAPABILITIES = (
    CapabilityRuntime(
        capability_id="screen_operator",
        workflow_id="screen_operator.runtime.v3",
        actions=_SCREEN_ACTIONS,
        evaluator=evaluate_screen_operator_runtime,
    ),
    CapabilityRuntime(
        capability_id="file_ops",
        workflow_id="file_ops.runtime.v3",
        actions=_FILE_OP_ACTIONS,
        evaluator=evaluate_file_ops_runtime,
    ),
)


def resolve_capability_runtime(action: str) -> CapabilityRuntime | None:
    normalized = str(action or "").strip().lower()
    for capability in _CAPABILITIES:
        if capability.supports(normalized):
            return capability
    return None


def evaluate_capability_runtime(
    ctx: Any,
    *,
    synthesize_screen_summary: Callable[[Any], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    capability = resolve_capability_runtime(getattr(ctx, "action", ""))
    if capability is None:
        return {"contract": {}, "verify": {"ok": True, "status": "success", "checks": [], "failed": [], "failed_codes": []}, "repair": {"repaired": False, "strategy": "noop", "failed": [], "failed_codes": []}}
    if capability.capability_id == "screen_operator":
        return capability.evaluator(ctx, synthesize_summary=synthesize_screen_summary)
    return capability.evaluator(ctx)
