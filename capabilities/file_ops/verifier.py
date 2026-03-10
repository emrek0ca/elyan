from __future__ import annotations

from pathlib import Path
from typing import Any

from core.pipeline_upgrade.executor import collect_paths_from_tool_results


def verify_file_ops_runtime(ctx: Any) -> dict[str, Any]:
    action = str(getattr(ctx, "action", "") or "").strip().lower()
    intent = getattr(ctx, "intent", {}) if isinstance(getattr(ctx, "intent", {}), dict) else {}
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    expected_path = str(
        params.get("path")
        or params.get("target_path")
        or params.get("destination")
        or params.get("source")
        or ""
    ).strip()
    produced_paths = collect_paths_from_tool_results([r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)])
    checks: list[dict[str, Any]] = []
    failed: list[str] = []

    if action == "create_folder":
        exists = bool(expected_path and Path(expected_path).expanduser().exists())
        checks.append({"check": "folder_exists", "passed": exists, "path": expected_path})
        if not exists:
            failed.append("folder_exists")
        correct_name = bool(expected_path and Path(expected_path).name and any(Path(p).name == Path(expected_path).name for p in produced_paths + [expected_path]))
        checks.append({"check": "correct_name", "passed": correct_name, "expected_name": Path(expected_path).name if expected_path else ""})
        if not correct_name:
            failed.append("correct_name")

    if action in {"write_file", "write_word", "write_excel"}:
        resolved = Path(expected_path).expanduser() if expected_path else None
        exists = bool(resolved and resolved.exists())
        non_empty = bool(exists and resolved and resolved.is_file() and resolved.stat().st_size > 0)
        checks.append({"check": "file_exists", "passed": exists, "path": expected_path})
        checks.append({"check": "file_non_empty", "passed": non_empty, "path": expected_path})
        if not exists:
            failed.append("file_exists")
        if exists and not non_empty:
            failed.append("file_non_empty")

    return {
        "capability": "file_ops",
        "ok": len(failed) == 0,
        "checks": checks,
        "failed": failed,
        "produced_paths": produced_paths,
    }

