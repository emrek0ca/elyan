from __future__ import annotations

from pathlib import Path
from typing import Any


_WRITE_ACTIONS = {"write_file", "write_word", "write_excel", "copy_file", "move_file"}
_READ_ACTIONS = {"read_file", "list_files"}
_DIR_ACTIONS = {"create_folder"}


def build_file_ops_contract(*, action: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    clean = dict(params or {})
    action_name = str(action or "").strip().lower()
    target_path = str(clean.get("path") or clean.get("target_path") or clean.get("destination") or "").strip()
    source_path = str(clean.get("source") or "").strip()
    required_artifacts: list[str] = []
    required_checks: list[str] = []

    if action_name in _WRITE_ACTIONS:
        required_artifacts = ["touched_path", "file_manifest"]
        required_checks = ["path_exists", "non_empty", "checksum_recorded"]
    elif action_name in _DIR_ACTIONS:
        required_artifacts = ["touched_path"]
        required_checks = ["path_exists", "directory_created"]
    elif action_name in _READ_ACTIONS:
        required_artifacts = ["request_trace"]
        required_checks = ["request_path_resolved"]
    else:
        required_artifacts = ["request_trace"]
        required_checks = ["operation_observed"]

    return {
        "capability": "file_ops",
        "workflow_id": "file_ops.runtime.v3",
        "action": action_name,
        "target_path": target_path,
        "source_path": source_path,
        "file_name": Path(target_path).name if target_path else "",
        "required_artifacts": required_artifacts,
        "required_checks": required_checks,
        "verify": True,
    }
