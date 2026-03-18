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


def verify_research_gates(
    *,
    final_response: str,
    source_urls: list[str],
    research_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    text = str(final_response or "")
    low = text.replace("İ", "I").lower()
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
    if research_payload is not None:
        payload_ok, payload_errors = validate_research_payload(research_payload)
        if not payload_ok:
            failed.extend([f"payload:{err}" for err in payload_errors])
        quality_summary = research_payload.get("quality_summary") if isinstance(research_payload, dict) else {}
        if isinstance(quality_summary, dict) and quality_summary:
            try:
                critical_coverage = float(quality_summary.get("critical_claim_coverage", 0.0) or 0.0)
            except Exception:
                critical_coverage = 0.0
            if critical_coverage < 1.0:
                failed.append("critical_claim_coverage")
    return {
        "ok": not failed,
        "failed": failed,
        "source_count": len(source_urls),
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
