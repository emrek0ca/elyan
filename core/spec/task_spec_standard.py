from __future__ import annotations

import hashlib
from copy import deepcopy
from typing import Any, Dict, List

TASK_SPEC_STANDARD_VERSION = "1.2"


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen: set[str] = set()
    for item in items:
        val = str(item or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _normalize_depends(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        val = raw.strip()
        return [val] if val else []
    if isinstance(raw, list):
        return _dedupe_keep_order([str(x).strip() for x in raw if str(x).strip()])
    return []


def _step_success_criteria(step: Dict[str, Any]) -> List[str]:
    checks = step.get("checks")
    criteria: List[str] = []
    if isinstance(checks, list):
        for row in checks:
            if not isinstance(row, dict):
                continue
            ctype = str(row.get("type") or "").strip().lower()
            if ctype == "tool_success":
                criteria.append("tool_success")
            elif ctype == "file_exists":
                criteria.append("artifact_file_exists")
            elif ctype == "path_exists":
                criteria.append("artifact_path_exists")
            elif ctype == "file_not_empty":
                criteria.append("artifact_file_not_empty")
            elif ctype == "contains":
                expected = str(row.get("text") or "").strip()
                criteria.append(f"output_contains:{expected}" if expected else "output_contains")
            elif ctype == "http_status":
                expected = row.get("expected")
                criteria.append(f"http_status:{expected}" if expected is not None else "http_status")
            elif ctype:
                criteria.append(f"check:{ctype}")
    if not criteria:
        desc = str(step.get("description") or "").strip()
        if desc:
            criteria.append(f"step_completed:{desc[:120]}")
    if not criteria:
        criteria.append("step_completed")
    return _dedupe_keep_order(criteria)


def _derive_task_id(spec: Dict[str, Any], *, user_input: str = "", intent_payload: Dict[str, Any] | None = None) -> str:
    existing = str(spec.get("task_id") or "").strip()
    if existing:
        return existing
    action = ""
    if isinstance(intent_payload, dict):
        action = str(intent_payload.get("action") or "").strip()
    if not action:
        steps = spec.get("steps")
        if isinstance(steps, list) and steps and isinstance(steps[0], dict):
            action = str(steps[0].get("action") or "").strip()
    goal = str(spec.get("goal") or user_input or "task").strip()
    seed = f"{action}|{goal}"[:400]
    digest = hashlib.sha1(seed.encode("utf-8")).hexdigest()[:10]
    prefix = action.lower().strip() or "task"
    return f"{prefix}_{digest}"


def _normalize_string_list(raw: Any) -> List[str]:
    if isinstance(raw, list):
        return _dedupe_keep_order([str(x).strip() for x in raw if str(x).strip()])
    if isinstance(raw, str) and raw.strip():
        return [raw.strip()]
    return []


def _derive_entities(slots: Dict[str, Any], *, user_input: str = "") -> Dict[str, Any]:
    entities: Dict[str, Any] = {}
    if isinstance(slots, dict):
        for key, value in slots.items():
            if value is None:
                continue
            if isinstance(value, str):
                value = value.strip()
                if not value:
                    continue
            entities[key] = value
    if not entities and str(user_input or "").strip():
        entities["raw_input"] = str(user_input or "").strip()
    return entities


def _derive_deliverables(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    artifacts = spec.get("artifacts_expected")
    if isinstance(artifacts, list):
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or "").strip()
            kind = str(item.get("type") or "").strip().lower() or "file"
            if not path:
                continue
            out.append(
                {
                    "name": path.split("/")[-1] or path,
                    "kind": kind,
                    "required": bool(item.get("must_exist", True)),
                }
            )
    if out:
        return out

    steps = spec.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            action = str(step.get("action") or "").strip().lower()
            path = str(step.get("path") or ((step.get("params") or {}).get("path") if isinstance(step.get("params"), dict) else "") or "").strip()
            if path:
                out.append({"name": path.split("/")[-1] or path, "kind": "file", "required": True})
                continue
            if action:
                out.append({"name": action, "kind": "response", "required": True})
    if out:
        return out[:5]
    goal = str(spec.get("goal") or "").strip() or "task_output"
    return [{"name": goal[:80], "kind": "response", "required": True}]


def _derive_tool_candidates(spec: Dict[str, Any]) -> List[str]:
    tools = _normalize_string_list(spec.get("tool_candidates"))
    if tools:
        return tools
    required = _normalize_string_list(spec.get("required_tools"))
    if required:
        return required
    steps = spec.get("steps")
    if isinstance(steps, list):
        actions = []
        for step in steps:
            if isinstance(step, dict):
                action = str(step.get("action") or "").strip()
                if action:
                    actions.append(action)
        tools = _dedupe_keep_order(actions)
    return tools or ["respond"]


def _infer_priority(spec: Dict[str, Any], *, user_input: str = "") -> str:
    raw = str(spec.get("priority") or "").strip().lower()
    if raw in {"low", "normal", "high", "critical"}:
        return raw
    constraints = spec.get("constraints") if isinstance(spec.get("constraints"), dict) else {}
    urgency = str(constraints.get("urgency") or "").strip().lower()
    if urgency in {"critical", "high"}:
        return "critical" if urgency == "critical" else "high"
    low = f"{spec.get('goal') or ''} {user_input or ''}".lower()
    if any(tok in low for tok in ("acil", "hemen", "ivedi", "urgent", "kritik")):
        return "high"
    return "normal"


def _infer_risk_level(spec: Dict[str, Any], *, intent_payload: Dict[str, Any] | None = None) -> str:
    raw = str(spec.get("risk_level") or "").strip().lower()
    if raw in {"low", "med", "high", "guarded", "dangerous"}:
        return raw
    actions: List[str] = []
    if isinstance(intent_payload, dict):
        act = str(intent_payload.get("action") or "").strip().lower()
        if act:
            actions.append(act)
    steps = spec.get("steps")
    if isinstance(steps, list):
        actions.extend(str(step.get("action") or "").strip().lower() for step in steps if isinstance(step, dict))
    joined = " ".join(actions)
    if any(tok in joined for tok in ("run_safe_command", "delete", "shutdown", "restart")):
        return "guarded"
    if any(tok in joined for tok in ("type_text", "mouse_click", "computer_use")):
        return "med"
    if any(tok in joined for tok in ("open_app", "key_combo", "press_key")):
        return "low"
    return "low"


def extract_slots_from_intent(intent: Dict[str, Any] | None) -> Dict[str, Any]:
    payload = intent if isinstance(intent, dict) else {}
    params = payload.get("params") if isinstance(payload.get("params"), dict) else {}
    slots: Dict[str, Any] = {}
    action = str(payload.get("action") or "").strip()
    if action:
        slots["action"] = action

    for key in (
        "app_name",
        "browser",
        "url",
        "path",
        "directory",
        "query",
        "topic",
        "text",
        "command",
        "combo",
        "method",
    ):
        if key not in params:
            continue
        value = params.get(key)
        if isinstance(value, str):
            value = value.strip()
            if not value:
                continue
        if value is None:
            continue
        slots[key] = value

    tasks = payload.get("tasks")
    if isinstance(tasks, list) and tasks:
        slots["task_count"] = len(tasks)
    return slots


def _derive_root_success_criteria(spec: Dict[str, Any]) -> List[str]:
    criteria: List[str] = []
    steps = spec.get("steps")
    if isinstance(steps, list):
        for step in steps:
            if not isinstance(step, dict):
                continue
            step_criteria = step.get("success_criteria")
            if isinstance(step_criteria, list):
                criteria.extend([str(x).strip() for x in step_criteria if str(x).strip()])
    artifacts = spec.get("artifacts_expected")
    if isinstance(artifacts, list) and artifacts:
        criteria.append("artifacts_expected_exist")
    checks = spec.get("checks")
    if isinstance(checks, list) and checks:
        criteria.append("all_root_checks_pass")
    if not criteria:
        criteria.append("task_completed")
    return _dedupe_keep_order(criteria)


def coerce_task_spec_standard(
    task_spec: Any,
    *,
    user_input: str = "",
    intent_payload: Dict[str, Any] | None = None,
    intent_confidence: float | None = None,
) -> Dict[str, Any]:
    spec = deepcopy(task_spec) if isinstance(task_spec, dict) else {}

    if "version" not in spec or not str(spec.get("version") or "").strip():
        spec["version"] = TASK_SPEC_STANDARD_VERSION

    goal = str(spec.get("goal") or user_input or "").strip()
    if goal:
        spec["goal"] = goal
        if not str(spec.get("user_goal") or "").strip():
            spec["user_goal"] = goal

    if intent_confidence is not None and "confidence" not in spec:
        try:
            spec["confidence"] = round(float(intent_confidence), 4)
        except Exception:
            pass

    slots = spec.get("slots")
    if not isinstance(slots, dict):
        slots = {}
    if not slots and isinstance(intent_payload, dict):
        slots = extract_slots_from_intent(intent_payload)
    if not slots and str(user_input or "").strip():
        slots = {"raw_input": str(user_input or "").strip()}
    spec["slots"] = slots
    spec["entities"] = dict(spec.get("entities") or {}) if isinstance(spec.get("entities"), dict) else _derive_entities(slots, user_input=user_input)

    raw_steps = spec.get("steps")
    steps = raw_steps if isinstance(raw_steps, list) else []
    normalized_steps: List[Dict[str, Any]] = []
    known_ids: List[str] = []

    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            continue
        item = dict(step)
        step_id = str(item.get("id") or "").strip() or f"step_{idx}"
        item["id"] = step_id
        known_ids.append(step_id)

        if not isinstance(item.get("params"), dict):
            item["params"] = {}
        item["depends_on"] = _normalize_depends(item.get("depends_on") if item.get("depends_on") is not None else item.get("dependencies"))

        s_criteria = item.get("success_criteria")
        if not isinstance(s_criteria, list) or not s_criteria:
            item["success_criteria"] = _step_success_criteria(item)
        else:
            item["success_criteria"] = _dedupe_keep_order([str(x).strip() for x in s_criteria if str(x).strip()])
        normalized_steps.append(item)

    known = set(known_ids)
    for step in normalized_steps:
        deps = _normalize_depends(step.get("depends_on"))
        step["depends_on"] = [d for d in deps if d in known and d != str(step.get("id") or "")]

    spec["steps"] = normalized_steps
    spec["task_id"] = _derive_task_id(spec, user_input=user_input, intent_payload=intent_payload)

    if not isinstance(spec.get("constraints"), dict):
        spec["constraints"] = {}
    if not isinstance(spec.get("context_assumptions"), list):
        spec["context_assumptions"] = []
    if not isinstance(spec.get("artifacts_expected"), list):
        spec["artifacts_expected"] = []
    if not isinstance(spec.get("checks"), list):
        spec["checks"] = []
    if not isinstance(spec.get("rollback"), list):
        spec["rollback"] = []
    if not isinstance(spec.get("retries"), dict):
        spec["retries"] = {"max_attempts": 1}
    else:
        spec["retries"].setdefault("max_attempts", 1)
    if not isinstance(spec.get("timeouts"), dict):
        spec["timeouts"] = {"step_timeout_s": 90, "run_timeout_s": 600}
    else:
        spec["timeouts"].setdefault("step_timeout_s", 90)
        spec["timeouts"].setdefault("run_timeout_s", 600)

    spec["tool_candidates"] = _derive_tool_candidates(spec)
    if not isinstance(spec.get("required_tools"), list) or not spec.get("required_tools"):
        spec["required_tools"] = list(spec.get("tool_candidates") or [])
    else:
        spec["required_tools"] = _normalize_string_list(spec.get("required_tools"))
    spec["deliverables"] = spec.get("deliverables") if isinstance(spec.get("deliverables"), list) and spec.get("deliverables") else _derive_deliverables(spec)
    spec["priority"] = _infer_priority(spec, user_input=user_input)
    spec["risk_level"] = _infer_risk_level(spec, intent_payload=intent_payload)

    root_criteria = spec.get("success_criteria")
    if not isinstance(root_criteria, list) or not root_criteria:
        spec["success_criteria"] = _derive_root_success_criteria(spec)
    else:
        spec["success_criteria"] = _dedupe_keep_order([str(x).strip() for x in root_criteria if str(x).strip()])

    return spec


__all__ = [
    "TASK_SPEC_STANDARD_VERSION",
    "coerce_task_spec_standard",
    "extract_slots_from_intent",
]
