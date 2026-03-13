from __future__ import annotations

from pathlib import Path
from typing import Any

from .contracts import validate_research_payload


def _iter_nested_strings(value: Any, *, _depth: int = 0):
    if _depth > 4:
        return
    if isinstance(value, str):
        yield value
        return
    if isinstance(value, dict):
        for item in value.values():
            yield from _iter_nested_strings(item, _depth=_depth + 1)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_nested_strings(item, _depth=_depth + 1)


def _collect_tool_text(tool_results: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for row in tool_results or []:
        if not isinstance(row, dict):
            continue
        for s in _iter_nested_strings(row):
            if s and len(s) > 0:
                parts.append(s)
    return "\n".join(parts).lower()


def _artifact_exists(path: str) -> bool:
    try:
        return Path(str(path or "")).expanduser().exists()
    except Exception:
        return False


def _artifact_non_empty(path: str) -> bool:
    try:
        target = Path(str(path or "")).expanduser()
        if not target.exists() or not target.is_file():
            return False
        return int(target.stat().st_size) > 0
    except Exception:
        return False


def _combined_output_text(final_response: str, tool_results: list[dict[str, Any]] | None = None) -> str:
    text = str(final_response or "").strip()
    tool_blob = _collect_tool_text(tool_results or [])
    return f"{text}\n{tool_blob}".strip().lower()


def enforce_output_contract(
    *,
    job_type: str,
    expected_extensions: list[str],
    produced_paths: list[str],
    evidence_checks: list[str],
) -> dict[str, Any]:
    j = str(job_type or "").lower()
    is_file_like = j in {"file_operations", "code_project"}
    files_created_min = len(produced_paths)
    non_empty = True
    for p in produced_paths:
        try:
            if Path(p).exists() and Path(p).is_file() and Path(p).stat().st_size == 0:
                non_empty = False
        except Exception:
            non_empty = False

    expected = [str(x).lower().strip() for x in (expected_extensions or []) if str(x).strip()]
    matched = True
    if expected:
        matched = all(any(str(p).lower().endswith(ext if ext.startswith(".") else f".{ext}") for ext in expected) for p in produced_paths)

    required_evidence = list(dict.fromkeys([str(c) for c in (evidence_checks or []) if str(c).strip()]))
    ok = True
    errors: list[str] = []

    if is_file_like and files_created_min < 1:
        ok = False
        errors.append("files_created_min")
    if is_file_like and not non_empty:
        ok = False
        errors.append("non_empty_files")
    if is_file_like and not matched:
        ok = False
        errors.append("expected_extensions")
    if is_file_like and not required_evidence:
        ok = False
        errors.append("evidence_required")

    return {
        "ok": ok,
        "errors": errors,
        "files_created_min": files_created_min,
        "non_empty_files": bool(non_empty),
        "expected_extensions_matched": bool(matched),
        "evidence_required": required_evidence,
    }


def verify_code_gates(*, final_response: str, produced_paths: list[str], tool_results: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    text = str(final_response or "").lower()
    tool_blob = _collect_tool_text(tool_results or [])
    combined = f"{text}\n{tool_blob}"
    checks = {
        "lint": any(k in combined for k in ("lint", "ruff", "flake8", "eslint", "pylint", "biome")),
        "smoke": any(
            k in combined
            for k in ("smoke", "pytest", "test passed", "run ok", "build ok", "tests passed", "npm test", "go test", "cargo test")
        ),
        "typecheck": any(k in combined for k in ("typecheck", "mypy", "pyright", "tsc", "type check")),
        "entrypoint": any(Path(p).name in {"main.py", "app.py", "index.js", "main.ts", "manage.py"} for p in (produced_paths or [])),
    }
    failed = [k for k, v in checks.items() if not v]
    return {"ok": not failed, "failed": failed, "checks": checks}


def verify_research_gates(*, final_response: str, source_urls: list[str], research_payload: dict[str, Any] | None = None) -> dict[str, Any]:
    text = str(final_response or "")
    low = text.lower()
    has_claim_map = "claim" in low or "iddia" in low
    has_unknowns = "unknown" in low or "bilinmeyen" in low or "belirs" in low
    has_sources = bool(source_urls)
    failed = []
    if not has_sources:
        failed.append("sources")
    if not has_claim_map:
        failed.append("claim_mapping")
    if not has_unknowns:
        failed.append("unknowns")
    payload_ok, payload_errors = validate_research_payload(research_payload)
    if not payload_ok:
        failed.extend([f"payload:{err}" for err in payload_errors])
    return {
        "ok": not failed,
        "failed": failed,
        "source_count": len(source_urls),
        "payload_ok": payload_ok,
    }


def verify_asset_gates(*, attachment_index: list[dict[str, Any]], safe_area_min: float = 0.85) -> dict[str, Any]:
    failed: list[str] = []
    supported = {"png", "jpg", "jpeg", "webp"}
    valid_items = 0
    dimensions_ok = 0
    safe_area_checked = 0
    safe_area_ok = 0

    def _dimensions_from_item(item: dict[str, Any]) -> tuple[int, int]:
        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width > 0 and height > 0:
            return width, height
        path = str(item.get("path") or "").strip()
        if not path:
            return 0, 0
        try:
            from PIL import Image

            with Image.open(path) as img:
                w, h = img.size
                return int(w or 0), int(h or 0)
        except Exception:
            return 0, 0

    for item in attachment_index or []:
        if not isinstance(item, dict):
            continue
        typ = str(item.get("type") or "").lower()
        size = int(item.get("size_bytes") or 0)
        if typ in supported and size > 0:
            valid_items += 1
            w, h = _dimensions_from_item(item)
            if w > 0 and h > 0:
                dimensions_ok += 1

            # Enforce safe-area only when ratio is provided by upstream tools/indexers.
            ratio = item.get("safe_area_ratio")
            if ratio is not None:
                safe_area_checked += 1
                try:
                    if float(ratio) >= float(safe_area_min):
                        safe_area_ok += 1
                except Exception:
                    pass

    if valid_items == 0:
        failed.append("asset_format_or_size")
    elif dimensions_ok < valid_items:
        failed.append("dimensions")

    if safe_area_checked > 0 and safe_area_ok < safe_area_checked:
        failed.append("safe_area")

    return {
        "ok": not failed,
        "failed": failed,
        "valid_assets": valid_items,
        "dimensions_checked": dimensions_ok,
        "safe_area_checked": safe_area_checked,
        "safe_area_passed": safe_area_ok,
    }


def verify_taskspec_contract(
    *,
    task_spec: dict[str, Any] | None,
    job_type: str,
    final_response: str,
    tool_results: list[dict[str, Any]] | None = None,
    produced_paths: list[str] | None = None,
) -> dict[str, Any]:
    spec = task_spec if isinstance(task_spec, dict) else {}
    produced = [str(p).strip() for p in (produced_paths or []) if str(p).strip()]
    combined = _combined_output_text(final_response, tool_results)
    artifacts_expected = spec.get("artifacts_expected") if isinstance(spec.get("artifacts_expected"), list) else []
    deliverables = spec.get("deliverables") if isinstance(spec.get("deliverables"), list) else []
    criteria = spec.get("success_criteria") if isinstance(spec.get("success_criteria"), list) else []
    checks = spec.get("checks") if isinstance(spec.get("checks"), list) else []

    failed: list[str] = []
    criteria_results: dict[str, bool] = {}
    deliverable_results: list[dict[str, Any]] = []
    required_artifacts = [item for item in artifacts_expected if isinstance(item, dict) and bool(item.get("must_exist", False))]

    has_successful_tool = any(
        isinstance(row, dict) and not (isinstance(row.get("success"), bool) and row.get("success") is False)
        for row in (tool_results or [])
    )
    has_nonempty_response = bool(str(final_response or "").strip())

    for item in deliverables:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "").strip().lower()
        required = bool(item.get("required", True))
        name = str(item.get("name") or "").strip()
        ok = True
        if kind in {"file", "directory", "document", "report", "artifact"}:
            ok = bool(produced or required_artifacts)
        elif kind == "response":
            ok = has_nonempty_response
        if required and not ok:
            failed.append(f"deliverable:{name or kind}")
        deliverable_results.append({"name": name, "kind": kind, "required": required, "ok": ok})

    for criterion in [str(x).strip() for x in criteria if str(x).strip()]:
        ok = True
        if criterion == "task_completed":
            ok = has_successful_tool or has_nonempty_response
        elif criterion == "artifacts_expected_exist":
            ok = all(_artifact_exists(str(item.get("path") or "")) for item in required_artifacts)
        elif criterion == "all_root_checks_pass":
            ok = bool(checks or not spec)
        elif criterion == "tool_success":
            ok = has_successful_tool
        elif criterion == "artifact_file_exists":
            ok = any(_artifact_exists(path) for path in produced) or any(
                _artifact_exists(str(item.get("path") or "")) for item in required_artifacts
            )
        elif criterion == "artifact_path_exists":
            ok = any(_artifact_exists(path) for path in produced) or any(
                _artifact_exists(str(item.get("path") or "")) for item in required_artifacts
            )
        elif criterion == "artifact_file_not_empty":
            ok = any(_artifact_non_empty(path) for path in produced) or any(
                _artifact_non_empty(str(item.get("path") or "")) for item in required_artifacts
            )
        elif criterion.startswith("output_contains:"):
            expected = criterion.split(":", 1)[1].strip().lower()
            ok = bool(expected and expected in combined)
        elif criterion.startswith("step_completed:"):
            ok = has_successful_tool
        criteria_results[criterion] = bool(ok)
        if not ok:
            failed.append(f"criteria:{criterion}")

    profile = "generic"
    profile_failed: list[str] = []
    low_job = str(job_type or "").strip().lower()
    low_intent = str(spec.get("intent") or "").strip().lower()
    if low_job == "code_project" or low_intent == "coding_batch":
        profile = "code"
        if not produced:
            profile_failed.append("code:no_artifacts")
    elif low_intent == "research_batch" or low_job == "data_analysis":
        profile = "research"
        if not has_nonempty_response:
            profile_failed.append("research:empty_response")
    elif low_intent in {"office_batch", "filesystem_batch"} or low_job == "file_operations":
        profile = "document"
        if required_artifacts and not all(_artifact_exists(str(item.get("path") or "")) for item in required_artifacts):
            profile_failed.append("document:missing_artifact")
        if any(str(item.get("type") or "").strip().lower() == "file" for item in required_artifacts):
            if not all(_artifact_non_empty(str(item.get("path") or "")) for item in required_artifacts if str(item.get("type") or "").strip().lower() == "file"):
                profile_failed.append("document:empty_artifact")

    failed.extend(profile_failed)
    failed = list(dict.fromkeys([str(x).strip() for x in failed if str(x).strip()]))
    return {
        "ok": not failed,
        "profile": profile,
        "failed": failed,
        "criteria_results": criteria_results,
        "deliverables": deliverable_results,
        "artifact_count": len(produced),
        "required_artifact_count": len(required_artifacts),
    }


def build_reflexion_hint(*, verification_payload: dict[str, Any] | None, job_type: str) -> str:
    payload = verification_payload if isinstance(verification_payload, dict) else {}
    failed = [str(x).strip() for x in (payload.get("failed") or []) if str(x).strip()]
    if not failed:
        return ""
    job = str(job_type or "").strip().lower()
    head = ", ".join(failed[:4])
    if job == "code_project":
        return f"Reflexion next: artifact, test ve syntax odakli yeniden uretim gerekli ({head})."
    if job == "file_operations":
        return f"Reflexion next: dosya artifact ve icerik dogrulamasi eksik ({head})."
    if job == "data_analysis":
        return f"Reflexion next: kaynak/icerik yeterliligi yeniden gozden gecirilmeli ({head})."
    return f"Reflexion next: verify gate hatalari icin hedefli onarim gerekli ({head})."


def build_critic_review_prompt(
    *,
    job_type: str,
    final_response: str,
    qa_results: dict[str, Any] | None = None,
    errors: list[str] | None = None,
) -> str:
    job = str(job_type or "").strip().lower()
    if job not in {"code_project", "research"}:
        return ""
    payload = {
        "job_type": job,
        "qa_results": dict(qa_results or {}),
        "errors": list(errors or []),
        "response_excerpt": str(final_response or "")[:2000],
    }
    return (
        "You are Elyan critic. Evaluate the verification outcome using only the provided QA data. "
        "Return 3 short lines in Turkish: "
        "1) verdict: pass|partial|fail "
        "2) risk: one short sentence "
        "3) next: one short sentence.\n\n"
        f"{payload}"
    )
