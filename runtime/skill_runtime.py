from __future__ import annotations

import copy
import json
import re
import threading
from pathlib import Path
from typing import Any

from runtime import mcp_runtime, state_store
from runtime.capability_registry import SafeCapabilityError, capability_dependency_status


_LOCK = threading.RLock()
_IMMUTABLE_BUILTIN_IDS = {
    str(item.get("id", "") or "") for item in [
        {
            "id": "document.summary",
        },
        {
            "id": "document.bullets",
        },
        {
            "id": "document.docx_from_context",
        },
        {
            "id": "document.xlsx_from_rows",
        },
        {
            "id": "mcp.readonly_tool_proxy",
        },
    ]
}


def _utc_now_iso() -> str:
    import datetime as dt

    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _skills_root() -> Path:
    return state_store.CONFIG_DIR.parent / "skills"


def _status_path() -> Path:
    return _skills_root() / "skills_status.json"


def _safe_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _string(value: Any, *, limit: int = 240) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", _string(value, limit=120).lower())
    normalized = normalized.strip("-")
    return normalized or "skill"


def _builtin_skill_manifests() -> list[dict[str, Any]]:
    return [
        {
            "id": "document.summary",
            "name": "Document Summary",
            "description": "Belgeyi kısa özet olarak çıkarır.",
            "enabled": True,
            "category": "document",
            "requiresConfirmation": False,
            "parameters": ["path"],
            "requiredParameters": ["path"],
            "steps": [
                {
                    "capability": "document_read",
                    "description": "Belge özeti",
                    "args": {"mode": "summary"},
                    "argsFromPayload": {"path": "path"},
                }
            ],
        },
        {
            "id": "document.bullets",
            "name": "Document Bullets",
            "description": "Belgeyi maddeler halinde çıkarır.",
            "enabled": True,
            "category": "document",
            "requiresConfirmation": False,
            "parameters": ["path"],
            "requiredParameters": ["path"],
            "steps": [
                {
                    "capability": "document_read",
                    "description": "Belge maddeleri",
                    "args": {"mode": "bullets"},
                    "argsFromPayload": {"path": "path"},
                }
            ],
        },
        {
            "id": "research.brief",
            "name": "Research Brief",
            "description": "Yerel bağlam ve çalışma alanından kısa, kaynaklı araştırma özeti üretir.",
            "enabled": True,
            "category": "research",
            "requiresConfirmation": False,
            "parameters": ["query", "sources", "limit", "conversationId"],
            "requiredParameters": ["query"],
            "steps": [
                {
                    "capability": "retrieve_context",
                    "description": "Yerel bağlamı topla",
                    "argsFromPayload": {
                        "query": "query",
                        "sources": "sources",
                        "limit": "limit",
                        "conversationId": "conversationId",
                    },
                }
            ],
        },
        {
            "id": "source.verify",
            "name": "Source Verify",
            "description": "Soru için kısa kaynak kontrolü yapar.",
            "enabled": True,
            "category": "research",
            "requiresConfirmation": False,
            "parameters": ["query", "sources", "limit", "conversationId"],
            "requiredParameters": ["query"],
            "steps": [
                {
                    "capability": "retrieve_context",
                    "description": "Kaynak kontrolü",
                    "args": {"sources": "workspace,conversations", "limit": 5},
                    "argsFromPayload": {
                        "query": "query",
                        "sources": "sources",
                        "limit": "limit",
                        "conversationId": "conversationId",
                    },
                }
            ],
        },
        {
            "id": "workspace.answer",
            "name": "Workspace Answer",
            "description": "Çalışma alanından cevap hazırlamak için bağlam toplar.",
            "enabled": True,
            "category": "research",
            "requiresConfirmation": False,
            "parameters": ["query", "limit", "conversationId"],
            "requiredParameters": ["query"],
            "steps": [
                {
                    "capability": "retrieve_context",
                    "description": "Çalışma alanını tara",
                    "args": {"sources": "workspace", "limit": 6},
                    "argsFromPayload": {
                        "query": "query",
                        "limit": "limit",
                        "conversationId": "conversationId",
                    },
                }
            ],
        },
        {
            "id": "file.explain",
            "name": "File Explain",
            "description": "Belgeyi sade şekilde açıklar.",
            "enabled": True,
            "category": "document",
            "requiresConfirmation": False,
            "parameters": ["path"],
            "requiredParameters": ["path"],
            "steps": [
                {
                    "capability": "document_read",
                    "description": "Belgeyi açıkla",
                    "args": {"mode": "summary"},
                    "argsFromPayload": {"path": "path"},
                }
            ],
        },
        {
            "id": "document.report_from_context",
            "name": "Context Report",
            "description": "Bağlamı toplayıp DOCX rapora dönüştürür.",
            "enabled": True,
            "category": "document",
            "requiresConfirmation": True,
            "parameters": ["query", "outputPath", "title", "sources", "limit", "conversationId", "overwrite"],
            "requiredParameters": ["query", "outputPath"],
            "steps": [
                {
                    "capability": "retrieve_context",
                    "description": "Bağlamı topla",
                    "argsFromPayload": {
                        "query": "query",
                        "sources": "sources",
                        "limit": "limit",
                        "conversationId": "conversationId",
                    },
                },
                {
                    "capability": "document_write",
                    "description": "DOCX rapor üret",
                    "argsFromPayload": {
                        "outputPath": "outputPath",
                        "title": "title",
                        "overwrite": "overwrite",
                    },
                    "argsFromPreviousOutput": ["sourceContext"],
                },
            ],
        },
        {
            "id": "document.docx_from_context",
            "name": "DOCX From Context",
            "description": "Bağlam veya kaynak belgeden DOCX üretir.",
            "enabled": True,
            "category": "document",
            "requiresConfirmation": True,
            "parameters": [
                "prompt",
                "outputPath",
                "title",
                "sourcePath",
                "sourceContext",
                "overwrite",
            ],
            "steps": [
                {
                    "capability": "document_write",
                    "description": "DOCX üret",
                    "argsFromPayload": {
                        "prompt": "prompt",
                        "outputPath": "outputPath",
                        "title": "title",
                        "sourcePath": "sourcePath",
                        "sourceContext": "sourceContext",
                        "overwrite": "overwrite",
                    },
                }
            ],
        },
        {
            "id": "document.xlsx_from_rows",
            "name": "XLSX From Rows",
            "description": "Satırlardan XLSX üretir.",
            "enabled": True,
            "category": "document",
            "requiresConfirmation": True,
            "parameters": [
                "prompt",
                "outputPath",
                "title",
                "columns",
                "rows",
                "sourceContext",
                "overwrite",
            ],
            "steps": [
                {
                    "capability": "spreadsheet_write",
                    "description": "XLSX üret",
                    "argsFromPayload": {
                        "prompt": "prompt",
                        "outputPath": "outputPath",
                        "title": "title",
                        "columns": "columns",
                        "rows": "rows",
                        "sourceContext": "sourceContext",
                        "overwrite": "overwrite",
                    },
                }
            ],
        },
        {
            "id": "mcp.readonly_tool_proxy",
            "name": "MCP Readonly Proxy",
            "description": "Read-only MCP aracini preset olarak cagirir.",
            "enabled": True,
            "category": "mcp",
            "requiresConfirmation": False,
            "parameters": ["serverId", "toolName", "arguments"],
            "requiredParameters": ["serverId", "toolName"],
            "steps": [
                {
                    "capability": "mcp_call_tool",
                    "description": "Read-only MCP araci",
                    "argsFromPayload": {
                        "serverId": "serverId",
                        "toolName": "toolName",
                        "arguments": "arguments",
                    },
                    "requiresReadOnlyMcp": True,
                }
            ],
        },
    ]


def _builtin_skill_ids() -> set[str]:
    return {str(item.get("id", "") or "") for item in _builtin_skill_manifests()}


def _allowed_local_capabilities() -> set[str]:
    return {
        "document_read",
        "document_write",
        "spreadsheet_write",
        "presentation_write",
        "ocr_read",
        "image_read",
        "data_analyze",
        "chart_generate",
        "math_solve",
        "latex_parse",
        "retrieve_context",
        "mcp_call_tool",
        "speech_to_text",
        "text_to_speech",
    }


def _ensure_builtin_manifests() -> None:
    root = _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    for manifest in _builtin_skill_manifests():
        path = root / f"{_slug(str(manifest.get('id', '') or 'skill'))}.json"
        desired = json.dumps(manifest, indent=2, ensure_ascii=False)
        if path.exists():
            try:
                if path.read_text(encoding="utf-8") == desired:
                    continue
            except Exception:
                pass
        path.write_text(desired, encoding="utf-8")


def _load_manifest_files() -> list[Path]:
    _ensure_builtin_manifests()
    root = _skills_root()
    return sorted(root.glob("*.json"))


def _manifest_path_for_id(skill_id: str) -> Path:
    return _skills_root() / f"{_slug(skill_id)}.json"


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill manifest okunamadi.") from exc
    if not isinstance(payload, dict):
        raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill manifest gecerli degil.")
    return payload


def _normalize_steps(
    raw_steps: Any,
    *,
    skill_id: str,
    parameters: set[str],
) -> list[dict[str, Any]]:
    if not isinstance(raw_steps, list) or not raw_steps:
        raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill steps gerekli.")
    normalized: list[dict[str, Any]] = []
    for item in raw_steps:
        if not isinstance(item, dict):
            raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill step gecerli degil.")
        capability = _string(item.get("capability"), limit=80)
        if not capability:
            raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill capability gerekli.")
        if capability not in _allowed_local_capabilities():
            raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Bu capability local skill icin desteklenmiyor.")
        args = item.get("args", {})
        args = _safe_json(args if isinstance(args, dict) else {})
        args_from_payload = item.get("argsFromPayload", {})
        args_from_payload = (
            dict(args_from_payload)
            if isinstance(args_from_payload, dict)
            else {}
        )
        args_from_previous_result = item.get("argsFromPreviousResult", {})
        args_from_previous_result = (
            dict(args_from_previous_result)
            if isinstance(args_from_previous_result, dict)
            else {}
        )
        args_from_previous_output = item.get("argsFromPreviousOutput", [])
        if isinstance(args_from_previous_output, str):
            args_from_previous_output = [args_from_previous_output]
        args_from_previous_output = (
            list(args_from_previous_output)
            if isinstance(args_from_previous_output, list)
            else []
        )
        cleaned_mapping: dict[str, str] = {}
        for target_key, payload_key in args_from_payload.items():
            target_name = _string(target_key, limit=80)
            payload_name = _string(payload_key, limit=80)
            if not target_name or not payload_name:
                continue
            if payload_name not in parameters:
                raise SafeCapabilityError(
                    "SKILL_MANIFEST_INVALID",
                    f"{skill_id} icin izinli olmayan parametre kullanildi.",
                )
            cleaned_mapping[target_name] = payload_name
        normalized.append(
            {
                "capability": capability,
                "description": _string(item.get("description"), limit=160),
                "args": args,
                "argsFromPayload": cleaned_mapping,
                "argsFromPreviousResult": {
                    _string(target_key, limit=80): _string(source_key, limit=120)
                    for target_key, source_key in args_from_previous_result.items()
                    if _string(target_key, limit=80) and _string(source_key, limit=120)
                },
                "argsFromPreviousOutput": [
                    _string(target_key, limit=80)
                    for target_key in args_from_previous_output
                    if _string(target_key, limit=80)
                ],
                "requiresReadOnlyMcp": bool(item.get("requiresReadOnlyMcp", False)),
            }
        )
    return normalized


def _normalize_manifest(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    skill_id = _string(payload.get("id"), limit=120)
    if not skill_id:
        raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill id gerekli.")
    parameters = {
        _string(item, limit=80)
        for item in (payload.get("parameters") if isinstance(payload.get("parameters"), list) else [])
        if _string(item, limit=80)
    }
    required_parameters = [
        _string(item, limit=80)
        for item in (payload.get("requiredParameters") if isinstance(payload.get("requiredParameters"), list) else [])
        if _string(item, limit=80)
    ]
    for item in required_parameters:
        if item not in parameters:
            raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Required skill parameter tanimsiz.")
    steps = _normalize_steps(payload.get("steps"), skill_id=skill_id, parameters=parameters)
    return {
        "id": skill_id,
        "name": _string(payload.get("name"), limit=120) or skill_id,
        "description": _string(payload.get("description"), limit=240),
        "enabled": bool(payload.get("enabled", True)),
        "category": _string(payload.get("category"), limit=80) or "custom",
        "requiresConfirmation": bool(payload.get("requiresConfirmation", False)),
        "parameters": sorted(parameters),
        "requiredParameters": required_parameters,
        "steps": steps,
        "path": str(path),
        "source": "built_in" if path.name in {f"{_slug(item['id'])}.json" for item in _builtin_skill_manifests()} else "local",
    }


def _skill_snapshot(
    manifest: dict[str, Any],
    *,
    available: bool = True,
    last_error_code: str = "",
    last_error: str = "",
) -> dict[str, Any]:
    steps = manifest.get("steps", [])
    steps = steps if isinstance(steps, list) else []
    step_statuses = [
        capability_dependency_status(str(step.get("capability", "") or ""))
        for step in steps
        if isinstance(step, dict)
    ]
    first_failure = next((item for item in step_statuses if not bool(item.get("available", False))), {})
    step_dependencies_available = all(bool(item.get("available", False)) for item in step_statuses)
    blocked_capabilities = [
        str(item.get("capability", "") or "").strip()
        for item in step_statuses
        if not bool(item.get("available", False)) and str(item.get("capability", "") or "").strip()
    ]
    ready_steps = sum(1 for item in step_statuses if bool(item.get("available", False)))
    available = bool(available) and bool(manifest.get("enabled", True)) and step_dependencies_available
    last_error_code = last_error_code or str(first_failure.get("lastErrorCode", "") or "").strip()
    last_error = last_error or str(first_failure.get("lastErrorMessage", "") or "").strip()
    return {
        "id": str(manifest.get("id", "") or ""),
        "name": str(manifest.get("name", "") or ""),
        "description": str(manifest.get("description", "") or ""),
        "enabled": bool(manifest.get("enabled", True)),
        "category": str(manifest.get("category", "") or ""),
        "requiresConfirmation": bool(manifest.get("requiresConfirmation", False)),
        "stepCount": len(steps),
        "parameters": list(manifest.get("parameters", []) or []),
        "requiredParameters": list(manifest.get("requiredParameters", []) or []),
        "path": str(manifest.get("path", "") or ""),
        "source": str(manifest.get("source", "") or "local"),
        "available": available,
        "lastErrorCode": last_error_code,
        "lastErrorMessage": last_error,
        "dependencySummary": {
            "totalSteps": len(steps),
            "readySteps": ready_steps,
            "blockedSteps": max(0, len(steps) - ready_steps),
            "blockedCapabilities": list(dict.fromkeys(blocked_capabilities)),
        },
    }


def _persist_skill_status(status: dict[str, Any]) -> None:
    root = _skills_root()
    root.mkdir(parents=True, exist_ok=True)
    _status_path().write_text(
        json.dumps(status, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def _load_cached_status() -> dict[str, Any]:
    path = _status_path()
    if not path.exists():
        return {
            "available": True,
            "lastRefreshAt": "",
            "manifestCount": 0,
            "activeSkillCount": 0,
            "skills": [],
            "lastErrorCode": "",
            "lastErrorMessage": "",
        }
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("available", True)
    payload.setdefault("lastRefreshAt", "")
    payload.setdefault("manifestCount", 0)
    payload.setdefault("activeSkillCount", 0)
    payload.setdefault("readySkillCount", 0)
    payload.setdefault("blockedSkillCount", 0)
    payload.setdefault("skills", [])
    payload.setdefault("lastErrorCode", "")
    payload.setdefault("lastErrorMessage", "")
    return payload


def refresh_skill_runtime(state: dict[str, Any] | None = None) -> dict[str, Any]:
    with _LOCK:
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        last_error_code = ""
        last_error_message = ""
        manifests: list[dict[str, Any]] = []
        for path in _load_manifest_files():
            try:
                payload = _read_manifest(path)
                manifests.append(_normalize_manifest(path, payload))
            except SafeCapabilityError as exc:
                if not last_error_code:
                    last_error_code = exc.code
                    last_error_message = exc.message
            except Exception:
                if not last_error_code:
                    last_error_code = "SKILL_MANIFEST_INVALID"
                    last_error_message = "Skill manifest gecerli degil."
        snapshots = [_skill_snapshot(item) for item in manifests]
        enabled = [
            item
            for item in snapshots
            if bool(item.get("enabled", False)) and bool(item.get("available", False))
        ]
        if not last_error_code:
            first_unavailable = next((item for item in snapshots if not bool(item.get("available", False))), {})
            last_error_code = str(first_unavailable.get("lastErrorCode", "") or "").strip()
            last_error_message = str(first_unavailable.get("lastErrorMessage", "") or "").strip()
        status = {
            "available": True,
            "lastRefreshAt": _utc_now_iso(),
            "manifestCount": len(snapshots),
            "activeSkillCount": len(enabled),
            "readySkillCount": sum(1 for item in snapshots if bool(item.get("available", False))),
            "blockedSkillCount": sum(
                1 for item in snapshots if bool(item.get("enabled", False)) and not bool(item.get("available", False))
            ),
            "skills": snapshots,
            "lastErrorCode": last_error_code,
            "lastErrorMessage": last_error_message,
        }
        _persist_skill_status(status)
        merged_state = copy.deepcopy(current_state)
        merged_state.setdefault("skills", {})
        if not isinstance(merged_state["skills"], dict):
            merged_state["skills"] = {}
        merged_state["skills"]["activeSkills"] = enabled
        state_store.save_state(merged_state)
        return copy.deepcopy(status)


def list_skill_runtime(state: dict[str, Any] | None = None, *, refresh: bool = False) -> dict[str, Any]:
    with _LOCK:
        if refresh:
            return refresh_skill_runtime(state)
        cached = _load_cached_status()
        if str(cached.get("lastRefreshAt", "") or "").strip():
            return copy.deepcopy(cached)
        return refresh_skill_runtime(state)


def planner_skill_context(state: dict[str, Any] | None = None) -> str:
    status = list_skill_runtime(state, refresh=False)
    skills = status.get("skills", [])
    if not isinstance(skills, list):
        return ""
    enabled = [
        item
        for item in skills
        if isinstance(item, dict) and item.get("enabled") is True and item.get("available", True) is True
    ]
    if not enabled:
        return ""
    lines = [
        "Enabled runnable local skills. Use capability=run_skill only with one of these exact skillId values.",
    ]
    for item in enabled[:8]:
        lines.append(
            f"- skillId={item.get('id', '')} category={item.get('category', '')} "
            f"requiresConfirmation={bool(item.get('requiresConfirmation', False))} "
            f"description={_string(item.get('description', ''), limit=160)}"
        )
    lines.append("If you choose run_skill, args must include skillId and optional payload object.")
    return "\n".join(lines)


def _manifest_by_id(skill_id: str) -> dict[str, Any]:
    target_id = _string(skill_id, limit=120)
    if not target_id:
        raise SafeCapabilityError("SKILL_NOT_FOUND", "Skill bulunamadi.")
    status = list_skill_runtime(refresh=False)
    for snapshot in status.get("skills", []):
        if not isinstance(snapshot, dict):
            continue
        if _string(snapshot.get("id"), limit=120) != target_id:
            continue
        path = Path(str(snapshot.get("path", "") or "").strip())
        return _normalize_manifest(path, _read_manifest(path))
    raise SafeCapabilityError("SKILL_NOT_FOUND", "Skill bulunamadi.")


def _manifest_payload_from_normalized(manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(manifest.get("id", "") or ""),
        "name": str(manifest.get("name", "") or ""),
        "description": str(manifest.get("description", "") or ""),
        "enabled": bool(manifest.get("enabled", True)),
        "category": str(manifest.get("category", "") or "custom"),
        "requiresConfirmation": bool(manifest.get("requiresConfirmation", False)),
        "parameters": list(manifest.get("parameters", []) or []),
        "requiredParameters": list(manifest.get("requiredParameters", []) or []),
        "steps": [
            {
                "capability": str(step.get("capability", "") or ""),
                "description": str(step.get("description", "") or ""),
                "args": _safe_json(step.get("args", {}) if isinstance(step.get("args"), dict) else {}),
                "argsFromPayload": dict(step.get("argsFromPayload", {}) or {})
                if isinstance(step.get("argsFromPayload"), dict)
                else {},
                "argsFromPreviousResult": dict(step.get("argsFromPreviousResult", {}) or {})
                if isinstance(step.get("argsFromPreviousResult"), dict)
                else {},
                "argsFromPreviousOutput": list(step.get("argsFromPreviousOutput", []) or [])
                if isinstance(step.get("argsFromPreviousOutput"), list)
                else [],
                "requiresReadOnlyMcp": bool(step.get("requiresReadOnlyMcp", False)),
            }
            for step in (manifest.get("steps", []) if isinstance(manifest.get("steps"), list) else [])
            if isinstance(step, dict)
        ],
    }


def clone_skill(skill_id: str) -> dict[str, Any]:
    with _LOCK:
        manifest = _manifest_by_id(skill_id)
        base_id = f"{str(manifest.get('id', '') or '')}.local"
        candidate_id = base_id
        counter = 2
        while True:
            try:
                _manifest_by_id(candidate_id)
                candidate_id = f"{base_id}-{counter}"
                counter += 1
            except SafeCapabilityError:
                break
        payload = _manifest_payload_from_normalized(manifest)
        payload["id"] = candidate_id
        payload["name"] = f"{str(manifest.get('name', '') or candidate_id)} Local"
        path = _manifest_path_for_id(candidate_id)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        status = refresh_skill_runtime()
        cloned = _manifest_by_id(candidate_id)
        return {
            "skillStatus": status,
            "skill": _skill_snapshot(cloned),
        }


def upsert_local_skill(payload: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        if not isinstance(payload, dict):
            raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill manifest gecerli degil.")
        skill_id = _string(payload.get("id"), limit=120)
        if not skill_id:
            raise SafeCapabilityError("SKILL_MANIFEST_INVALID", "Skill id gerekli.")
        if skill_id in _builtin_skill_ids():
            raise SafeCapabilityError("SKILL_IMMUTABLE", "Built-in skill degistirilemez.")
        existing: dict[str, Any] | None = None
        try:
            existing = _manifest_by_id(skill_id)
        except SafeCapabilityError:
            existing = None
        if existing is not None and str(existing.get("source", "") or "") != "local":
            raise SafeCapabilityError("SKILL_IMMUTABLE", "Built-in skill degistirilemez.")
        normalized = _normalize_manifest(_manifest_path_for_id(skill_id), payload)
        if str(normalized.get("source", "") or "") != "local":
            normalized["source"] = "local"
        path = _manifest_path_for_id(skill_id)
        path.write_text(
            json.dumps(_manifest_payload_from_normalized(normalized), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        status = refresh_skill_runtime()
        saved = _manifest_by_id(skill_id)
        return {
            "skillStatus": status,
            "skill": _skill_snapshot(saved),
        }


def remove_local_skill(skill_id: str) -> dict[str, Any]:
    with _LOCK:
        manifest = _manifest_by_id(skill_id)
        if str(manifest.get("source", "") or "") != "local":
            raise SafeCapabilityError("SKILL_IMMUTABLE", "Built-in skill silinemez.")
        path = Path(str(manifest.get("path", "") or "").strip())
        if path.exists():
            path.unlink()
        status = refresh_skill_runtime()
        return {
            "skillStatus": status,
            "removed": True,
            "skillId": skill_id,
        }


def set_skill_enabled(skill_id: str, enabled: bool) -> dict[str, Any]:
    with _LOCK:
        manifest = _manifest_by_id(skill_id)
        path = Path(str(manifest.get("path", "") or "").strip())
        payload = _read_manifest(path)
        payload["enabled"] = bool(enabled)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return refresh_skill_runtime()


def prepare_skill_run(
    skill_id: str,
    payload: dict[str, Any] | None,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    current_state = state if isinstance(state, dict) else state_store.snapshot()
    manifest = _manifest_by_id(skill_id)
    if not bool(manifest.get("enabled", True)):
        raise SafeCapabilityError("SKILL_DISABLED", "Skill devre disi.")
    skill_snapshot = _skill_snapshot(manifest)
    if not bool(skill_snapshot.get("available", False)):
        raise SafeCapabilityError(
            str(skill_snapshot.get("lastErrorCode", "") or "DEPENDENCY_UNAVAILABLE"),
            str(skill_snapshot.get("lastErrorMessage", "") or "Skill hazir degil."),
        )
    raw_payload = payload if isinstance(payload, dict) else {}
    safe_payload = _safe_json(raw_payload)
    if not isinstance(safe_payload, dict):
        safe_payload = {}
    required_parameters = list(manifest.get("requiredParameters", []) or [])
    for field in required_parameters:
        value = safe_payload.get(field)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise SafeCapabilityError("INVALID_ARGUMENT", "Skill icin gerekli alan eksik.")

    steps: list[dict[str, Any]] = []
    for item in manifest.get("steps", []):
        if not isinstance(item, dict):
            continue
        args = _safe_json(item.get("args") if isinstance(item.get("args"), dict) else {})
        if not isinstance(args, dict):
            args = {}
        mapping = item.get("argsFromPayload", {})
        mapping = dict(mapping) if isinstance(mapping, dict) else {}
        for target_key, source_key in mapping.items():
            if source_key not in safe_payload:
                continue
            args[target_key] = _safe_json(safe_payload.get(source_key))
        previous_result_map = item.get("argsFromPreviousResult", {})
        if isinstance(previous_result_map, dict):
            for target_key, source_key in previous_result_map.items():
                target_name = _string(target_key, limit=80)
                source_name = _string(source_key, limit=120)
                if not target_name or not source_name:
                    continue
                if source_name in safe_payload:
                    args[target_name] = _safe_json(safe_payload.get(source_name))
        previous_output_targets = item.get("argsFromPreviousOutput", [])
        if isinstance(previous_output_targets, list):
            for target_key in previous_output_targets:
                target_name = _string(target_key, limit=80)
                if not target_name:
                    continue
                # previous output is injected later by the runtime bridge; keep the
                # manifest explicit without mutating the payload here.
        if bool(item.get("requiresReadOnlyMcp", False)):
            server_id = _string(args.get("serverId"), limit=120)
            tool_name = _string(args.get("toolName"), limit=120)
            metadata = mcp_runtime.mcp_tool_metadata(server_id, tool_name, current_state)
            if metadata is None:
                raise SafeCapabilityError("MCP_TOOL_NOT_FOUND", "Istenen MCP araci bulunamadi.")
            if not bool(metadata.get("readOnly", False)):
                raise SafeCapabilityError("PERMISSION_REQUIRED", "Bu skill yalniz read-only MCP araci calistirir.")
            args["_readOnlyHint"] = True
        steps.append(
            {
                "capability": str(item.get("capability", "") or ""),
                "args": args,
                "description": str(item.get("description", "") or ""),
                "argsFromPreviousResult": dict(item.get("argsFromPreviousResult", {}) or {})
                if isinstance(item.get("argsFromPreviousResult"), dict)
                else {},
                "argsFromPreviousOutput": list(item.get("argsFromPreviousOutput", []) or [])
                if isinstance(item.get("argsFromPreviousOutput"), list)
                else [],
            }
        )
    preview_steps = [
        {
            "capability": step.get("capability", ""),
            "description": step.get("description", "") or step.get("capability", ""),
        }
        for step in steps
    ]
    summary = str(manifest.get("description", "") or manifest.get("name", "") or skill_id)
    return {
        "skill": skill_snapshot,
        "steps": steps,
        "requiresConfirmation": bool(manifest.get("requiresConfirmation", False)),
        "planPreview": {
            "summary": summary,
            "steps": preview_steps,
            "privacyClass": "local_private",
        },
    }
