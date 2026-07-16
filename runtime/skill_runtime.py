from __future__ import annotations

import copy
import json
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

from runtime import mcp_runtime, state_store
from runtime.capability_registry import SafeCapabilityError, capability_dependency_status
from runtime.skill_catalog import builtin_skill_manifests as _catalog_builtin_skill_manifests


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


def _fold_text(value: Any) -> str:
    text = _string(value, limit=500)
    if not text:
        return ""
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()


def _tokenize(value: Any) -> list[str]:
    folded = _fold_text(value)
    if not folded:
        return []
    return [token for token in re.findall(r"[a-z0-9]+", folded) if len(token) > 1]


def _unique_tokens(*values: Any) -> list[str]:
    tokens: set[str] = set()
    for value in values:
        tokens.update(_tokenize(value))
    return sorted(tokens)


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", _string(value, limit=120).lower())
    normalized = normalized.strip("-")
    return normalized or "skill"


def _builtin_skill_manifests() -> list[dict[str, Any]]:
    return _catalog_builtin_skill_manifests()


def _builtin_skill_ids() -> set[str]:
    return {str(item.get("id", "") or "") for item in _builtin_skill_manifests()}


def _allowed_local_capabilities() -> set[str]:
    # Tek Spec mimarisi: spec'e kayıtlı her yetenek skill tariflerinde
    # kullanılabilir — elle whitelist büyütmek yalnız legacy adlar için kaldı.
    from runtime import capability_spec

    return {spec.name for spec in capability_spec.SPECS} | {
        "document_read",
        "document_write",
        "spreadsheet_write",
        "presentation_write",
        "canvas_write",
        "ocr_read",
        "image_read",
        "image_generate",
        "image_edit",
        "web_research",
        "browser_control",
        "data_analyze",
        "chart_generate",
        "math_solve",
        "latex_parse",
        "desktop_operator.run",
        "desktop_operator.observe_screen",
        "desktop_operator.locate",
        "desktop_operator.focus_window",
        "desktop_operator.execute_action",
        "retrieve_context",
        "mcp_call_tool",
        "speech_to_text",
        "text_to_speech",
    }


def _skill_usage_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    current_state = state if isinstance(state, dict) else state_store.snapshot()
    skills = current_state.get("skills", {})
    skills = skills if isinstance(skills, dict) else {}
    usage = skills.get("usage", {})
    usage = usage if isinstance(usage, dict) else {}
    stats = usage.get("skillStats", {})
    stats = stats if isinstance(stats, dict) else {}
    recent_runs = usage.get("recentRuns", [])
    recent_runs = recent_runs if isinstance(recent_runs, list) else []
    return {
        "skillStats": stats,
        "recentRuns": recent_runs,
        "lastSuccessfulSkillId": _string(usage.get("lastSuccessfulSkillId", ""), limit=160),
        "lastSuccessfulAt": _string(usage.get("lastSuccessfulAt", ""), limit=80),
        "lastFailedSkillId": _string(usage.get("lastFailedSkillId", ""), limit=160),
        "lastFailedAt": _string(usage.get("lastFailedAt", ""), limit=80),
    }


_QUERY_ALIAS_MAP: dict[str, set[str]] = {
    "ozet": {"summary", "brief", "bullet", "bullets"},
    "ozetle": {"summary", "brief", "bullet", "bullets"},
    "summary": {"ozet", "brief"},
    "pdf": {"document", "file", "belge", "dosya"},
    "belge": {"document", "file"},
    "dosya": {"document", "file"},
    "docx": {"document", "word"},
    "xlsx": {"spreadsheet", "excel", "table"},
    "excel": {"spreadsheet", "xlsx"},
    "ppt": {"presentation", "slide", "sunum"},
    "sunum": {"presentation", "slide"},
    "canvas": {"canvas_write", "document", "layout", "table"},
    "kanvas": {"canvas_write", "document", "layout", "table"},
    "tuval": {"canvas_write", "document", "layout", "table"},
    "web": {"browser", "search", "internet"},
    "internet": {"web", "search"},
    "arama": {"search", "browser"},
    "ara": {"search", "browser"},
    "search": {"browser", "research"},
    "kaynak": {"research", "verify", "context"},
    "arastir": {"research", "verify", "web", "source"},
    "arastirma": {"research", "verify", "web", "source"},
    "research": {"source", "verify", "web"},
    "gorsel": {"image", "ocr", "vision", "picture"},
    "goruntu": {"image", "ocr", "vision"},
    "resim": {"image", "ocr"},
    "ocr": {"image", "text"},
    "veri": {"data", "analysis", "chart"},
    "grafik": {"chart", "analysis"},
    "chart": {"analysis", "data"},
    "hesapla": {"math", "solve"},
    "denklem": {"math", "solve"},
    "latex": {"math", "parse"},
    "ekran": {"desktop", "operator", "screen"},
    "mouse": {"desktop", "operator"},
    "terminal": {"shell"},
    "skill": {"run_skill"},
}


def _expand_query_tokens(tokens: set[str]) -> set[str]:
    expanded = set(tokens)
    for token in list(tokens):
        for alias, mapped in _QUERY_ALIAS_MAP.items():
            if token == alias or token.startswith(alias):
                expanded.update(mapped)
    return expanded


def _skill_tokens(manifest: dict[str, Any]) -> set[str]:
    tokens = set(
        _unique_tokens(
            manifest.get("id", ""),
            manifest.get("name", ""),
            manifest.get("description", ""),
            manifest.get("category", ""),
            manifest.get("adapter", ""),
            *([item for item in (manifest.get("intentTags", []) or []) if str(item).strip()]),
            *([item for item in (manifest.get("expectedInputs", []) or []) if str(item).strip()]),
            *([item for item in (manifest.get("parameters", []) or []) if str(item).strip()]),
            *([item for item in (manifest.get("libraries", []) or []) if str(item).strip()]),
        )
    )
    return tokens


def _skill_usage_for_id(skill_id: str, state: dict[str, Any] | None = None) -> dict[str, Any]:
    usage = _skill_usage_state(state)
    stats = usage.get("skillStats", {})
    stats = stats if isinstance(stats, dict) else {}
    item = stats.get(skill_id, {})
    return item if isinstance(item, dict) else {}


def _skill_score_for_request(
    manifest: dict[str, Any],
    query: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    skill_id = _string(manifest.get("id"), limit=120)
    if not skill_id:
        return {
            "score": -1000.0,
            "reasons": ["missing_skill_id"],
            "matchCount": 0,
        }
    available = bool(manifest.get("available", True))
    if not available:
        return {
            "score": -1000.0,
            "reasons": ["unavailable"],
            "matchCount": 0,
        }
    query_tokens = _expand_query_tokens(set(_tokenize(query)))
    skill_tokens = _skill_tokens(manifest)
    overlap = sorted(query_tokens & skill_tokens)
    name_tokens = set(_tokenize(manifest.get("name", "")))
    description_tokens = set(_tokenize(manifest.get("description", "")))
    adapter_tokens = set(_tokenize(manifest.get("adapter", "")))
    tag_tokens = set(_tokenize(manifest.get("intentTags", [])))
    parameter_tokens = set(_tokenize(manifest.get("expectedInputs", [])))
    score = float(manifest.get("selectionPriority", 50) or 50)
    reasons: list[str] = []
    if overlap:
        score += len(overlap) * 10.0
        reasons.append(f"overlap:{','.join(overlap[:5])}")
    name_overlap = sorted(query_tokens & name_tokens)
    if name_overlap:
        score += len(name_overlap) * 8.0
        reasons.append(f"name:{','.join(name_overlap[:3])}")
    description_overlap = sorted(query_tokens & description_tokens)
    if description_overlap:
        score += min(10.0, len(description_overlap) * 3.0)
        reasons.append(f"description:{','.join(description_overlap[:3])}")
    adapter_overlap = sorted(query_tokens & adapter_tokens)
    if adapter_overlap:
        score += len(adapter_overlap) * 4.0
        reasons.append(f"adapter:{','.join(adapter_overlap[:3])}")
    tag_overlap = sorted(query_tokens & tag_tokens)
    if tag_overlap:
        score += len(tag_overlap) * 5.0
        reasons.append(f"tags:{','.join(tag_overlap[:3])}")
    parameter_overlap = sorted(query_tokens & parameter_tokens)
    if parameter_overlap:
        score += len(parameter_overlap) * 4.0
        reasons.append(f"inputs:{','.join(parameter_overlap[:3])}")
    latency_class = str(manifest.get("latencyClass", "") or "medium").strip().lower()
    if latency_class == "quick":
        score += 3.0
    elif latency_class == "medium":
        score += 1.5
    else:
        score -= 1.0
    if bool(manifest.get("requiresConfirmation", False)):
        score -= 5.0
        reasons.append("confirmation")
    usage = _skill_usage_for_id(skill_id, state)
    success_count = max(0, int(usage.get("successCount", 0) or 0))
    failure_count = max(0, int(usage.get("failureCount", 0) or 0))
    score += min(8.0, success_count * 0.6)
    score -= min(6.0, failure_count * 0.8)
    last_success = _string(usage.get("lastOkAt", ""), limit=80)
    last_failure = _string(usage.get("lastFailedAt", ""), limit=80)
    if last_success:
        score += 0.8
    if last_failure:
        score -= 0.5
    if not overlap and not name_overlap and not description_overlap and not adapter_overlap and not tag_overlap:
        score -= 6.0
        reasons.append("weak_match")
    return {
        "score": round(score, 3),
        "reasons": reasons,
        "matchCount": len(overlap) + len(name_overlap) + len(description_overlap),
    }


def rank_skills_for_text(
    text: str,
    state: dict[str, Any] | None = None,
    *,
    skills: list[dict[str, Any]] | None = None,
    limit: int = 8,
) -> list[dict[str, Any]]:
    runtime_state = state if isinstance(state, dict) else state_store.snapshot()
    skill_items = skills
    if skill_items is None:
        status = list_skill_runtime(runtime_state, refresh=False)
        skill_items = status.get("skills", []) if isinstance(status, dict) else []
    if not isinstance(skill_items, list) or not skill_items:
        return []
    candidates = [
        item
        for item in skill_items
        if isinstance(item, dict) and bool(item.get("enabled", True)) and bool(item.get("available", True))
    ]
    if not candidates:
        return []
    ranked: list[dict[str, Any]] = []
    for item in candidates:
        score_payload = _skill_score_for_request(item, text, runtime_state)
        ranked.append(
            {
                **item,
                **score_payload,
            }
        )
    ranked.sort(
        key=lambda item: (
            -float(item.get("score", 0.0) or 0.0),
            -int(item.get("selectionPriority", 0) or 0),
            str(item.get("id", "") or ""),
        )
    )
    return ranked[: max(0, int(limit or 0)) or 8]


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
        normalized_step: dict[str, Any] = {
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
        # Tarif dili: {{steps.<id>...}} referansları ve forEach fan-out
        # manifest'ten executor'a kadar korunur.
        step_id = _string(item.get("id"), limit=80)
        if step_id:
            normalized_step["id"] = step_id
        for_each = item.get("forEach")
        if isinstance(for_each, str) and for_each.strip():
            normalized_step["forEach"] = for_each.strip()
        normalized.append(normalized_step)
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
    libraries = [
        _string(item, limit=120)
        for item in (payload.get("libraries") if isinstance(payload.get("libraries"), list) else [])
        if _string(item, limit=120)
    ]
    intent_tags = [
        _string(item, limit=80)
        for item in (payload.get("intentTags") if isinstance(payload.get("intentTags"), list) else [])
        if _string(item, limit=80)
    ]
    expected_inputs = [
        _string(item, limit=80)
        for item in (payload.get("expectedInputs") if isinstance(payload.get("expectedInputs"), list) else [])
        if _string(item, limit=80)
    ]
    latency_class = _string(payload.get("latencyClass"), limit=20).lower()
    if latency_class not in {"quick", "medium", "slow"}:
        latency_class = "medium"
    try:
        selection_priority = int(payload.get("selectionPriority", 50) or 50)
    except (TypeError, ValueError):
        selection_priority = 50
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
        "intentTags": list(dict.fromkeys(intent_tags)),
        "latencyClass": latency_class,
        "selectionPriority": max(0, min(100, selection_priority)),
        "expectedInputs": list(dict.fromkeys(expected_inputs or required_parameters or sorted(parameters))),
        "adapter": _string(payload.get("adapter"), limit=120),
        "libraries": list(dict.fromkeys(libraries)),
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
        "adapter": str(manifest.get("adapter", "") or ""),
        "libraries": list(manifest.get("libraries", []) or []),
        "requiresConfirmation": bool(manifest.get("requiresConfirmation", False)),
        "stepCount": len(steps),
        "parameters": list(manifest.get("parameters", []) or []),
        "requiredParameters": list(manifest.get("requiredParameters", []) or []),
        "intentTags": list(manifest.get("intentTags", []) or []),
        "latencyClass": str(manifest.get("latencyClass", "") or ""),
        "selectionPriority": int(manifest.get("selectionPriority", 50) or 50),
        "expectedInputs": list(manifest.get("expectedInputs", []) or []),
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


def _usage_summary_line(skill_id: str, state: dict[str, Any] | None = None) -> str:
    usage = _skill_usage_for_id(skill_id, state)
    if not usage:
        return ""
    success_count = max(0, int(usage.get("successCount", 0) or 0))
    failure_count = max(0, int(usage.get("failureCount", 0) or 0))
    if success_count == 0 and failure_count == 0:
        return ""
    return f"usage={success_count}ok/{failure_count}fail"


def planner_skill_context(state: dict[str, Any] | None = None, text: str = "") -> str:
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
    ranked = rank_skills_for_text(text, state, skills=enabled, limit=8) if _string(text, limit=240) else sorted(
        enabled,
        key=lambda item: (
            -int(item.get("selectionPriority", 0) or 0),
            -int(bool(item.get("available", True))),
            str(item.get("id", "") or ""),
        ),
    )
    lines = [
        "Enabled runnable local skills. Use capability=run_skill only with one of these exact skillId values.",
    ]
    for item in ranked[:8]:
        libraries = ", ".join(
            str(value)
            for value in list(item.get("libraries", []) or [])[:4]
            if str(value).strip()
        )
        tags = ", ".join(str(value) for value in list(item.get("intentTags", []) or [])[:5] if str(value).strip())
        usage_line = _usage_summary_line(str(item.get("id", "") or ""), state)
        lines.append(
            f"- skillId={item.get('id', '')} score={item.get('score', 0)} priority={item.get('selectionPriority', 0)} "
            f"category={item.get('category', '')} latency={item.get('latencyClass', '')} "
            f"adapter={item.get('adapter', '')} "
            f"libraries={libraries or 'none'} "
            f"tags={tags or 'none'} "
            f"{usage_line + ' ' if usage_line else ''}"
            f"requiresConfirmation={bool(item.get('requiresConfirmation', False))} "
            f"expectedInputs={', '.join(str(value) for value in list(item.get('expectedInputs', []) or [])[:4] if str(value).strip()) or 'none'} "
            f"description={_string(item.get('description', ''), limit=160)}"
        )
    if _string(text, limit=240):
        lines.append("Best matches above are ranked for this exact request. Prefer the highest scoring ready skill.")
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
        "intentTags": list(manifest.get("intentTags", []) or []),
        "latencyClass": str(manifest.get("latencyClass", "") or "medium"),
        "selectionPriority": int(manifest.get("selectionPriority", 50) or 50),
        "expectedInputs": list(manifest.get("expectedInputs", []) or []),
        "adapter": str(manifest.get("adapter", "") or ""),
        "libraries": list(manifest.get("libraries", []) or []),
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


def record_skill_usage(
    skill_id: str,
    *,
    success: bool,
    source: str = "",
    duration_ms: int = 0,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    skill_key = _string(skill_id, limit=120)
    if not skill_key:
        return {}
    with _LOCK:
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        merged_state = copy.deepcopy(current_state)
        skills_state = merged_state.setdefault("skills", {})
        if not isinstance(skills_state, dict):
            skills_state = {}
            merged_state["skills"] = skills_state
        usage = skills_state.get("usage", {})
        if not isinstance(usage, dict):
            usage = {}
        recent_runs = usage.get("recentRuns", [])
        if not isinstance(recent_runs, list):
            recent_runs = []
        stats = usage.get("skillStats", {})
        if not isinstance(stats, dict):
            stats = {}
        stat = stats.get(skill_key, {})
        if not isinstance(stat, dict):
            stat = {}
        now = _utc_now_iso()
        recent_runs.insert(
            0,
            {
                "skillId": skill_key,
                "success": bool(success),
                "source": _string(source, limit=80),
                "durationMs": max(0, int(duration_ms or 0)),
                "at": now,
            },
        )
        usage["recentRuns"] = recent_runs[:40]
        stat["successCount"] = max(0, int(stat.get("successCount", 0) or 0)) + (1 if success else 0)
        stat["failureCount"] = max(0, int(stat.get("failureCount", 0) or 0)) + (0 if success else 1)
        if success:
            stat["lastOkAt"] = now
            usage["lastSuccessfulSkillId"] = skill_key
            usage["lastSuccessfulAt"] = now
        else:
            stat["lastFailedAt"] = now
            usage["lastFailedSkillId"] = skill_key
            usage["lastFailedAt"] = now
        stat["lastDurationMs"] = max(0, int(duration_ms or 0))
        stats[skill_key] = stat
        usage["skillStats"] = stats
        skills_state["usage"] = usage
        state_store.save_state(merged_state)
        return copy.deepcopy(usage)


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
        step_entry: dict[str, Any] = {
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
        # Tarif dili: adım kimliği ({{steps.<id>...}} referansları için) ve
        # forEach (liste çıktısı üzerinde fan-out) executor'a aynen taşınır —
        # skill'ler artık çok adımlı, veri akışlı görev tarifleri yazabilir.
        step_id = _string(item.get("id"), limit=80)
        if step_id:
            step_entry["id"] = step_id
        for_each = item.get("forEach")
        if isinstance(for_each, str) and for_each.strip():
            step_entry["forEach"] = for_each.strip()
        steps.append(step_entry)
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
