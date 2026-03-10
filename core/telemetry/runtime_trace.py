from __future__ import annotations

import time
import uuid
from typing import Any


def ensure_runtime_trace(ctx: Any) -> dict[str, Any]:
    trace = getattr(ctx, "telemetry", {}) if isinstance(getattr(ctx, "telemetry", {}), dict) else {}
    if not trace.get("request_id"):
        trace["request_id"] = f"req_{uuid.uuid4().hex[:12]}"
    trace.setdefault("capability", str(getattr(ctx, "capability_domain", "") or "general"))
    trace.setdefault("selected_workflow", str(getattr(ctx, "workflow_id", "") or getattr(ctx, "action", "") or ""))
    trace.setdefault("extracted_params", {})
    trace.setdefault("tool_calls", [])
    trace.setdefault("verifier_results", {})
    trace.setdefault("repair_steps", [])
    trace.setdefault("delivery_mode", str(getattr(ctx, "channel", "") or "cli"))
    trace.setdefault("final_status", "")
    trace.setdefault("started_at", time.time())
    ctx.telemetry = trace
    return trace


def update_runtime_trace(ctx: Any, **fields: Any) -> dict[str, Any]:
    trace = ensure_runtime_trace(ctx)
    for key, value in fields.items():
        if value is not None:
            trace[key] = value
    ctx.telemetry = trace
    return trace
