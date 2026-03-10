from __future__ import annotations

from pathlib import Path
from typing import Any

from core.contracts.failure_taxonomy import FailureCode
from core.contracts.verification_result import VerificationCheck, VerificationResult

from .artifacts import collect_file_ops_artifacts
from .schema import build_file_ops_contract


_WRITE_ACTIONS = {"write_file", "write_word", "write_excel", "copy_file", "move_file"}
_DIR_ACTIONS = {"create_folder"}
_READ_ACTIONS = {"read_file", "list_files"}


def _first_existing(manifest: list[dict[str, Any]], path: str) -> dict[str, Any] | None:
    target = str(path or "").strip()
    for item in manifest:
        if str(item.get("path") or "") == target:
            return item
    return None


def verify_file_ops_runtime(ctx: Any) -> dict[str, Any]:
    action = str(getattr(ctx, "action", "") or "").strip().lower()
    intent = getattr(ctx, "intent", {}) if isinstance(getattr(ctx, "intent", {}), dict) else {}
    params = intent.get("params", {}) if isinstance(intent.get("params"), dict) else {}
    contract = build_file_ops_contract(action=action, params=params)
    target_path = str(contract.get("target_path") or "").strip()
    manifest = collect_file_ops_artifacts([r for r in list(getattr(ctx, "tool_results", []) or []) if isinstance(r, dict)])

    checks: list[VerificationCheck] = []
    evidence_refs = [{"type": "artifact_manifest", "count": len(manifest)}]

    if action in _DIR_ACTIONS:
        exists = bool(target_path and Path(target_path).expanduser().exists())
        checks.append(VerificationCheck(code="folder_exists", passed=exists, details={"path": target_path}))
        checks.append(
            VerificationCheck(
                code="directory_created",
                passed=bool(target_path and Path(target_path).expanduser().is_dir()),
                details={"path": target_path},
            )
        )
    elif action in _WRITE_ACTIONS:
        item = _first_existing(manifest, target_path)
        exists = bool(item and item.get("exists"))
        non_empty = bool(item and int(item.get("size_bytes") or 0) > 0)
        checksum_recorded = bool(item and str(item.get("sha256") or "").strip())
        checks.extend(
            [
                VerificationCheck(code="path_exists", passed=exists, details={"path": target_path}),
                VerificationCheck(code="non_empty", passed=non_empty, details={"path": target_path, "size_bytes": int(item.get("size_bytes") or 0) if item else 0}),
                VerificationCheck(code="checksum_recorded", passed=checksum_recorded, details={"path": target_path}),
            ]
        )
    elif action in _READ_ACTIONS:
        path_resolved = bool(target_path or action == "list_files")
        checks.append(VerificationCheck(code="request_path_resolved", passed=path_resolved, details={"path": target_path}))
        if action == "read_file":
            content_present = False
            for row in list(getattr(ctx, "tool_results", []) or []):
                if not isinstance(row, dict):
                    continue
                payloads = [row]
                if isinstance(row.get("result"), dict):
                    payloads.append(row["result"])
                for payload in payloads:
                    if str(payload.get("content") or "").strip():
                        content_present = True
                        break
                if content_present:
                    break
            checks.append(VerificationCheck(code="content_returned", passed=content_present, details={"path": target_path}))
    else:
        checks.append(VerificationCheck(code="operation_observed", passed=bool(manifest or getattr(ctx, "tool_results", []))))

    result = VerificationResult.from_checks(
        checks,
        summary="file_ops capability runtime verification",
        evidence_refs=evidence_refs,
        metrics={"artifact_count": len(manifest)},
        repairable=True,
    )

    failed_codes: list[str] = []
    for item in checks:
        if item.passed:
            continue
        if item.code == "non_empty":
            failed_codes.append(FailureCode.EMPTY_FILE_OUTPUT.value)
        else:
            failed_codes.append(FailureCode.ARTIFACT_MISSING.value)
    payload = result.to_dict()
    payload.update({
        "capability": "file_ops",
        "artifact_manifest": manifest,
        "failed_codes": list(dict.fromkeys(failed_codes)),
        "target_path": target_path,
    })
    return payload
