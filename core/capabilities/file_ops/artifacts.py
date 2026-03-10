from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from core.contracts.tool_result import coerce_tool_result


_EXTRA_PATH_KEYS = ("path", "file_path", "output_path", "destination", "source")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _append_manifest_row(out: list[dict[str, Any]], raw_path: str, *, tool: str, source_result: dict[str, Any] | None = None) -> None:
    clean = str(raw_path or "").strip()
    if not clean:
        return
    try:
        path = Path(clean).expanduser()
    except Exception:
        return
    exists = path.exists()
    row = {
        "path": str(path),
        "name": path.name,
        "exists": exists,
        "is_dir": bool(exists and path.is_dir()),
        "tool": tool,
    }
    if exists and path.is_file():
        row["size_bytes"] = int(path.stat().st_size)
        row["sha256"] = _sha256(path)
    if isinstance(source_result, dict) and source_result:
        row["source_result"] = dict(source_result)
    if not any(item.get("path") == row["path"] for item in out):
        out.append(row)


def collect_file_ops_artifacts(tool_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    manifest: list[dict[str, Any]] = []
    for row in tool_results or []:
        if not isinstance(row, dict):
            continue
        tool_name = str(row.get("tool") or row.get("action") or "").strip()
        normalized = coerce_tool_result(row, tool=tool_name, source="capability_runtime")
        for artifact in list(normalized.artifacts or []):
            _append_manifest_row(manifest, artifact.path, tool=tool_name, source_result=row)
        for key in _EXTRA_PATH_KEYS:
            value = row.get(key)
            if isinstance(value, str):
                _append_manifest_row(manifest, value, tool=tool_name, source_result=row)
            nested = row.get("result") if isinstance(row.get("result"), dict) else {}
            nested_value = nested.get(key)
            if isinstance(nested_value, str):
                _append_manifest_row(manifest, nested_value, tool=tool_name, source_result=nested)
    return manifest
