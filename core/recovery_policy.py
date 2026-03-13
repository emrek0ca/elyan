from __future__ import annotations

from typing import Any
import re


_STATE_MISMATCH_ACTIONS = {
    "key_combo",
    "type_text",
    "press_key",
    "mouse_click",
    "mouse_move",
    "open_url",
}


def _normalize_terminal_command(command: str) -> str:
    cmd = str(command or "").strip()
    if not cmd:
        return ""
    cmd = re.sub(r"\s+", " ", cmd).strip(" \t\r\n.,;:!?")
    cmd = re.sub(r"\s+\b(?:komut(?:u|unu|un)?|command)\b\s*$", "", cmd, flags=re.IGNORECASE).strip(" \t\r\n.,;:!?")
    cmd = re.sub(r"\s+(?:çalıştır|calistir|run|execute)\b\s*$", "", cmd, flags=re.IGNORECASE).strip(" \t\r\n.,;:!?")
    return cmd


def _extract_focus_app(action: str, params: dict[str, Any], result: dict[str, Any]) -> str:
    if not isinstance(params, dict):
        params = {}
    if not isinstance(result, dict):
        result = {}
    for key in ("target_app", "app_name", "browser"):
        val = str(result.get(key) or params.get(key) or "").strip()
        if val:
            return val
    if str(action or "").strip().lower() == "open_url":
        return str(params.get("browser") or "Safari").strip()
    return ""


def select_recovery_strategy(
    *,
    failure_class: str,
    action: str,
    reason: str = "",
    params: dict[str, Any] | None = None,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return deterministic recovery strategy for a failed step."""
    fc = str(failure_class or "").strip().lower()
    act = str(action or "").strip().lower()
    low_reason = str(reason or "").strip().lower()
    p = dict(params or {})
    r = dict(result or {})

    if fc == "policy_block":
        return {"kind": "fail_fast", "stop_retry": True, "note": "policy_block_fail_fast"}

    if fc == "planning_failure":
        hard_plan_markers = ("unknown_dependency", "unsupported_action", "invalid_task_spec", "döngüsel", "dongusel", "cyclic")
        if any(tok in low_reason for tok in hard_plan_markers):
            return {"kind": "fail_fast", "stop_retry": True, "note": "planning_failure_fail_fast"}
        failed_research_gates = [str(x).strip().lower() for x in list(((r.get("research_gate") or {}) if isinstance(r.get("research_gate"), dict) else {}).get("failed") or []) if str(x).strip()]
        research_repair_steps = [str(x).strip() for x in list(r.get("research_repair_steps") or []) if str(x).strip()]
        if failed_research_gates and research_repair_steps:
            if any(item in {"sources", "claim_mapping", "unknowns"} or item.startswith("payload:") for item in failed_research_gates):
                return {
                    "kind": "research_revision_plan",
                    "stop_retry": False,
                    "note": "research_revision_plan",
                }
        failed_code_gates = [str(x).strip().lower() for x in list(((r.get("code_gate") or {}) if isinstance(r.get("code_gate"), dict) else {}).get("failed") or []) if str(x).strip()]
        quality_gate_commands = [str(x).strip() for x in list(r.get("quality_gate_commands") or []) if str(x).strip()]
        if failed_code_gates and quality_gate_commands:
            if any(item in {"lint", "smoke", "typecheck"} for item in failed_code_gates):
                return {
                    "kind": "quality_gate_plan",
                    "stop_retry": False,
                    "note": "quality_gate_plan",
                }
        if act in {"write_file", "write_word", "write_excel", "research_document_delivery"}:
            task_spec = r.get("task_spec") if isinstance(r.get("task_spec"), dict) else {}
            failed = [str(x).strip().lower() for x in list(r.get("failed") or []) if str(x).strip()]
            artifact_markers = ("deliverable:", "document:missing_artifact", "document:empty_artifact", "criteria:artifact_")
            if task_spec and any(any(marker in item for marker in artifact_markers) for item in failed):
                return {
                    "kind": "replay_taskspec_artifact",
                    "stop_retry": False,
                    "note": "replay_taskspec_artifact",
                }

    if fc == "state_mismatch" and act in _STATE_MISMATCH_ACTIONS:
        app = _extract_focus_app(act, p, r)
        if app:
            return {
                "kind": "refocus_app",
                "stop_retry": False,
                "focus_app": app,
                "note": f"refocus_app:{app}",
            }

    if fc == "tool_failure" and act in {"run_safe_command", "execute_shell_command", "run_command"}:
        raw_cmd = str(p.get("command") or p.get("cmd") or "").strip()
        cleaned = _normalize_terminal_command(raw_cmd)
        if cleaned and cleaned != raw_cmd:
            return {
                "kind": "patch_params",
                "stop_retry": False,
                "params_patch": {"command": cleaned},
                "note": "normalize_terminal_command",
            }

    return {"kind": "none", "stop_retry": False, "note": ""}


__all__ = ["select_recovery_strategy"]
