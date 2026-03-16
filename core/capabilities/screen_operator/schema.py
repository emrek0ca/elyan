from __future__ import annotations

from typing import Any


_CONTROL_MODES = {"control", "inspect_and_control"}


def build_screen_operator_contract(*, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    clean = dict(params or {})
    mode = str(clean.get("mode") or "inspect").strip().lower() or "inspect"
    required_artifacts = ["before.png", "ui_state.json", "screen_summary.txt"]
    if mode in _CONTROL_MODES:
        required_artifacts.extend(["after.png", "action_log.json"])
    return {
        "capability": "screen",
        "capability_id": "screen_operator",
        "workflow_id": "screen_operator.runtime.v3",
        "action": str(action or "").strip().lower(),
        "mode": mode,
        "instruction": str(clean.get("instruction") or clean.get("prompt") or clean.get("objective") or clean.get("action_goal") or "").strip(),
        "required_artifacts": required_artifacts,
        "fallback_order": ["accessibility_and_window_metadata", "vision_detection", "ocr", "last_known_ui_target_cache"],
        "verify": True,
    }
