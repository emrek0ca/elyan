from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

TASK_SPEC_SCHEMA_VERSION = "1.2"
_SCHEMA_PATH = Path(__file__).with_name("task_spec.schema.json")
_CACHED_SCHEMA: Dict[str, Any] | None = None

_ALLOWED_INTENTS = {
    "filesystem_batch",
    "api_batch",
    "automation_batch",
    "office_batch",
    "coding_batch",
    "research_batch",
    "general_batch",
}
_ALLOWED_ACTIONS = {
    "mkdir",
    "write_file",
    "verify_file",
    "report_artifacts",
    "api_health_check",
    "http_request",
    "graphql_query",
    "read_file",
    "list_files",
    "edit_text_file",
    "batch_edit_text",
    "edit_word_document",
    "summarize_document",
    "analyze_document",
    "summarize_document_rag",
    "document_rag_qa",
    "analyze_document_rag",
    "build_document_rag_index",
    "analyze_document_vision",
    "extract_tables_from_document",
    "extract_charts_from_document",
    "run_safe_command",
    "summarize_text",
    "generate_report",
    "advanced_research",
    "research_document_delivery",
    "create_automation",
    "type_text",
    "press_key",
    "key_combo",
    "mouse_move",
    "mouse_click",
    "computer_use",
    "create_coding_project",
}
_PATH_REQUIRED_ACTIONS = {"mkdir", "write_file", "verify_file", "report_artifacts", "read_file", "list_files", "edit_text_file", "edit_word_document", "summarize_document", "analyze_document", "summarize_document_rag", "analyze_document_rag"}
_PARAMS_REQUIRED_ACTIONS = {
    "api_health_check",
    "http_request",
    "graphql_query",
    "run_safe_command",
    "edit_text_file",
    "batch_edit_text",
    "edit_word_document",
    "summarize_document",
    "analyze_document",
    "summarize_document_rag",
    "document_rag_qa",
    "analyze_document_rag",
    "build_document_rag_index",
    "analyze_document_vision",
    "extract_tables_from_document",
    "extract_charts_from_document",
    "summarize_text",
    "generate_report",
    "advanced_research",
    "research_document_delivery",
    "create_automation",
    "type_text",
    "press_key",
    "key_combo",
    "mouse_move",
    "mouse_click",
    "computer_use",
    "create_coding_project",
}
_ALLOWED_CHECK_TYPES = {
    "tool_success",
    "file_exists",
    "path_exists",
    "file_not_empty",
    "contains",
    "http_status",
    "response_present",
    "artifact_paths_nonempty",
    "exit_code",
    "json_valid",
}

_CODING_REQUIRED_FIELDS = (
    "execution_mode",
    "repo_snapshot",
    "coding_contract",
    "style_intent",
    "required_gates",
    "evidence_requirements",
    "allowed_write_paths",
    "forbidden_write_paths",
    "claim_policy",
)


def _step_path(step: Dict[str, Any], params: Dict[str, Any]) -> str:
    direct = str(step.get("path") or "").strip()
    if direct:
        return direct
    return str(params.get("path") or "").strip()


def _step_content(step: Dict[str, Any], params: Dict[str, Any]) -> str:
    direct = str(step.get("content") or "").strip()
    if direct:
        return direct
    return str(params.get("content") or "").strip()


def load_task_spec_schema() -> Dict[str, Any]:
    global _CACHED_SCHEMA
    if _CACHED_SCHEMA is not None:
        return _CACHED_SCHEMA
    try:
        _CACHED_SCHEMA = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except Exception:
        _CACHED_SCHEMA = {}
    return _CACHED_SCHEMA


def _validate_checks(checks: Any, prefix: str, errors: List[str]) -> None:
    if not isinstance(checks, list):
        errors.append(f"invalid:{prefix}")
        return
    for cidx, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            errors.append(f"invalid:{prefix}[{cidx}]")
            continue
        ctype = str(check.get("type") or "").strip().lower()
        if not ctype:
            errors.append(f"missing:{prefix}[{cidx}].type")
            continue
        if ctype not in _ALLOWED_CHECK_TYPES:
            errors.append(f"invalid:{prefix}[{cidx}].type:{ctype}")


def _has_dependency_cycle(deps_by_step: Dict[str, List[str]]) -> bool:
    visiting: set[str] = set()
    visited: set[str] = set()

    def _dfs(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        for dep in deps_by_step.get(node, []):
            if dep and _dfs(dep):
                return True
        visiting.remove(node)
        visited.add(node)
        return False

    for node in deps_by_step.keys():
        if _dfs(node):
            return True
    return False


def _manual_validate(task_spec: Any) -> Tuple[bool, List[str]]:
    errors: List[str] = []
    if not isinstance(task_spec, dict):
        return False, ["spec_not_dict"]

    required_root = (
        "task_id",
        "intent",
        "version",
        "goal",
        "user_goal",
        "entities",
        "deliverables",
        "constraints",
        "context_assumptions",
        "artifacts_expected",
        "checks",
        "rollback",
        "required_tools",
        "tool_candidates",
        "priority",
        "risk_level",
        "success_criteria",
        "timeouts",
        "retries",
        "steps",
    )
    for key in required_root:
        if key not in task_spec:
            errors.append(f"missing:{key}")

    task_id = str(task_spec.get("task_id") or "").strip()
    if not task_id:
        errors.append("invalid:task_id")
    intent = str(task_spec.get("intent") or "").strip().lower()
    if intent not in _ALLOWED_INTENTS:
        errors.append("invalid:intent")
    version = str(task_spec.get("version") or "").strip()
    if not version:
        errors.append("invalid:version")
    goal = str(task_spec.get("goal") or "").strip()
    if not goal:
        errors.append("invalid:goal")
    user_goal = str(task_spec.get("user_goal") or "").strip()
    if not user_goal:
        errors.append("invalid:user_goal")
    slots = task_spec.get("slots")
    if slots is not None and not isinstance(slots, dict):
        errors.append("invalid:slots")
    entities = task_spec.get("entities")
    if not isinstance(entities, dict):
        errors.append("invalid:entities")
    success_criteria_root = task_spec.get("success_criteria")
    if not isinstance(success_criteria_root, list) or not success_criteria_root:
        errors.append("invalid:success_criteria")
    elif any(not str(x or "").strip() for x in success_criteria_root):
        errors.append("invalid:success_criteria.item")

    if not isinstance(task_spec.get("constraints"), dict):
        errors.append("invalid:constraints")
    if not isinstance(task_spec.get("context_assumptions"), list):
        errors.append("invalid:context_assumptions")
    if not isinstance(task_spec.get("artifacts_expected"), list):
        errors.append("invalid:artifacts_expected")
    if not isinstance(task_spec.get("checks"), list):
        errors.append("invalid:checks")
    if not isinstance(task_spec.get("rollback"), list):
        errors.append("invalid:rollback")
    deliverables = task_spec.get("deliverables")
    if not isinstance(deliverables, list) or not deliverables:
        errors.append("invalid:deliverables")
    else:
        for didx, item in enumerate(deliverables, start=1):
            if not isinstance(item, dict):
                errors.append(f"invalid:deliverables[{didx}]")
                continue
            name = str(item.get("name") or "").strip()
            kind = str(item.get("kind") or "").strip().lower()
            required = item.get("required")
            if not name:
                errors.append(f"missing:deliverables[{didx}].name")
            if kind not in {"file", "directory", "response", "report", "document", "artifact"}:
                errors.append(f"invalid:deliverables[{didx}].kind")
            if not isinstance(required, bool):
                errors.append(f"invalid:deliverables[{didx}].required")

    artifacts_expected = task_spec.get("artifacts_expected")
    if isinstance(artifacts_expected, list):
        for aidx, artifact in enumerate(artifacts_expected, start=1):
            if not isinstance(artifact, dict):
                errors.append(f"invalid:artifacts_expected[{aidx}]")
                continue
            path = str(artifact.get("path") or "").strip()
            atype = str(artifact.get("type") or "").strip().lower()
            must_exist = artifact.get("must_exist")
            if not path:
                errors.append(f"missing:artifacts_expected[{aidx}].path")
            if atype not in {"file", "directory"}:
                errors.append(f"invalid:artifacts_expected[{aidx}].type")
            if not isinstance(must_exist, bool):
                errors.append(f"invalid:artifacts_expected[{aidx}].must_exist")

    tools = task_spec.get("required_tools")
    if not isinstance(tools, list) or not tools:
        errors.append("invalid:required_tools")
    elif any(not str(t or "").strip() for t in tools):
        errors.append("invalid:required_tools.item")
    tool_candidates = task_spec.get("tool_candidates")
    if not isinstance(tool_candidates, list) or not tool_candidates:
        errors.append("invalid:tool_candidates")
    elif any(not str(t or "").strip() for t in tool_candidates):
        errors.append("invalid:tool_candidates.item")

    priority = str(task_spec.get("priority") or "").strip().lower()
    if priority not in {"low", "normal", "high", "critical"}:
        errors.append("invalid:priority")

    risk = str(task_spec.get("risk_level") or "").strip().lower()
    if risk not in {"low", "med", "high", "guarded", "dangerous"}:
        errors.append("invalid:risk_level")

    if intent == "coding_batch":
        for key in _CODING_REQUIRED_FIELDS:
            if key not in task_spec:
                errors.append(f"missing:{key}")
        execution_mode = str(task_spec.get("execution_mode") or "").strip()
        if not execution_mode:
            errors.append("invalid:execution_mode")
        repo_snapshot = task_spec.get("repo_snapshot")
        if not isinstance(repo_snapshot, dict):
            errors.append("invalid:repo_snapshot")
        else:
            if not str(repo_snapshot.get("repo_type") or "").strip():
                errors.append("missing:repo_snapshot.repo_type")
            if not str(repo_snapshot.get("root_path") or "").strip():
                errors.append("missing:repo_snapshot.root_path")
        coding_contract = task_spec.get("coding_contract")
        if not isinstance(coding_contract, dict):
            errors.append("invalid:coding_contract")
        else:
            if not str(coding_contract.get("adapter_id") or coding_contract.get("adapter") or "").strip():
                errors.append("missing:coding_contract.adapter_id")
        style_intent = task_spec.get("style_intent")
        if not isinstance(style_intent, dict):
            errors.append("invalid:style_intent")
        elif not str(style_intent.get("visual_direction") or "").strip():
            errors.append("missing:style_intent.visual_direction")
        required_gates = task_spec.get("required_gates")
        if not isinstance(required_gates, list):
            errors.append("invalid:required_gates")
        evidence_requirements = task_spec.get("evidence_requirements")
        if not isinstance(evidence_requirements, list) or not evidence_requirements:
            errors.append("invalid:evidence_requirements")
        allowed_write_paths = task_spec.get("allowed_write_paths")
        if not isinstance(allowed_write_paths, list) or not allowed_write_paths:
            errors.append("invalid:allowed_write_paths")
        forbidden_write_paths = task_spec.get("forbidden_write_paths")
        if not isinstance(forbidden_write_paths, list):
            errors.append("invalid:forbidden_write_paths")
        if not isinstance(task_spec.get("claim_policy"), dict):
            errors.append("invalid:claim_policy")

    timeouts = task_spec.get("timeouts")
    if not isinstance(timeouts, dict):
        errors.append("invalid:timeouts")
    else:
        step_timeout = int(timeouts.get("step_timeout_s") or 0)
        run_timeout = int(timeouts.get("run_timeout_s") or 0)
        if step_timeout <= 0:
            errors.append("invalid:timeouts.step_timeout_s")
        if run_timeout <= 0:
            errors.append("invalid:timeouts.run_timeout_s")
        if step_timeout > 0 and run_timeout > 0 and run_timeout < step_timeout:
            errors.append("invalid:timeouts.run_timeout_lt_step_timeout")

    retries = task_spec.get("retries")
    if not isinstance(retries, dict):
        errors.append("invalid:retries")
    else:
        max_attempts = int(retries.get("max_attempts") or -1)
        if max_attempts < 0:
            errors.append("invalid:retries.max_attempts")
        if max_attempts > 4:
            errors.append("invalid:retries.max_attempts_too_large")

    steps = task_spec.get("steps")
    if not isinstance(steps, list) or not steps:
        errors.append("invalid:steps")
        return False, errors

    step_ids: set[str] = set()
    deps_by_step: Dict[str, List[str]] = {}

    for idx, step in enumerate(steps, start=1):
        if not isinstance(step, dict):
            errors.append(f"invalid:steps[{idx}]")
            continue
        step_id = str(step.get("id") or "").strip()
        action = str(step.get("action") or "").strip().lower()
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        path = _step_path(step, params)

        if not step_id:
            errors.append(f"missing:steps[{idx}].id")
        elif step_id in step_ids:
            errors.append(f"duplicate:steps.id:{step_id}")
        else:
            step_ids.add(step_id)
        if action not in _ALLOWED_ACTIONS:
            errors.append(f"invalid:steps[{idx}].action")
        if action in _PATH_REQUIRED_ACTIONS and not path:
            errors.append(f"missing:steps[{idx}].path")
        if action in _PARAMS_REQUIRED_ACTIONS and not params:
            errors.append(f"missing:steps[{idx}].params")
        if action == "write_file":
            content = _step_content(step, params)
            if len(content) < 3:
                errors.append(f"invalid:steps[{idx}].content_too_short")
        if action == "edit_text_file":
            operations = params.get("operations")
            if not isinstance(operations, list) or not operations:
                errors.append(f"invalid:steps[{idx}].params.operations")
        if action == "batch_edit_text":
            directory = str(params.get("directory") or "").strip()
            pattern = str(params.get("pattern") or "").strip()
            operations = params.get("operations")
            if not directory:
                errors.append(f"missing:steps[{idx}].params.directory")
            if not pattern:
                errors.append(f"missing:steps[{idx}].params.pattern")
            if not isinstance(operations, list) or not operations:
                errors.append(f"invalid:steps[{idx}].params.operations")
        if action == "edit_word_document":
            operations = params.get("operations")
            if not isinstance(operations, list) or not operations:
                errors.append(f"invalid:steps[{idx}].params.operations")
        if action == "summarize_document":
            has_content = bool(str(params.get("content") or "").strip())
            has_path = bool(path)
            if not has_path and not has_content:
                errors.append(f"missing:steps[{idx}].path_or_params.content")
        if action == "summarize_document_rag":
            has_content = bool(str(params.get("content") or "").strip())
            has_path = bool(path)
            if not has_path and not has_content:
                errors.append(f"missing:steps[{idx}].path_or_params.content")
        if action == "analyze_document_vision":
            has_content = bool(str(params.get("content") or "").strip())
            has_path = bool(path)
            if not has_path and not has_content:
                errors.append(f"missing:steps[{idx}].path_or_params.content")
        if action == "extract_tables_from_document":
            has_content = bool(str(params.get("content") or "").strip())
            has_path = bool(path)
            if not has_path and not has_content:
                errors.append(f"missing:steps[{idx}].path_or_params.content")
        if action == "extract_charts_from_document":
            has_content = bool(str(params.get("content") or "").strip())
            has_path = bool(path)
            if not has_path and not has_content:
                errors.append(f"missing:steps[{idx}].path_or_params.content")
        if action == "document_rag_qa":
            has_content = bool(str(params.get("content") or "").strip())
            has_path = bool(path)
            question = str(params.get("question") or "").strip()
            if not has_path and not has_content:
                errors.append(f"missing:steps[{idx}].path_or_params.content")
            if not question:
                errors.append(f"missing:steps[{idx}].params.question")
        if action == "build_document_rag_index":
            paths = params.get("paths")
            if not isinstance(paths, list) or not paths:
                errors.append(f"missing:steps[{idx}].params.paths")
        if action == "api_health_check":
            url = str(params.get("url") or "").strip()
            if not url:
                errors.append(f"missing:steps[{idx}].params.url")
        if action == "http_request":
            url = str(params.get("url") or "").strip()
            method = str(params.get("method") or "").strip()
            if not url:
                errors.append(f"missing:steps[{idx}].params.url")
            if not method:
                errors.append(f"missing:steps[{idx}].params.method")
        if action == "create_coding_project":
            project_name = str(params.get("project_name") or "").strip()
            brief = str(params.get("brief") or "").strip()
            if not project_name:
                errors.append(f"missing:steps[{idx}].params.project_name")
            if not brief:
                errors.append(f"missing:steps[{idx}].params.brief")
        if action == "graphql_query":
            url = str(params.get("url") or "").strip()
            query = str(params.get("query") or "").strip()
            if not url:
                errors.append(f"missing:steps[{idx}].params.url")
            if not query:
                errors.append(f"missing:steps[{idx}].params.query")
        if "checks" in step:
            _validate_checks(step.get("checks"), f"steps[{idx}].checks", errors)
            step_checks = step.get("checks")
            if isinstance(step_checks, list):
                for cidx, check in enumerate(step_checks, start=1):
                    if not isinstance(check, dict):
                        continue
                    ctype = str(check.get("type") or "").strip().lower()
                    if ctype == "contains":
                        expected = str(check.get("text") or step.get("expect_contains") or "").strip()
                        if not expected:
                            errors.append(f"invalid:steps[{idx}].checks[{cidx}].contains_text")
        if "success_criteria" in step:
            step_criteria = step.get("success_criteria")
            if not isinstance(step_criteria, list):
                errors.append(f"invalid:steps[{idx}].success_criteria")
            elif any(not str(x or "").strip() for x in step_criteria):
                errors.append(f"invalid:steps[{idx}].success_criteria.item")

        raw_deps = step.get("depends_on") if step.get("depends_on") is not None else step.get("dependencies")
        deps: List[str] = []
        if isinstance(raw_deps, str):
            dep = raw_deps.strip()
            if dep:
                deps = [dep]
        elif isinstance(raw_deps, list):
            deps = [str(x).strip() for x in raw_deps if str(x).strip()]
        elif raw_deps is not None:
            errors.append(f"invalid:steps[{idx}].depends_on")
        if step_id:
            deps_by_step[step_id] = deps

    for step_id, deps in deps_by_step.items():
        for dep in deps:
            if dep == step_id:
                errors.append(f"invalid:steps.depends_on.self:{step_id}")
            elif dep not in step_ids:
                errors.append(f"invalid:steps.depends_on.unknown:{step_id}->{dep}")
    if not any(e.startswith("invalid:steps.depends_on.unknown:") for e in errors) and _has_dependency_cycle(deps_by_step):
        errors.append("invalid:steps.depends_on.cycle")

    checks_payload = task_spec.get("checks")
    if isinstance(checks_payload, list):
        for ridx, item in enumerate(checks_payload, start=1):
            if not isinstance(item, dict):
                errors.append(f"invalid:checks[{ridx}]")
                continue
            sid = str(item.get("step_id") or "").strip()
            if not sid:
                errors.append(f"missing:checks[{ridx}].step_id")
            elif sid not in step_ids:
                errors.append(f"invalid:checks[{ridx}].step_id:{sid}")
            _validate_checks(item.get("checks"), f"checks[{ridx}].checks", errors)

    return len(errors) == 0, errors


def validate_task_spec(task_spec: Any, *, strict_schema: bool = False) -> Tuple[bool, List[str]]:
    ok, errors = _manual_validate(task_spec)
    if not ok:
        return False, errors

    if not strict_schema:
        return True, []

    schema = load_task_spec_schema()
    if not schema:
        return False, ["schema_unavailable"]
    try:
        import jsonschema  # type: ignore

        jsonschema.validate(instance=task_spec, schema=schema)
        return True, []
    except Exception as exc:
        return False, [f"schema_validation_failed:{exc}"]
