from __future__ import annotations

from collections import OrderedDict
from typing import Any


def _safe_text(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


_SIDE_EFFECT_CAPABILITIES = {
    "open_app",
    "close_app",
    "shell_run",
    "browser_control",
    "play_media",
    "add_calendar_event",
    "delete_calendar_event",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "email_send",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
    "run_skill",
    "mcp_call_tool",
    "desktop_operator.focus_window",
    "desktop_operator.execute_action",
    "desktop_operator.run",
}

_APPROVAL_CAPABILITIES = {
    "shell_run",
    "add_calendar_event",
    "delete_calendar_event",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "email_send",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "canvas_write",
    "run_skill",
    "mcp_call_tool",
    "browser_control",
    "play_media",
    "desktop_operator.focus_window",
    "desktop_operator.execute_action",
    "desktop_operator.run",
}

_ROLE_BY_CAPABILITY: dict[str, str] = {
    # Observation and truth gathering
    "sys_info": "observer",
    "web_research": "observer",
    "retrieve_context": "observer",
    "document_read": "observer",
    "ocr_read": "observer",
    "image_read": "observer",
    "image_fetch": "observer",
    "file_read": "observer",
    "file_search": "observer",
    "directory_tree": "observer",
    "analyze_screen": "observer",
    "data_analyze": "observer",
    "text_analyze": "analyzer",
    "chart_generate": "observer",
    "desktop_os.status": "observer",
    "desktop_os.permissions": "observer",
    "desktop_os.processes": "observer",
    "desktop_os.active_window": "observer",
    # Desktop / OS execution
    "open_app": "operator",
    "close_app": "operator",
    "shell_run": "operator",
    "run_skill": "operator",
    "mcp_call_tool": "operator",
    "desktop_operator.observe_screen": "operator",
    "desktop_operator.locate": "operator",
    "desktop_operator.focus_window": "operator",
    "desktop_operator.execute_action": "operator",
    "desktop_operator.run": "operator",
    "desktop_operator.cancel": "operator",
    # Browser and media handoff
    "browser_control": "browser",
    "play_media": "browser",
    # Artifact creation
    "document_write": "writer",
    "spreadsheet_write": "writer",
    "presentation_write": "writer",
    "canvas_write": "writer",
    # Personal and outbound communication
    "send_whatsapp_message": "communicator",
    "save_whatsapp_contact": "communicator",
    "email_draft": "communicator",
    "email_send": "communicator",
    "add_calendar_event": "communicator",
    "add_reminder": "communicator",
    # Voice / speech
    "speech_to_text": "voice",
    "text_to_speech": "voice",
    # Symbolic work
    "math_solve": "analyzer",
    "latex_parse": "analyzer",
    "quantum_model_problem": "analyzer",
    "quantum_run_experiment": "analyzer",
    "quantum_compare_classical": "analyzer",
    "quantum_generate_report": "writer",
}


def _capability_phase(capability: str, role: str) -> str:
    normalized = str(capability or "").strip().lower()
    if normalized in {"retrieve_context", "web_research", "document_read", "ocr_read", "image_read", "data_analyze", "chart_generate", "sys_info"}:
        return "gather"
    if normalized in {"math_solve", "latex_parse", "text_analyze", "quantum_model_problem", "quantum_run_experiment", "quantum_compare_classical"}:
        return "reason"
    if normalized in {"document_write", "spreadsheet_write", "presentation_write", "canvas_write", "email_draft", "quantum_generate_report"}:
        return "compose"
    if normalized.startswith("desktop_operator.") or role in {"operator", "browser", "communicator", "voice"}:
        return "act"
    return "act"


def agent_role_for_capability(capability: str) -> str:
    normalized = str(capability or "").strip().lower()
    if not normalized:
        return "operator"
    return _ROLE_BY_CAPABILITY.get(normalized, "operator")


def build_agent_plan(steps: list[dict[str, Any]], *, summary: str = "") -> dict[str, Any]:
    normalized_steps = [dict(step) for step in steps if isinstance(step, dict)]
    step_roles: list[dict[str, Any]] = []
    role_breakdown: "OrderedDict[str, list[str]]" = OrderedDict()
    phase_breakdown: "OrderedDict[str, list[str]]" = OrderedDict()
    capabilities: list[str] = []
    requires_approval = False
    has_side_effect = False

    for index, step in enumerate(normalized_steps, start=1):
        capability = str(step.get("capability", "") or "").strip()
        if not capability:
            continue
        role = agent_role_for_capability(capability)
        phase = _capability_phase(capability, role)
        side_effect = capability in _SIDE_EFFECT_CAPABILITIES
        approval_required = capability in _APPROVAL_CAPABILITIES
        has_side_effect = has_side_effect or side_effect
        requires_approval = requires_approval or approval_required
        step_roles.append({
            "id": str(step.get("id", "") or f"step_{index}"),
            "index": index,
            "capability": capability,
            "role": role,
            "phase": phase,
            "description": _safe_text(step.get("description", "") or capability),
            "sideEffect": side_effect,
            "approvalRequired": approval_required,
        })
        if capability not in capabilities:
            capabilities.append(capability)
        role_breakdown.setdefault(role, []).append(capability)
        phase_breakdown.setdefault(phase, []).append(capability)

    agent_roles: list[str] = ["planner"]
    for role in role_breakdown:
        if role not in agent_roles:
            agent_roles.append(role)

    lane_count = len(agent_roles)
    if lane_count <= 1:
        execution_strategy = "single_lane"
    elif lane_count == 2:
        execution_strategy = "balanced"
    else:
        execution_strategy = "multi_lane"
    if requires_approval:
        risk_level = "approval_required"
    elif has_side_effect:
        risk_level = "side_effect"
    else:
        risk_level = "read_only"

    return {
        "summary": _safe_text(summary),
        "stepCount": len(step_roles),
        "capabilities": capabilities,
        "stepRoles": step_roles,
        "agentRoles": agent_roles,
        "roleBreakdown": [
            {
                "role": role,
                "stepCount": len(capability_list),
                "capabilities": list(capability_list),
            }
            for role, capability_list in role_breakdown.items()
        ],
        "phases": [
            {
                "phase": phase,
                "stepCount": len(capability_list),
                "capabilities": list(capability_list),
            }
            for phase, capability_list in phase_breakdown.items()
        ],
        "laneCount": lane_count,
        "executionStrategy": execution_strategy,
        "riskLevel": risk_level,
        "requiresApproval": requires_approval,
    }
