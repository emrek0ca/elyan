from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = "elyan.desktop_work_order.v1"
MAX_STEPS = 8
_SOURCE_HASH_RE = re.compile(r"^[a-f0-9]{24}$")
_CONTENT_HASH_RE = re.compile(r"^(?:sha256:)?[a-f0-9]{64}$", re.IGNORECASE)
_ALLOWED_OUTPUT_KINDS = {"chat_result", "artifact", "file_update", "browser_state", "system_state"}
_ALLOWED_EVIDENCE = {"runtime_status", "tool_result", "artifact", "state_readback"}


def canonical_capability(value: Any) -> str:
    normalized = " ".join(str(value or "").strip().lower().split()).replace(" ", "_")
    aliases = {
        "document.read": "document_read",
        "document.write": "document_write",
        "document.export": "document_write",
        "spreadsheet.write": "spreadsheet_write",
        "table.generate": "spreadsheet_write",
        "chart.generate": "chart_generate",
        "image.read": "image_read",
        "image.generate": "image_generate",
        "svg.generate": "canvas_write",
        "browser.read": "browser_control",
        "desktop.file_access": "document_read",
        "desktop.runtime": "desktop_operator.run",
        "filesystem_read": "document_read",
        "filesystem_write": "document_write",
        "screen_context": "desktop_operator.observe_screen",
        "app_control": "desktop_operator.run",
        "computer_control": "desktop_operator.run",
        "computer.control": "desktop_operator.run",
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized.startswith("desktop.operator."):
        return "desktop_operator." + normalized.removeprefix("desktop.operator.")
    if normalized.startswith(("desktop_operator.", "desktop_os.")):
        return normalized
    return normalized.replace(".", "_")


def _safe_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


@dataclass(frozen=True)
class WorkOrderValidation:
    work_order: dict[str, Any] | None
    errors: tuple[dict[str, str], ...]

    @property
    def ok(self) -> bool:
        return self.work_order is not None and not self.errors


def _error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _tool_event_succeeded(event: dict[str, Any]) -> bool:
    return event.get("ok") is True and not str(event.get("errorCode", "") or "").strip()


def _artifact_has_evidence(artifact: dict[str, Any]) -> bool:
    for key in ("contentHash", "content_hash", "sha256", "checksum"):
        value = str(artifact.get(key, "") or "").strip()
        if _CONTENT_HASH_RE.fullmatch(value):
            return True

    path_value = str(artifact.get("path", "") or artifact.get("outputPath", "") or "").strip()
    if path_value:
        try:
            path = Path(path_value).expanduser()
            return path.is_file()
        except (OSError, RuntimeError, ValueError):
            return False

    return artifact.get("verified") is True and bool(
        str(artifact.get("id", "") or artifact.get("artifactId", "") or artifact.get("localRef", "")).strip()
    )


def _structured_file_update_verified(structured: dict[str, Any]) -> bool:
    if structured.get("created") is True or structured.get("updated") is True:
        return True
    kind = str(structured.get("kind", "") or "").strip().lower()
    if kind == "image_fetch":
        try:
            return int(structured.get("savedCount", 0) or 0) > 0
        except (TypeError, ValueError):
            return False
    return False


def validate_payload(payload: dict[str, Any]) -> WorkOrderValidation:
    candidate = payload.get("desktopWorkOrder")
    if candidate is None:
        return WorkOrderValidation(None, ())
    if not isinstance(candidate, dict):
        return WorkOrderValidation(None, (_error("WORK_ORDER_INVALID", "desktopWorkOrder", "Work order nesne olmalı."),))

    errors: list[dict[str, str]] = []
    if candidate.get("schema") != SCHEMA:
        errors.append(_error("WORK_ORDER_SCHEMA_UNSUPPORTED", "desktopWorkOrder.schema", "Work order şeması desteklenmiyor."))

    goal = candidate.get("goal")
    if not isinstance(goal, dict):
        errors.append(_error("WORK_ORDER_GOAL_MISSING", "desktopWorkOrder.goal", "Tipli görev amacı eksik."))
        goal = {}
    summary = _safe_text(goal.get("summary"), 1000)
    if not summary:
        errors.append(_error("WORK_ORDER_GOAL_MISSING", "desktopWorkOrder.goal.summary", "Görev özeti eksik."))
    source_hash = str(goal.get("sourceTextHash", "") or "").strip()
    if not _SOURCE_HASH_RE.fullmatch(source_hash):
        errors.append(_error("WORK_ORDER_SOURCE_HASH_INVALID", "desktopWorkOrder.goal.sourceTextHash", "Kaynak özeti hash'i geçersiz."))

    execution = candidate.get("execution")
    if not isinstance(execution, dict):
        errors.append(_error("WORK_ORDER_EXECUTION_MISSING", "desktopWorkOrder.execution", "Yürütme politikası eksik."))
        execution = {}
    if execution.get("mode") != "cowork_dispatch":
        errors.append(_error("WORK_ORDER_MODE_INVALID", "desktopWorkOrder.execution.mode", "Yürütme modu geçersiz."))
    try:
        max_steps = int(execution.get("maxSteps", MAX_STEPS) or MAX_STEPS)
    except (TypeError, ValueError):
        max_steps = MAX_STEPS + 1
    if max_steps < 1 or max_steps > MAX_STEPS:
        errors.append(_error("WORK_ORDER_STEP_BUDGET_INVALID", "desktopWorkOrder.execution.maxSteps", "Adım bütçesi 1-8 arasında olmalı."))

    preview = candidate.get("planPreview")
    if not isinstance(preview, dict):
        errors.append(_error("WORK_ORDER_PLAN_MISSING", "desktopWorkOrder.planPreview", "Tipli yürütme planı eksik."))
        preview = {}
    raw_steps = preview.get("steps")
    if not isinstance(raw_steps, list):
        errors.append(_error("WORK_ORDER_STEPS_INVALID", "desktopWorkOrder.planPreview.steps", "Plan adımları dizi olmalı."))
        raw_steps = []
    if len(raw_steps) > min(max_steps, MAX_STEPS):
        errors.append(_error("WORK_ORDER_STEP_BUDGET_EXCEEDED", "desktopWorkOrder.planPreview.steps", "Plan adım bütçesini aşıyor."))

    normalized_steps: list[dict[str, Any]] = []
    step_ids: set[str] = set()
    for index, raw_step in enumerate(raw_steps[:MAX_STEPS]):
        path = f"desktopWorkOrder.planPreview.steps.{index}"
        if not isinstance(raw_step, dict):
            errors.append(_error("WORK_ORDER_STEP_INVALID", path, "Plan adımı nesne olmalı."))
            continue
        step_id = _safe_text(raw_step.get("id") or f"step_{index + 1}", 80)
        capability = canonical_capability(raw_step.get("capability"))
        args = raw_step.get("args")
        if not step_id or step_id in step_ids:
            errors.append(_error("WORK_ORDER_STEP_ID_INVALID", f"{path}.id", "Plan adımı kimliği boş veya tekrarlı."))
            continue
        if not capability:
            errors.append(_error("WORK_ORDER_CAPABILITY_MISSING", f"{path}.capability", "Plan adımı capability alanı eksik."))
            continue
        if not isinstance(args, dict):
            errors.append(_error("WORK_ORDER_ARGS_INVALID", f"{path}.args", "Plan adımı args alanı nesne olmalı."))
            continue
        step_ids.add(step_id)
        normalized_steps.append({
            **raw_step,
            "id": step_id,
            "capability": capability,
            "description": _safe_text(raw_step.get("description") or capability, 240),
            "args": dict(args),
        })

    required_capabilities: list[str] = []
    raw_capabilities = candidate.get("requiredCapabilities")
    if not isinstance(raw_capabilities, list):
        errors.append(_error("WORK_ORDER_CAPABILITIES_INVALID", "desktopWorkOrder.requiredCapabilities", "Capability listesi geçersiz."))
        raw_capabilities = []
    for raw_capability in raw_capabilities[:24]:
        capability = canonical_capability(raw_capability)
        if capability and capability not in required_capabilities:
            required_capabilities.append(capability)
    for step in normalized_steps:
        capability = step["capability"]
        if capability not in required_capabilities:
            required_capabilities.append(capability)

    expected_outputs = candidate.get("expectedOutputs")
    if not isinstance(expected_outputs, list):
        errors.append(_error("WORK_ORDER_OUTPUTS_INVALID", "desktopWorkOrder.expectedOutputs", "Beklenen çıktı listesi geçersiz."))
        expected_outputs = []
    normalized_outputs: list[dict[str, Any]] = []
    for index, output in enumerate(expected_outputs[:12]):
        if not isinstance(output, dict) or output.get("kind") not in _ALLOWED_OUTPUT_KINDS:
            errors.append(_error("WORK_ORDER_OUTPUT_INVALID", f"desktopWorkOrder.expectedOutputs.{index}", "Beklenen çıktı türü geçersiz."))
            continue
        normalized_outputs.append({
            "kind": str(output["kind"]),
            "format": _safe_text(output.get("format"), 80),
            "required": bool(output.get("required", False)),
        })

    rules = candidate.get("verificationRules")
    if not isinstance(rules, list):
        errors.append(_error("WORK_ORDER_VERIFICATION_INVALID", "desktopWorkOrder.verificationRules", "Doğrulama kuralları geçersiz."))
        rules = []
    normalized_rules: list[dict[str, str]] = []
    for index, rule in enumerate(rules[:16]):
        if not isinstance(rule, dict) or rule.get("evidence") not in _ALLOWED_EVIDENCE:
            errors.append(_error("WORK_ORDER_VERIFICATION_RULE_INVALID", f"desktopWorkOrder.verificationRules.{index}", "Kanıt türü geçersiz."))
            continue
        normalized_rules.append({
            "id": _safe_text(rule.get("id") or f"rule_{index + 1}", 80),
            "description": _safe_text(rule.get("description"), 240),
            "evidence": str(rule["evidence"]),
        })

    if errors:
        return WorkOrderValidation(None, tuple(errors))

    normalized = {
        **candidate,
        "goal": {**goal, "summary": summary},
        "requiredCapabilities": required_capabilities,
        "expectedOutputs": normalized_outputs,
        "verificationRules": normalized_rules,
        "execution": {**execution, "maxSteps": max_steps},
        "planPreview": {**preview, "steps": normalized_steps},
    }
    return WorkOrderValidation(normalized, ())


def verify_result(work_order: dict[str, Any], local_result: dict[str, Any]) -> dict[str, Any]:
    artifacts = [item for item in local_result.get("artifacts", []) if isinstance(item, dict)] if isinstance(local_result.get("artifacts"), list) else []
    tool_events = [item for item in local_result.get("toolEvents", []) if isinstance(item, dict)] if isinstance(local_result.get("toolEvents"), list) else []
    successful_tool_events = [item for item in tool_events if _tool_event_succeeded(item)]
    verified_artifacts = [item for item in artifacts if _artifact_has_evidence(item)]
    # "prove it": bir adım başarı döndürse (ok) de iddia ettiği yan etki
    # gerçekten gözlenemediyse (stateReadback.observed=False — ör. "kapatıldı"
    # dedi ama süreç hâlâ ayakta), görev bunu tamamlandı sayamaz.
    readback_observed = False
    unverified_side_effects: list[str] = []
    for item in tool_events:
        readback = item.get("stateReadback")
        if not isinstance(readback, dict):
            continue
        if readback.get("observed") is True:
            readback_observed = True
        elif item.get("ok") is True and readback.get("observed") is False:
            unverified_side_effects.append(str(item.get("tool", "") or "capability"))
    structured = local_result.get("structuredResult")
    structured = structured if isinstance(structured, dict) else {}
    assistant_message = _safe_text(local_result.get("assistantMessage"), 1000)
    execution_trace = local_result.get("executionTrace")
    execution_trace = execution_trace if isinstance(execution_trace, dict) else {}
    existing_verification = local_result.get("verification")
    existing_verification = existing_verification if isinstance(existing_verification, dict) else {}

    evidence = {
        "runtime_status": local_result.get("chatOk") is True,
        "tool_result": bool(successful_tool_events) or existing_verification.get("status") in {"passed", "repaired"},
        "artifact": bool(verified_artifacts),
        "state_readback": structured.get("stateVerified") is True
        or structured.get("readBackVerified") is True
        or execution_trace.get("stateVerified") is True
        or readback_observed,
    }
    # A chat-only work order can complete without emitting a tool event (for
    # example, a local runtime answer assembled from an already completed
    # action). Keep artifact/file/state work orders strict, but do not turn a
    # completed runtime trace into WORK_ORDER_EVIDENCE_MISSING solely because
    # the tool event transport was empty.
    required_output_kinds = {
        str(output.get("kind", "") or "")
        for output in work_order.get("expectedOutputs", [])
        if isinstance(output, dict) and output.get("required") is True
    }
    chat_only = required_output_kinds <= {"chat_result"}
    runtime_trace_completed = str(execution_trace.get("status", "") or "").strip().lower() in {
        "completed",
        "done",
        "success",
    }
    visible_result = bool(assistant_message or structured or local_result.get("blocks"))
    evidence_fallbacks: list[dict[str, str]] = []
    if (
        not evidence["tool_result"]
        and chat_only
        and evidence["runtime_status"]
        and runtime_trace_completed
        and visible_result
    ):
        evidence["tool_result"] = True
        evidence_fallbacks.append({
            "kind": "tool_result",
            "source": "runtime_status",
            "reason": "chat_only_runtime_completion",
        })
    checks: list[dict[str, Any]] = []
    missing: list[str] = []

    for output in work_order.get("expectedOutputs", []):
        if not isinstance(output, dict) or output.get("required") is not True:
            continue
        kind = str(output.get("kind", "") or "")
        passed = True
        if kind == "chat_result":
            passed = evidence["runtime_status"] and bool(assistant_message or structured or local_result.get("blocks"))
        elif kind == "artifact":
            passed = evidence["artifact"]
        elif kind == "file_update":
            passed = evidence["artifact"] and _structured_file_update_verified(structured)
        elif kind in {"browser_state", "system_state"}:
            passed = evidence["tool_result"] or evidence["state_readback"]
        checks.append({"id": f"output:{kind}", "passed": passed})
        if not passed:
            missing.append(f"output:{kind}")

    for rule in work_order.get("verificationRules", []):
        if not isinstance(rule, dict):
            continue
        evidence_kind = str(rule.get("evidence", "") or "")
        if evidence_kind == "artifact" and not any(
            isinstance(output, dict) and output.get("required") is True and output.get("kind") in {"artifact", "file_update"}
            for output in work_order.get("expectedOutputs", [])
        ):
            passed = True
        else:
            passed = bool(evidence.get(evidence_kind, False))
        rule_id = str(rule.get("id", "") or evidence_kind)
        checks.append({"id": f"rule:{rule_id}", "passed": passed, "evidence": evidence_kind})
        if not passed:
            missing.append(f"rule:{rule_id}")

    # Gözlenemeyen yan etkiler her koşulda doğrulamayı düşürür: bir adım
    # "yaptım" (ok) deyip etkiyi kanıtlayamadıysa görev tamamlandı sayılmaz.
    for tool_name in unverified_side_effects:
        check_id = f"sideeffect:{tool_name}"
        checks.append({"id": check_id, "passed": False, "evidence": "state_readback"})
        missing.append(check_id)

    passed_count = sum(1 for check in checks if check.get("passed") is True)
    confidence = 1.0 if not checks else round(passed_count / len(checks), 3)
    return {
        "status": "passed" if not missing else "failed",
        "passed": not missing,
        "confidence": confidence,
        "checks": checks,
        "evidenceCounts": {
            "toolResults": len(successful_tool_events),
            "artifacts": len(verified_artifacts),
            "structuredResults": 1 if structured else 0,
            "stateReadbacks": sum(
                1
                for item in tool_events
                if isinstance(item.get("stateReadback"), dict)
                and item["stateReadback"].get("observed") is True
            ),
        },
        "evidenceFallbacks": evidence_fallbacks,
        "unverifiedSideEffects": unverified_side_effects,
        "missingEvidence": missing,
    }
