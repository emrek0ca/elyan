from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class GenericToolInput(BaseModel):
    model_config = ConfigDict(extra="allow")


class GenericToolOutput(BaseModel):
    success: bool | None = None
    output: str | None = None
    path: str | None = None


class WriteFileInput(BaseModel):
    path: str
    content: str


class WriteFileOutput(BaseModel):
    success: bool
    path: str
    size: int | None = None
    bytes_written: int | None = None
    sha256: str | None = None
    preview_200_chars: str | None = None


class WebScaffoldOutput(BaseModel):
    success: bool
    path: str
    files_created: list[str] = []
    bytes_written: int | None = None


_TOOL_INPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "write_file": WriteFileInput,
    "edit_text_file": GenericToolInput,
    "run_safe_command": GenericToolInput,
    "take_screenshot": GenericToolInput,
    "http_request": GenericToolInput,
}

_TOOL_OUTPUT_SCHEMAS: dict[str, type[BaseModel]] = {
    "write_file": WriteFileOutput,
    "edit_text_file": GenericToolOutput,
    "take_screenshot": GenericToolOutput,
    "http_request": GenericToolOutput,
    "create_web_project_scaffold": WebScaffoldOutput,
}


@dataclass
class TypedValidationResult:
    ok: bool
    errors: list[str]


def validate_tool_io(tool_name: str, params: dict[str, Any], result: Any) -> TypedValidationResult:
    errors: list[str] = []
    in_schema = _TOOL_INPUT_SCHEMAS.get(tool_name)
    out_schema = _TOOL_OUTPUT_SCHEMAS.get(tool_name)

    if in_schema is not None:
        try:
            in_schema.model_validate(params or {})
        except ValidationError as exc:
            errors.append(f"input_schema:{exc.errors()[:2]}")

    if out_schema is not None:
        payload = result if isinstance(result, dict) else {"output": str(result)}
        try:
            out_schema.model_validate(payload)
        except ValidationError as exc:
            errors.append(f"output_schema:{exc.errors()[:2]}")

    return TypedValidationResult(ok=not errors, errors=errors)


def detect_artifact_mismatch(*, expected_extensions: list[str], produced_paths: list[str]) -> list[str]:
    exts = {str(e).lower().strip() for e in (expected_extensions or []) if str(e).strip()}
    if not exts:
        return []
    mismatches: list[str] = []
    for path in produced_paths or []:
        low = str(path or "").lower()
        if not low:
            continue
        if not any(low.endswith(ext if ext.startswith(".") else f".{ext}") for ext in exts):
            mismatches.append(str(path))
    return mismatches


def collect_paths_from_tool_results(tool_results: list[dict[str, Any]]) -> list[str]:
    def _walk(payload: Any, out: list[str], *, depth: int = 0) -> None:
        if depth > 4 or not isinstance(payload, dict):
            return
        for key in ("path", "file_path", "output_path", "delivery_dir"):
            val = payload.get(key)
            if isinstance(val, str) and val.strip():
                out.append(val.strip())
        for key in ("outputs", "artifacts", "report_paths", "files_created"):
            val = payload.get(key)
            if isinstance(val, list):
                for item in val:
                    if isinstance(item, str) and item.strip():
                        out.append(item.strip())
                    elif isinstance(item, dict):
                        path_val = item.get("path")
                        if isinstance(path_val, str) and path_val.strip():
                            out.append(path_val.strip())
        for key in ("result", "raw"):
            nested = payload.get(key)
            if isinstance(nested, dict) and nested is not payload:
                _walk(nested, out, depth=depth + 1)

    paths: list[str] = []
    for row in tool_results or []:
        if not isinstance(row, dict):
            continue
        _walk(row, paths)
    return list(dict.fromkeys(paths))


def decide_orchestration_policy(
    *,
    complexity_score: float,
    parallelizable: bool,
    default_threshold: float = 0.82,
    team_threshold: float = 0.9,
) -> dict[str, Any]:
    c = max(0.0, min(1.0, float(complexity_score or 0.0)))
    if parallelizable and c >= team_threshold:
        bucket = 3 if c >= 0.92 else 2
        max_agents = min(3, bucket)
        return {
            "mode": "team_mode",
            "max_agents": max_agents,
            "token_budget": 6000 * max_agents,
            "time_budget_s": 180 * max_agents,
        }
    if parallelizable and c >= default_threshold:
        bucket = 3 if c >= 0.9 else (2 if c >= 0.75 else 1)
        max_agents = min(3, bucket)
        return {
            "mode": "multi_agent",
            "max_agents": max_agents,
            "token_budget": 4500 * max_agents,
            "time_budget_s": 120 * max_agents,
        }
    return {"mode": "single_agent_cdg", "max_agents": 1, "token_budget": 2500, "time_budget_s": 120}


def fallback_ladder() -> list[str]:
    return [
        "same_plan_different_model",
        "reduced_minimal_plan",
        "deterministic_tool_macro",
        "ask_user",
    ]


def diff_only_failed_steps(plan: list[dict[str, Any]], failed_step_ids: list[str]) -> list[dict[str, Any]]:
    failed = {str(x) for x in (failed_step_ids or [])}
    if not failed:
        return list(plan or [])
    return [step for step in (plan or []) if str(step.get("id") or "") in failed]
