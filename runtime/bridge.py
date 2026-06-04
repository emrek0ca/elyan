from __future__ import annotations

import asyncio
import datetime as dt
import difflib
import json
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from functools import lru_cache
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import requests

from app_config import get_app_config_value
from runtime.backend_client import BackendClient, BackendResult
from runtime.capability_registry import (
    TOOL_DECLARATIONS as REGISTRY_TOOL_DECLARATIONS,
    SafeCapabilityError,
    capability_readiness,
    capability_metadata_summary,
    capability_names,
    capability_groups,
    dependency_status_snapshot,
    run_capability,
    run_capability_text,
    safe_tool_event,
)
from runtime.safety_policy import PERSONAL_ACTION_CAPABILITIES, evaluate_tool
from runtime.task_router import (
    RoutedTask,
    artifact_target_clarification,
    revise_plan_payload,
    route_text_to_tool,
)
from runtime import state_store
from runtime.executor_core import ExecutorCore
from runtime import native_file_indexer
from runtime import mcp_runtime
from runtime import skill_runtime
from runtime import litellm_adapter


BASE_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = BASE_DIR / "core" / "prompt.txt"
STATE = state_store
KNOWN_PROVIDER_IDS = {"local", "ollama", "lmstudio", "llamacpp", "openai", "gemini", "anthropic", "groq", "custom"}
GOOGLE_LIVE_MODEL_DEFAULT = "models/gemini-2.5-flash"
LOCAL_MODELS_CAPABILITY_NAME = "local_models.api"
RECOMMENDED_LOCAL_MODELS = [
    "llama3.1:8b",
    "qwen2.5:7b",
    "deepseek-r1:8b",
    "mistral:7b",
]
_PROVIDER_SECRET_OVERRIDES: dict[str, str] = {}
SIDE_EFFECT_CAPABILITIES = {
    "open_app",
    "close_app",
    "shell_run",
    "add_calendar_event",
    "delete_calendar_event",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "email_send",
    "document_write",
    "spreadsheet_write",
    "presentation_write",
    "run_skill",
}
LOCAL_PRIVATE_CAPABILITIES = {
    "open_app",
    "close_app",
    "sys_info",
    "get_calendar_events",
    "add_calendar_event",
    "get_reminders",
    "add_reminder",
    "send_whatsapp_message",
    "save_whatsapp_contact",
    "document_read",
    "document_write",
    "ocr_read",
    "image_read",
    "data_analyze",
    "chart_generate",
    "analyze_screen",
    "shell_run",
    "spreadsheet_write",
    "presentation_write",
    "mcp_call_tool",
    "retrieve_context",
    "speech_capture",
    "speech_to_text",
    "run_skill",
}
REMOTE_EMAIL_CAPABILITIES = {"email_draft", "email_send", "email.draft", "email.send"}
REMOTE_RESEARCH_CAPABILITIES = {"web_research", "web.research"}
REMOTE_QUANTUM_CAPABILITIES = {
    "quantum_model_problem",
    "quantum_run_experiment",
    "quantum_compare_classical",
    "quantum_generate_report",
}
QUANTUM_EXECUTION_CAPABILITIES = {"quantum_run_experiment"}
EMAIL_ADDRESS_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


def _canonical_capability_name(value: Any) -> str:
    return str(value or "").strip().lower().replace(".", "_").replace(" ", "_")


def _extract_email_addresses_from_text(text: str) -> list[str]:
    ordered: list[str] = []
    for match in EMAIL_ADDRESS_RE.findall(str(text or "")):
        candidate = match.strip()
        if candidate and candidate not in ordered:
            ordered.append(candidate)
    return ordered


def _research_topic_from_text(text: str) -> str:
    original = str(text or "").strip()
    patterns = [
        r"(.+?)\s+(?:hakk[ıi]nda|about)\s+(?:araştırma yap|arastirma yap|araştır|araştir|research|incele)",
        r"(?:araştırma yap|arastirma yap|araştır|araştir|research|incele)\s+(.+?)(?:\s+(?:ve|and)\s+|$)",
    ]
    for pattern in patterns:
        match = re.search(pattern, original, flags=re.IGNORECASE)
        if match:
            candidate = re.sub(r"\b(?:mail|email|e-?posta).*$", "", match.group(1), flags=re.IGNORECASE)
            candidate = " ".join(candidate.split()).strip(" ,.;:")
            if candidate:
                return candidate
    return " ".join(re.sub(EMAIL_ADDRESS_RE, "", original).split()).strip(" ,.;:") or original


def _utc_now_iso() -> str:
    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _request_id() -> str:
    import uuid

    return f"req_{uuid.uuid4().hex[:12]}"


def _map_from(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _parse_iso_datetime(value: str) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(dt.timezone.utc).replace(tzinfo=None)
    return parsed


def _pairing_expired(expires_at: str, *, skew_seconds: int = 15) -> bool:
    parsed = _parse_iso_datetime(expires_at)
    if parsed is None:
        return False
    return dt.datetime.utcnow() >= parsed + dt.timedelta(seconds=skew_seconds)


def _safe_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _simple_local_runtime_status(provider_id: str, status: dict[str, Any]) -> tuple[str, str]:
    reachable = status.get("reachable") is True
    configured = status.get("configured") is True
    error_code = str(status.get("errorCode", "") or "").strip()
    if reachable and configured:
        return "ready", "Hazır"
    if provider_id == "ollama" and str(status.get("binary", "") or "").strip():
        return "available", "Açılabilir"
    if provider_id == "ollama" and error_code == "ollama_binary_missing":
        return "missing", "Bulunamadı"
    if provider_id == "llamacpp" and error_code in {"llamacpp_binary_missing", "llamacpp_model_missing"}:
        return "setup_required", "Kurulum gerekli"
    if configured:
        return "offline", "Bağlı değil"
    return "setup_required", "Kurulum gerekli"


def _simple_local_runtime_hint(provider_id: str, status: dict[str, Any], default_model: str) -> str:
    state_key, _ = _simple_local_runtime_status(provider_id, status)
    if state_key == "ready" and default_model:
        return f"{default_model} kullanılabilir."
    if state_key == "ready":
        return "Bağlantı hazır."
    if provider_id == "ollama" and state_key == "available":
        return "Bilgisayarda var, istersen açılabilir."
    if provider_id == "ollama" and state_key == "missing":
        return "Bilgisayarda görünmüyor."
    if provider_id == "llamacpp" and state_key == "setup_required":
        return "Model dosyası seçilince kullanılabilir."
    if provider_id == "lmstudio":
        return "Açık olduğunda bağlanır."
    return "Henüz hazır değil."


def _load_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "Sen Elyan'sin. Turkce konus. Kisa ve net cevap ver. "
            "Araclari kullanarak gorevleri tamamla; asla taklit etme."
        )


@lru_cache(maxsize=1)
def _memory_manager_module() -> Any | None:
    try:
        return import_module("memory.memory_manager")
    except Exception:
        return None


def _memory_prompt_context() -> str:
    module = _memory_manager_module()
    if module is None:
        return ""
    try:
        return str(module.format_memory_for_prompt(module.load_memory()) or "")
    except Exception:
        return ""


@lru_cache(maxsize=1)
def _ollama_client_class() -> type[Any] | None:
    try:
        module = import_module("runtime.local_models")
    except Exception:
        return None
    client_class = getattr(module, "OllamaClient", None)
    return client_class if isinstance(client_class, type) else None


def _make_ollama_client(base_url: str | None = None, default_model: str = "") -> Any | None:
    client_class = _ollama_client_class()
    if client_class is None:
        return None
    return client_class(base_url=base_url, default_model=default_model)


@lru_cache(maxsize=1)
def _lmstudio_client_class() -> type[Any] | None:
    try:
        module = import_module("runtime.local_models")
    except Exception:
        return None
    client_class = getattr(module, "LMStudioClient", None)
    return client_class if isinstance(client_class, type) else None


def _make_lmstudio_client(base_url: str | None = None, default_model: str = "") -> Any | None:
    client_class = _lmstudio_client_class()
    if client_class is None:
        return None
    return client_class(base_url=base_url, default_model=default_model)


@lru_cache(maxsize=1)
def _llamacpp_client_class() -> type[Any] | None:
    try:
        module = import_module("runtime.local_models")
    except Exception:
        return None
    client_class = getattr(module, "LlamaCppClient", None)
    return client_class if isinstance(client_class, type) else None


def _make_llamacpp_client(
    base_url: str | None = None,
    default_model: str = "",
    *,
    binary_path: str = "",
    model_path: str = "",
    auto_start: bool = False,
) -> Any | None:
    client_class = _llamacpp_client_class()
    if client_class is None:
        return None
    return client_class(
        base_url=base_url,
        default_model=default_model,
        binary_path=binary_path,
        model_path=model_path,
        auto_start=auto_start,
    )


def _ollama_status_payload(base_url: str | None, default_model: str) -> dict[str, Any]:
    client = _make_ollama_client(base_url=base_url, default_model=default_model)
    if client is None:
        return {
            "available": False,
            "binary": None,
            "baseUrl": (base_url or os.environ.get("ELYAN_OLLAMA_BASE_URL") or "http://127.0.0.1:11434").rstrip("/"),
            "defaultModel": default_model,
            "jobs": [],
            "error": "ollama_client_unavailable",
        }
    return client.status()


@lru_cache(maxsize=1)
def _google_live_sdk() -> tuple[Any | None, Any | None]:
    try:
        from google import genai as google_genai  # type: ignore[reportMissingImports]
        from google.genai import types as google_types  # type: ignore[reportMissingImports]
    except Exception:
        return None, None
    return google_genai, google_types


def _google_live_available() -> bool:
    google_genai, google_types = _google_live_sdk()
    return google_genai is not None and google_types is not None


@lru_cache(maxsize=1)
def _websocket_module() -> Any | None:
    try:
        return import_module("websocket")
    except Exception:
        return None


def _websocket_runtime_available() -> bool:
    return _websocket_module() is not None


def _module_available(module_name: str) -> bool:
    try:
        return find_spec(module_name) is not None
    except Exception:
        return False


def _quantum_simulator_ready() -> bool:
    return _module_available("qiskit") and _module_available("qiskit_aer")


def _runtime_advertised_capabilities() -> list[str]:
    capabilities = set(capability_names())
    capabilities.update(
        {
            "providers.catalog",
            "providers.update_config",
            "providers.validate",
            "providers.secrets_sync",
            "local_models.start",
            "backend.auth_update_profile",
            "backend.auth_change_password",
            "backend.auth_avatar_upload",
            "backend.auth_avatar_get",
            "backend.auth_avatar_delete",
            "backend.auth_delete_account",
        }
    )
    if not _quantum_simulator_ready():
        capabilities.difference_update(QUANTUM_EXECUTION_CAPABILITIES)
    if native_file_indexer.sidecar_available():
        capabilities.add(native_file_indexer.CAPABILITY_NAME)
    return sorted(capabilities)


@lru_cache(maxsize=1)
def _speech_module() -> Any | None:
    try:
        return import_module("actions.speech")
    except Exception:
        return None


@lru_cache(maxsize=1)
def _tts_module() -> Any | None:
    try:
        return import_module("actions.tts")
    except Exception:
        return None


def _dependency_status_payload() -> dict[str, Any]:
    payload = {
        **dependency_status_snapshot(),
        "desktop_native_snapshot": _native_desktop_dependency_status(),
    }
    for key, module_name, label in (
        ("qiskit", "qiskit", "Qiskit"),
        ("qiskit_aer", "qiskit_aer", "Qiskit Aer"),
    ):
        payload[key] = {
            "available": _module_available(module_name),
            "label": label,
        }
    return payload


def _native_desktop_dependency_status() -> dict[str, Any]:
    try:
        module = import_module("actions.desktop_os")
        status = module.desktop_os_runtime_status()
    except Exception:
        return {
            "available": False,
            "label": "Desktop Native Snapshot",
            "lastErrorCode": "native_snapshot_unavailable",
        }
    detail = status.get("detail", {}) if isinstance(status, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    return {
        "available": bool(status.get("available", False)),
        "label": "Desktop Native Snapshot",
        "lastErrorCode": str(status.get("lastErrorCode", "") or ""),
        "source": str(detail.get("source", "") or ""),
        "platform": str(detail.get("platform", "") or ""),
    }


def _desktop_os_capability_states() -> dict[str, dict[str, Any]]:
    try:
        module = import_module("actions.desktop_os")
        status = module.desktop_os_runtime_status()
        permissions = module.desktop_os_permissions()
    except Exception:
        return {
            "desktop_os.status": {"available": False, "ready": False, "errorCode": "native_snapshot_unavailable"},
            "desktop_os.permissions": {"available": False, "ready": False, "errorCode": "native_snapshot_unavailable"},
            "desktop_os.processes": {"available": False, "ready": False, "errorCode": "native_snapshot_unavailable"},
            "desktop_os.active_window": {"available": False, "ready": False, "errorCode": "native_snapshot_unavailable"},
        }
    detail = status.get("detail", {}) if isinstance(status, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    permissions_result = permissions.get("result", {}) if isinstance(permissions, dict) else {}
    permissions_result = permissions_result if isinstance(permissions_result, dict) else {}
    last_error_code = str(status.get("lastErrorCode", "") or "")
    return {
        "desktop_os.status": {
            "available": bool(status.get("available", False)),
            "ready": bool(status.get("available", False)),
            "platform": str(detail.get("platform", "") or ""),
            "source": str(detail.get("source", "") or ""),
            "collectedAt": str(detail.get("collectedAt", "") or ""),
            "errorCode": last_error_code,
        },
        "desktop_os.permissions": {
            "available": bool(permissions_result.get("available", False)),
            "ready": bool(permissions_result.get("available", False)),
            "osPermissionModel": str(permissions_result.get("osPermissionModel", "") or ""),
            "errorCode": last_error_code,
        },
        "desktop_os.processes": {
            "available": bool(detail.get("processInspectionAvailable", False)),
            "ready": bool(detail.get("processInspectionAvailable", False)),
            "errorCode": last_error_code if not bool(detail.get("processInspectionAvailable", False)) else "",
        },
        "desktop_os.active_window": {
            "available": bool(detail.get("activeWindowAvailable", False)),
            "ready": bool(detail.get("activeWindowAvailable", False)),
            "errorCode": last_error_code if not bool(detail.get("activeWindowAvailable", False)) else "",
        },
    }


def _runtime_dynamic_capability_states(local_models_state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        native_file_indexer.CAPABILITY_NAME: native_file_indexer.current_capability_state(),
        LOCAL_MODELS_CAPABILITY_NAME: local_models_state,
        **_desktop_os_capability_states(),
    }


def _runtime_capability_states_payload(
    runtime_capabilities: list[str],
    runtime_state: dict[str, Any] | None,
    local_models_state: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    dependency_status = _dependency_status_payload()
    dynamic_states = _runtime_dynamic_capability_states(local_models_state)
    runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
    existing_states = runtime_state.get("capabilityStates", {})
    states = dict(existing_states) if isinstance(existing_states, dict) else {}
    state_snapshot = {"runtime": {"capabilityStates": states}}
    for capability in runtime_capabilities:
        if capability in dynamic_states:
            continue
        states[capability] = capability_readiness(
            capability,
            state=state_snapshot,
            dependency_status=dependency_status,
        )
    states.update(dynamic_states)
    return states


def _retrieval_index_cache_path() -> Path:
    return STATE.CONFIG_DIR / "retrieval" / "index.json"


def _retrieval_status_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    path = _retrieval_index_cache_path()
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                payload = raw
        except Exception:
            payload = {}
    workspace = payload.get("workspace", {}) if isinstance(payload.get("workspace"), dict) else {}
    conversations = payload.get("conversations", {}) if isinstance(payload.get("conversations"), dict) else {}
    indexed_workspace_chunks = sum(
        len(entry.get("chunks", []))
        for entry in workspace.values()
        if isinstance(entry, dict) and isinstance(entry.get("chunks"), list)
    )
    indexed_conversation_chunks = sum(
        len(entry.get("chunks", []))
        for entry in conversations.values()
        if isinstance(entry, dict) and isinstance(entry.get("chunks"), list)
    )
    return {
        "available": True,
        "strategy": str(payload.get("lastStrategy", "lexical") or "lexical"),
        "model": str(os.environ.get("ELYAN_SENTENCE_TRANSFORMERS_MODEL", "all-MiniLM-L6-v2") or "all-MiniLM-L6-v2"),
        "cacheReady": path.exists(),
        "indexedWorkspaceChunks": indexed_workspace_chunks,
        "indexedConversationChunks": indexed_conversation_chunks,
        "lastIndexedAt": str(payload.get("indexedAt", "") or ""),
        "localFileIndex": native_file_indexer.current_capability_state(),
        "indexedLocalFileChunks": sum(
            len(entry.get("chunks", []))
            for entry in (payload.get("localFiles", {}) if isinstance(payload.get("localFiles"), dict) else {}).values()
            if isinstance(entry, dict) and isinstance(entry.get("chunks"), list)
        ),
    }


def _speech_status_payload() -> dict[str, Any]:
    module = _speech_module()
    payload: dict[str, Any] = {
        "available": False,
        "recording": False,
        "captureSessionId": "",
        "transcriptionModel": str(os.environ.get("ELYAN_FASTER_WHISPER_MODEL", "base") or "base"),
        "ttsProvider": "",
        "lastErrorCode": "",
    }
    if module is not None:
        try:
            status = module.speech_runtime_status()
            if isinstance(status, dict):
                payload.update(status)
        except Exception:
            pass
    tts_module = _tts_module()
    if tts_module is not None:
        try:
            tts_status = tts_module.speech_tts_status()
            if isinstance(tts_status, dict):
                provider = str(tts_status.get("provider", "") or "")
                if provider:
                    payload["ttsProvider"] = provider
                payload["available"] = bool(payload.get("available")) or bool(tts_status.get("available"))
        except Exception:
            pass
    return payload


def _mcp_status_payload() -> dict[str, Any]:
    try:
        return mcp_runtime.runtime_mcp_status()
    except Exception:
        return {
            "available": True,
            "sdkAvailable": False,
            "lastRefreshAt": "",
            "serverCount": 0,
            "servers": [],
            "tools": [],
            "toolCount": 0,
            "lastErrorCode": "",
            "lastErrorMessage": "",
        }


def _skill_status_payload() -> dict[str, Any]:
    try:
        return skill_runtime.list_skill_runtime(refresh=False)
    except Exception:
        return {
            "available": True,
            "lastRefreshAt": "",
            "manifestCount": 0,
            "activeSkillCount": 0,
            "readySkillCount": 0,
            "blockedSkillCount": 0,
            "skills": [],
            "lastErrorCode": "",
            "lastErrorMessage": "",
        }


def _build_system_instruction() -> str:
    now = dt.datetime.now()
    time_ctx = f"[SU ANKI ZAMAN]\n{now.strftime('%A, %d %B %Y — %H:%M')}\n\n"
    memory = _memory_prompt_context()
    parts = [time_ctx]
    if memory:
        parts.append(memory + "\n\n")
    parts.append(_load_prompt())
    return "\n".join(parts)

TOOL_DECLARATIONS = list(REGISTRY_TOOL_DECLARATIONS)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _workspace_projects() -> list[dict[str, Any]]:
    projects: list[dict[str, Any]] = []
    for child in sorted(BASE_DIR.iterdir(), key=lambda path: path.name.lower()):
        if not child.is_dir():
            continue
        if child.name.startswith("."):
            continue
        if child.name in {"venv", "__pycache__", ".swift-cache"}:
            continue
        project_files = 0
        try:
            project_files = sum(1 for nested in child.iterdir() if nested.is_file())
        except Exception:
            project_files = 0
        projects.append(
            {
                "id": child.name,
                "name": child.name,
                "path": str(child),
                "fileCount": project_files,
            }
        )
    return projects


def _conversation_entries() -> list[dict[str, Any]]:
    return state_store.list_conversations()


def _current_provider(state: dict[str, Any]) -> str:
    providers = state.get("providers", {})
    if isinstance(providers, dict):
        active = str(providers.get("active", "local") or "local").strip()
        if active in KNOWN_PROVIDER_IDS:
            return active
        if active:
            return "ollama"
    return "local"


def _model_for_provider(state: dict[str, Any], provider: str) -> str:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return ""
    if provider == "openai":
        return str(providers.get("openai", {}).get("defaultModel", "") or "")
    if provider in {"gemini", "google_live"}:
        return str(providers.get("gemini", {}).get("defaultModel", "") or GOOGLE_LIVE_MODEL_DEFAULT)
    if provider == "anthropic":
        return str(providers.get("anthropic", {}).get("defaultModel", "") or "")
    if provider == "groq":
        return str(providers.get("groq", {}).get("defaultModel", "") or "")
    if provider == "custom":
        return str(providers.get("custom", {}).get("defaultModel", "") or "")
    if provider == "ollama":
        return str(providers.get("ollama", {}).get("defaultModel", "") or "")
    if provider == "lmstudio":
        return str(providers.get("lmstudio", {}).get("defaultModel", "") or "")
    if provider == "llamacpp":
        return str(providers.get("llamacpp", {}).get("defaultModel", "") or "")
    if provider == "local":
        return str(providers.get("local", {}).get("defaultModel", "") or "")
    return ""


def _provider_secret(provider: str) -> str:
    if provider in _PROVIDER_SECRET_OVERRIDES:
        return str(_PROVIDER_SECRET_OVERRIDES.get(provider, "") or "").strip()
    try:
        return str(state_store.volatile_provider_secrets().get(provider, "") or "").strip()
    except Exception:
        return ""


def _provider_config(state: dict[str, Any], provider: str) -> dict[str, Any]:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return {}
    provider_key = "gemini" if provider == "google_live" else provider
    cfg = dict(providers.get(provider_key, {}) or {})
    secret = _provider_secret(provider_key)
    if secret:
        cfg["apiKey"] = secret
    return cfg


def _routing_policy(state: dict[str, Any]) -> str:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return "local_first"
    policy = str(providers.get("routingPolicy", "local_first") or "local_first").strip().lower()
    return policy if policy in {"local_first", "cloud_fallback", "provider_lock"} else "local_first"


def _provider_enabled(state: dict[str, Any], provider: str) -> bool:
    if provider == "google_live":
        provider = "gemini"
    if provider == "local":
        local_cfg = _map_from(_map_from(state.get("providers")).get("local"))
        runtime_family = str(local_cfg.get("runtimeFamily", "") or _map_from(state.get("providers")).get("defaultLocalRuntime", "") or "ollama").strip().lower()
        provider = runtime_family if runtime_family in {"ollama", "lmstudio", "llamacpp"} else "ollama"
    if provider not in KNOWN_PROVIDER_IDS:
        return False
    cfg = _provider_config(state, provider)
    return _is_truthy(cfg.get("enabled", True))


def _provider_is_configured_for_chat(state: dict[str, Any], provider: str) -> bool:
    if provider == "local":
        local_cfg = _map_from(_map_from(state.get("providers")).get("local"))
        runtime_family = str(local_cfg.get("runtimeFamily", "") or _map_from(state.get("providers")).get("defaultLocalRuntime", "") or "ollama").strip().lower()
        target_provider = runtime_family if runtime_family in {"ollama", "lmstudio", "llamacpp"} else "ollama"
        return bool(_model_for_provider(state, target_provider))
    if provider in {"ollama", "lmstudio", "llamacpp"}:
        return bool(_model_for_provider(state, provider))
    if provider == "openai":
        cfg = _provider_config(state, "openai")
        return bool(cfg.get("apiKey") and _model_for_provider(state, "openai"))
    if provider in {"gemini", "google_live"}:
        cfg = _provider_config(state, "gemini")
        return bool(cfg.get("apiKey") and _model_for_provider(state, "gemini")) and _google_live_available()
    if provider == "groq":
        cfg = _provider_config(state, "groq")
        return bool(cfg.get("apiKey") and _model_for_provider(state, "groq"))
    if provider == "custom":
        cfg = _provider_config(state, "custom")
        return bool(cfg.get("apiKey") and cfg.get("baseUrl") and _model_for_provider(state, "custom"))
    if provider == "anthropic":
        cfg = _provider_config(state, "anthropic")
        return bool(cfg.get("apiKey") and _model_for_provider(state, "anthropic"))
    return False


def _local_runtime_family_from_state(state: dict[str, Any]) -> str:
    providers = _map_from(state.get("providers"))
    local_cfg = _map_from(providers.get("local"))
    runtime_family = str(
        local_cfg.get("runtimeFamily", "")
        or providers.get("defaultLocalRuntime", "")
        or "ollama"
    ).strip().lower()
    return runtime_family if runtime_family in {"ollama", "lmstudio", "llamacpp"} else "ollama"


def _local_runtime_client_from_state(
    state: dict[str, Any],
    provider_id: str = "",
) -> tuple[str, Any | None]:
    selected = str(provider_id or _local_runtime_family_from_state(state)).strip().lower() or "ollama"
    providers = _map_from(state.get("providers"))
    if selected == "lmstudio":
        cfg = _map_from(providers.get("lmstudio"))
        return selected, _make_lmstudio_client(
            base_url=str(cfg.get("baseUrl", "") or "http://127.0.0.1:1234/v1"),
            default_model=str(cfg.get("defaultModel", "") or ""),
        )
    if selected == "llamacpp":
        cfg = _map_from(providers.get("llamacpp"))
        return selected, _make_llamacpp_client(
            base_url=str(cfg.get("baseUrl", "") or "http://127.0.0.1:8080/v1"),
            default_model=str(cfg.get("defaultModel", "") or ""),
            binary_path=str(cfg.get("binaryPath", "") or ""),
            model_path=str(cfg.get("modelPath", "") or ""),
            auto_start=bool(cfg.get("autoStart", False)),
        )
    cfg = _map_from(providers.get("ollama"))
    return "ollama", _make_ollama_client(
        base_url=str(cfg.get("baseUrl", "") or "http://127.0.0.1:11434"),
        default_model=str(cfg.get("defaultModel", "") or ""),
    )


def _local_runtime_status_from_state(
    state: dict[str, Any],
    provider_id: str = "",
) -> tuple[str, dict[str, Any]]:
    provider, client = _local_runtime_client_from_state(state, provider_id)
    providers = _map_from(state.get("providers"))
    cfg = _map_from(providers.get(provider))
    base_url_defaults = {
        "ollama": "http://127.0.0.1:11434",
        "lmstudio": "http://127.0.0.1:1234/v1",
        "llamacpp": "http://127.0.0.1:8080/v1",
    }
    default_status = {
        "providerId": provider,
        "available": False,
        "reachable": False,
        "configured": _provider_is_configured_for_chat(state, provider),
        "baseUrl": str(cfg.get("baseUrl", "") or base_url_defaults.get(provider, "")),
        "defaultModel": _model_for_provider(state, provider),
        "latencyMs": 0,
        "lastCheckedAt": "",
        "errorCode": f"{provider}_client_unavailable",
        "jobs": [],
    }
    if client is None:
        return provider, default_status
    status = client.status() if hasattr(client, "status") else {}
    status = dict(status) if isinstance(status, dict) else {}
    status.setdefault("providerId", provider)
    status["configured"] = bool(status.get("configured", _provider_is_configured_for_chat(state, provider)))
    status["defaultModel"] = str(status.get("defaultModel", "") or _model_for_provider(state, provider))
    status["baseUrl"] = str(status.get("baseUrl", "") or default_status["baseUrl"])
    status["available"] = bool(status.get("available", False))
    status["reachable"] = bool(status.get("reachable", status.get("available", False)))
    status["latencyMs"] = max(0, int(status.get("latencyMs", 0) or 0))
    status["lastCheckedAt"] = str(status.get("lastCheckedAt", "") or "")
    status["errorCode"] = str(status.get("errorCode", "") or "")
    status["jobs"] = status.get("jobs", []) if isinstance(status.get("jobs"), list) else []
    return provider, status


def _selected_local_runtime_error(state: dict[str, Any]) -> str:
    provider, runtime_status = _local_runtime_status_from_state(state)
    if not _provider_enabled(state, provider):
        return "provider_disabled"
    if not bool(runtime_status.get("configured", False)):
        return "LOCAL_MODEL_NOT_CONFIGURED"
    if bool(runtime_status.get("reachable", False)):
        return ""
    error_code = str(runtime_status.get("errorCode", "") or "").strip().lower()
    if error_code == "request_timeout":
        return "LOCAL_MODEL_TIMEOUT"
    if error_code == "invalid_response":
        return "LOCAL_MODEL_INVALID_RESPONSE"
    if error_code in {"ollama_binary_missing", "llamacpp_binary_missing"}:
        return "LOCAL_MODEL_BINARY_MISSING"
    return "LOCAL_MODEL_UNREACHABLE"


def _semantic_candidate_providers(state: dict[str, Any], *, privacy_class: str) -> list[str]:
    active = _current_provider(state)
    policy = _routing_policy(state)
    fallback_to_cloud = _is_truthy(state.get("providers", {}).get("fallbackToCloud", True))
    cloud_candidates = ["openai", "gemini", "anthropic", "groq", "custom"]

    def configured(provider: str) -> bool:
        target = "ollama" if provider == "local" else provider
        return _provider_enabled(state, target) and _provider_is_configured_for_chat(state, target)

    if policy == "provider_lock":
        locked = "ollama" if active in {"local", "ollama"} else active
        return [locked] if configured(locked) else []

    if policy == "cloud_fallback":
        ordered: list[str] = []
        if active not in {"local", "ollama"} and configured(active):
            ordered.append(active)
        for provider in cloud_candidates:
            if provider != active and configured(provider):
                ordered.append(provider)
        if configured("ollama"):
            ordered.append("ollama")
        return ordered

    ordered = []
    if configured("ollama"):
        ordered.append("ollama")
    if fallback_to_cloud and privacy_class == "public_text":
        active_cloud = active if active not in {"local", "ollama"} else ""
        if active_cloud and configured(active_cloud):
            ordered.append(active_cloud)
        for provider in cloud_candidates:
            if provider != active_cloud and configured(provider):
                ordered.append(provider)
    return ordered


def _chat_messages(
    conversation: list[dict[str, Any]],
    text: str,
    *,
    allow_system: bool = True,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    allowed_roles = {"system", "user", "assistant"} if allow_system else {"user", "assistant"}
    for item in conversation:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "user") or "user")
        content = str(item.get("text", "") or "").strip()
        if role not in allowed_roles or not content:
            continue
        messages.append({"role": role, "content": content})
    current_text = str(text or "").strip()
    if current_text:
        if not messages or messages[-1].get("role") != "user" or messages[-1].get("content") != current_text:
            messages.append({"role": "user", "content": current_text})
    return messages


def _requires_tool_capable_route(text: str) -> bool:
    lowered = f" {str(text or '').lower()} "
    keyword_patterns = [
        r"\baç\b",
        r"\baçabilir\b",
        r"\bbaşlat\b",
        r"\bçalıştır\b",
        r"\btıkla\b",
        r"\byaz\b",
        r"\bara\b",
        r"\btakvim\b",
        r"\bhatırlat",
        r"\bwhatsapp\b",
        r"\bekran\b",
        r"\buygulama\b",
        r"\bdosya\b",
        r"\bpdf\b",
        r"\bcsv\b",
        r"\bjson\b",
        r"\bchart\b",
        r"\bgrafik\b",
        r"\blatex\b",
        r"\bgorsel\b",
        r"\bresim\b",
        r"\baudio\b",
        r"\btranskript\b",
        r"\bterminal\b",
        r"\bkomut\b",
        r"\bdocx\b",
        r"\bword\b",
        r"\bxlsx\b",
        r"\bexcel\b",
        r"\btablo\b",
        r"\bpptx\b",
        r"\bsunum\b",
        r"\bslide\b",
        r"\byoutube\b",
        r"\bspotify\b",
        r"\bçal\b",
        r"\bkapat\b",
        r"\bsil\b",
        r"\bkaydet\b",
        r"\bquit\b",
        r"\bterminate\b",
        r"\bsaat\b",
        r"\btarih\b",
        r"\bhava\b",
        r"\bopen\b",
        r"\blaunch\b",
        r"\bclick\b",
        r"\btype\b",
        r"\bcalendar\b",
        r"\breminder\b",
        r"\bbrowser\b",
    ]
    return any(re.search(pattern, lowered) for pattern in keyword_patterns)


def _approve_like_request(text: str) -> bool:
    normalized = _normalise_text(text)
    return normalized in {"onayla", "approve", "tamam", "devam et", "uygula", "gonder", "gönder"}


def _cancel_like_request(text: str) -> bool:
    normalized = _normalise_text(text)
    return normalized in {"iptal et", "iptal", "cancel", "vazgec", "vazgeç", "hayir", "hayır"}


def _looks_like_plan_revision(text: str) -> bool:
    normalized = _normalise_text(text)
    if not normalized:
        return False
    revision_patterns = (
        " yerine ",
        " yarina al",
        " yarına al",
        " bir saat ertele",
        " sonra yap",
        " yap",
        " saat",
        ":",
    )
    return any(pattern in normalized for pattern in revision_patterns)


def _looks_like_document_followup(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(token in normalized for token in ("bunu", "onu", "belgeyi", "dosyayi", "dosyayı")) and any(
        token in normalized for token in ("ozetle", "özetle", "oku", "madde", "listele", "cikar", "çıkar")
    )


def _looks_like_image_followup(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(token in normalized for token in ("bunu", "onu", "gorseli", "görseli", "resmi", "fotografi", "fotoğrafı")) and any(
        token in normalized
        for token in ("incele", "ozetle", "özetle", "metadata", "meta", "boyut", "cozunurluk", "çözünürlük", "palette", "palet", "renk")
    )


def _looks_like_audio_followup(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(token in normalized for token in ("bunu", "onu", "ayni dosya", "aynı dosya", "kaydi", "kaydı", "audio")) and any(
        token in normalized
        for token in ("transkript", "transcribe", "yaziya cevir", "yazıya çevir", "metne cevir", "metne çevir")
    )


def _looks_like_data_followup(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(token in normalized for token in ("bunu", "onu", "tabloyu", "veriyi", "csvyi", "jsonu")) and any(
        token in normalized for token in ("analiz", "profil", "incele", "preview", "onizleme", "önizleme", "istatistik")
    )


def _looks_like_chart_followup(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(token in normalized for token in ("bunu", "onu", "tabloyu", "veriyi", "bundan", "ayni veriden", "aynı veriden")) and any(
        token in normalized for token in ("grafik", "chart", "histogram", "scatter", "bar", "line")
    )


def _looks_like_app_followup(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(token in normalized for token in ("onu", "bunu", "uygulamayi", "uygulamayı")) and any(
        token in normalized for token in ("kapat", "ac", "aç", "open", "close")
    )


def _with_selected_paths(args: dict[str, Any], source_args: dict[str, Any]) -> dict[str, Any]:
    payload = dict(args)
    selected_paths = source_args.get("_selectedPaths", [])
    if isinstance(selected_paths, list):
        cleaned = [str(item).strip() for item in selected_paths if str(item).strip()]
        if cleaned:
            payload["_selectedPaths"] = cleaned[:3]
    return payload


def _safe_error_code(raw: Any) -> str:
    value = str(raw or "chat_failed").strip()
    if not value:
        return "CHAT_FAILED"
    normalised = re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").upper()
    return normalised[:80] or "CHAT_FAILED"


_TRANSPORT_SECRET_KEYS = {
    "accessToken",
    "refreshToken",
    "runtimeToken",
    "deviceSecret",
    "pairingToken",
    "lastSessionId",
    "connectionId",
}


def _public_state_snapshot() -> dict[str, Any]:
    return state_store.public_snapshot()


def _sanitize_transport_payload(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if key == "state" and isinstance(item, dict):
                sanitized[key] = state_store.public_snapshot(item)
                continue
            if key in _TRANSPORT_SECRET_KEYS:
                sanitized[key] = ""
                continue
            sanitized[key] = _sanitize_transport_payload(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_transport_payload(item) for item in value]
    return value


def _safe_chat_error_message(raw: Any) -> str:
    value = str(raw or "").strip()
    if value == "PERMISSION_REQUIRED":
        return "Bu işlem için güvenlik izni gerekiyor."
    if value == "UNSUPPORTED_PLATFORM":
        return "Bu özellik bu işletim sisteminde desteklenmiyor."
    if value in {"CAPABILITY_UNAVAILABLE", "DEPENDENCY_UNAVAILABLE"}:
        return "Bu özellik bu kurulumda hazır değil."
    if value == "TIMEOUT":
        return "İşlem güvenli zaman aşımı sınırına ulaştı."
    if value == "TOOL_EXECUTION_FAILED":
        return "Araç güvenli şekilde tamamlanamadı."
    if value == "UNKNOWN_CAPABILITY":
        return "Bu görev için uygun yerel araç bulunamadı."
    if value in {"ollama_model_missing", "model_required"}:
        return "Yerel model seçilmemiş."
    if value in {"LOCAL_MODEL_NOT_CONFIGURED", "local_model_not_configured", "local_model_not_selected"}:
        return "Seçili yerel runtime yapılandırılmamış."
    if value in {"LOCAL_MODEL_UNREACHABLE", "provider_unreachable", "ollama_client_unavailable", "lmstudio_client_unavailable", "llamacpp_client_unavailable"}:
        return "Seçili yerel runtime'a ulaşılamıyor."
    if value in {"LOCAL_MODEL_TIMEOUT", "request_timeout"}:
        return "Seçili yerel runtime zaman aşımına uğradı."
    if value in {"LOCAL_MODEL_INVALID_RESPONSE", "invalid_response"}:
        return "Seçili yerel runtime geçerli bir yanıt üretmedi."
    if value in {"LOCAL_MODEL_BINARY_MISSING", "ollama_binary_missing", "llamacpp_binary_missing"}:
        return "Seçili yerel runtime ikilisi bu kurulumda bulunamadı."
    if value in {"google_api_key_missing", "google_genai_missing", "tool_capable_provider_required"}:
        return "Bu görev için araç destekli runtime yapılandırması gerekiyor."
    if value in {"WEB_RESEARCH_FAILED", "GMAIL_SEND_FAILED"}:
        return "Bu görev güvenli şekilde tamamlanamadı."
    if value.endswith("_config_missing"):
        return "Seçili sağlayıcı yapılandırması eksik."
    if value == "provider_disabled":
        return "Elyan şu anda uygun konuşma yoluna bağlanamadı."
    if value == "LOCAL_PRIVATE_CLOUD_ESCALATION_BLOCKED":
        return "Bu yerel görev için bulut yükseltmesi açık izin olmadan kullanılamaz."
    if value == "CLARIFICATION_REQUIRED":
        return "Görevi güvenli şekilde yürütmek için biraz daha netlik gerekiyor."
    return "Görev güvenli şekilde tamamlanamadı."


def _safe_auth_error(result: BackendResult, fallback_code: str, fallback_message: str) -> dict[str, str]:
    code = _safe_error_code(result.error or fallback_code)
    status_code = int(result.status_code or 0)
    message = fallback_message
    if status_code in {400, 401, 403}:
        message = "E-posta veya şifre doğrulanamadı."
    elif status_code == 409:
        message = "Bu e-posta için zaten bir hesap var."
    elif status_code >= 500:
        message = "Backend geçici olarak yanıt veremiyor."
    elif result.error:
        message = str(result.error).replace("_", " ").strip().capitalize() or fallback_message
    return {"code": code, "message": message}


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        payload = json.loads(text[start : end + 1])
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _intent_confidence(value: Any, fallback: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return fallback
    return max(0.0, min(1.0, score))


def _task_intelligence_prompt_context(state: dict[str, Any]) -> str:
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        return ""
    routes = intelligence.get("recentSuccessfulRoutes", [])
    misroutes = intelligence.get("recentMisroutes", [])
    clarifications = intelligence.get("recentClarifications", [])
    patterns = intelligence.get("confirmedPlanPatterns", [])
    response_style = intelligence.get("responseStyle", {})
    parts: list[str] = []
    if isinstance(routes, list) and routes:
        compact = []
        for item in routes[:4]:
            if not isinstance(item, dict):
                continue
            compact.append(
                f"{str(item.get('query', '')).strip()} => {str(item.get('capability', '')).strip()} ({str(item.get('intent', '')).strip()})"
            )
        if compact:
            parts.append("Recent successful routes:\n" + "\n".join(f"- {line}" for line in compact))
    if isinstance(patterns, list) and patterns:
        compact_patterns = []
        for item in patterns[:4]:
            if not isinstance(item, dict):
                continue
            compact_patterns.append(
                f"{str(item.get('query', '')).strip()} => {str(item.get('capability', '')).strip()}"
            )
        if compact_patterns:
            parts.append("Confirmed plan patterns:\n" + "\n".join(f"- {line}" for line in compact_patterns))
    if isinstance(misroutes, list) and misroutes:
        compact_misroutes = []
        for item in misroutes[:3]:
            if not isinstance(item, dict):
                continue
            compact_misroutes.append(
                f"{str(item.get('query', '')).strip()} => avoid weak route {str(item.get('capability', '')).strip()}"
            )
        if compact_misroutes:
            parts.append("Recent misroutes to avoid:\n" + "\n".join(f"- {line}" for line in compact_misroutes))
    if isinstance(clarifications, list) and clarifications:
        compact_clarifications = []
        for item in clarifications[:3]:
            if not isinstance(item, dict):
                continue
            compact_clarifications.append(
                f"{str(item.get('query', '')).strip()} => ask {str(item.get('question', '')).strip()}"
            )
        if compact_clarifications:
            parts.append(
                "Recent clarification patterns:\n"
                + "\n".join(f"- {line}" for line in compact_clarifications)
            )
    if isinstance(response_style, dict):
        length = str(response_style.get("length", "") or "").strip()
        directness = str(response_style.get("directness", "") or "").strip()
        tone = str(response_style.get("tone", "") or "").strip()
        if length or directness or tone:
            parts.append(
                "Response style: "
                + ", ".join(item for item in [length, directness, tone] if item)
            )
    return "\n\n".join(parts)


def _semantic_acceptance_threshold(state: dict[str, Any]) -> float:
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        return 0.58
    current = intelligence.get("clarificationCount", 0)
    try:
        penalty = min(0.1, max(0.0, float(current) * 0.01))
    except (TypeError, ValueError):
        penalty = 0.0
    return 0.58 + penalty


def _semantic_capability_penalty(capability: str) -> float:
    quality = STATE.capability_quality_snapshot(capability)
    negatives = (
        int(quality.get("clarifications", 0) or 0)
        + int(quality.get("revisions", 0) or 0)
        + int(quality.get("rejections", 0) or 0)
        + int(quality.get("misroutes", 0) or 0)
    )
    positives = int(quality.get("successes", 0) or 0)
    raw_penalty = (negatives * 0.02) - (positives * 0.01)
    return max(0.0, min(0.12, raw_penalty))


def _semantic_requires_plan_from_history(capability: str) -> bool:
    if not capability or capability in SIDE_EFFECT_CAPABILITIES:
        return False
    quality = STATE.capability_quality_snapshot(capability)
    negatives = (
        int(quality.get("revisions", 0) or 0)
        + int(quality.get("rejections", 0) or 0)
        + int(quality.get("misroutes", 0) or 0)
    )
    positives = int(quality.get("successes", 0) or 0)
    return negatives >= 2 and negatives > positives


def _semantic_misroute_question(state: dict[str, Any], text: str, capability: str) -> str:
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        return ""
    misroutes = intelligence.get("recentMisroutes", [])
    if not isinstance(misroutes, list):
        return ""
    normalized_query = _normalise_text(text)
    best_score = 0.0
    for item in misroutes[:8]:
        if not isinstance(item, dict):
            continue
        if capability and str(item.get("capability", "") or "").strip() not in {"", capability}:
            continue
        candidate = _normalise_text(str(item.get("query", "") or ""))
        if not candidate:
            continue
        score = difflib.SequenceMatcher(None, normalized_query, candidate).ratio()
        if normalized_query in candidate or candidate in normalized_query:
            score = max(score, 0.82)
        best_score = max(best_score, score)
    if best_score >= 0.78:
        return "Bu isteği yanlış yürütmemek için hedefi biraz daha netleştirir misin?"
    return ""


def _clarification_response(question: str, *, intent: str = "clarification", privacy_class: str = "public_text") -> dict[str, Any]:
    return {
        "ok": True,
        "content": question,
        "provider": "local_planner",
        "toolEvents": [],
        "intent": intent,
        "confidence": 0.0,
        "executionMode": "clarification",
        "clarificationNeeded": True,
        "clarificationQuestion": question,
        "needsConfirmation": False,
        "privacyClass": privacy_class,
        "planPreview": None,
    }


def _permission_needed_response(reason: str, *, intent: str = "permission", privacy_class: str = "local_private") -> dict[str, Any]:
    return {
        "ok": True,
        "content": reason,
        "provider": "local_planner",
        "toolEvents": [],
        "intent": intent,
        "confidence": 0.0,
        "executionMode": "permission_needed",
        "clarificationNeeded": False,
        "permissionNeeded": True,
        "permissionReason": reason,
        "needsConfirmation": False,
        "privacyClass": privacy_class,
        "planPreview": None,
    }


def _agent_status_from_result(result: dict[str, Any], *, active: bool = False) -> dict[str, Any]:
    structured_result = result.get("structuredResult")
    structured_result = structured_result if isinstance(structured_result, dict) else {}
    kind = str(structured_result.get("kind", "") or "").strip().lower()
    execution_mode = str(result.get("executionMode", "") or "").strip().lower()
    intent = str(result.get("intent", "") or "").strip().lower()
    confidence = _intent_confidence(result.get("confidence"), 0.0)
    retrieval_used = bool(result.get("retrievalUsed", False))
    shared_retrieval_used = bool(result.get("sharedRetrievalUsed", False))
    permission_needed = bool(result.get("permissionNeeded", False) or result.get("needsConfirmation", False))

    verification_used = False
    verification_reason = ""
    if retrieval_used or shared_retrieval_used:
        verification_used = True
        verification_reason = "context"
    elif kind in {"document_read", "ocr_read", "retrieve_context", "mcp_call_tool"}:
        verification_used = True
        verification_reason = kind
    elif execution_mode in {"plan_preview", "confirmed_plan", "clarification"}:
        verification_used = True
        verification_reason = execution_mode
    elif confidence > 0 and confidence < 0.84:
        verification_used = True
        verification_reason = "low_confidence"
    elif intent in {"document_read", "ocr_read", "retrieve_context", "mcp_call_tool", "run_skill"}:
        verification_used = True
        verification_reason = intent

    if permission_needed:
        display_stage = "Onay bekliyor"
    elif active:
        display_stage = "Bakıyor"
    elif verification_used:
        display_stage = "Kontrol ediyor"
    else:
        display_stage = "Hazır"

    display_action = display_stage
    if retrieval_used or shared_retrieval_used:
        display_action = "Kaynak topluyor" if active else "Kontrol ediyor"

    return {
        "active": bool(active),
        "displayStage": display_stage,
        "displayAction": display_action,
        "verificationUsed": verification_used,
        "verificationReason": verification_reason,
        "executionStrategy": "balanced",
    }


def _record_task_intelligence_outcome(
    outcome: str,
    *,
    query: str,
    intent: str,
    capability: str,
    args: dict[str, Any] | None = None,
    conversation_id: str = "",
    question: str = "",
    corrected_to: str = "",
) -> None:
    try:
        STATE.record_route_outcome(
            outcome=outcome,
            query=query,
            intent=intent,
            capability=capability,
            args=args,
            conversation_id=conversation_id,
            question=question,
            corrected_to=corrected_to,
        )
    except Exception:
        return


def _semantic_missing_argument_question(capability: str, args: dict[str, Any]) -> str:
    payload = dict(args) if isinstance(args, dict) else {}
    if capability in {"open_app", "close_app"}:
        if not str(payload.get("app_name", "") or "").strip():
            action = "açayım" if capability == "open_app" else "kapatayım"
            return f"Hangi uygulamayı {action}?"
    if capability == "browser_control":
        action = str(payload.get("action", "") or "").strip()
        if action == "open_url" and not str(payload.get("url", "") or "").strip():
            return "Hangi adresi açayım?"
        if action in {"search", "play_youtube"} and not str(payload.get("query", "") or "").strip():
            return "Ne aramamı istiyorsun?"
    if capability in {"document_read", "ocr_read", "image_read", "data_analyze", "chart_generate"}:
        if not str(payload.get("path", "") or "").strip():
            if capability == "chart_generate":
                return "Hangi CSV/JSON dosyasından grafik üreteyim?"
            if capability == "data_analyze":
                return "Hangi CSV/JSON dosyasını analiz edeyim?"
            if capability == "image_read":
                return "Hangi görseli inceleyeyim?"
            if capability == "ocr_read":
                return "Hangi belge veya görseldeki metni okuyayım?"
            return "Hangi belgeyi açayım?"
    if capability == "image_generate" and not str(payload.get("prompt", "") or "").strip():
        return "Nasıl bir görsel üretmemi istiyorsun?"
    if capability in {"math_solve", "latex_parse"}:
        if not str(payload.get("expression", "") or "").strip():
            return "Hangi ifadeyi çözmemi istiyorsun?"
    if capability == "retrieve_context" and not str(payload.get("query", "") or "").strip():
        return "Tam olarak hangi bilgiyi arayayım?"
    if capability == "speech_to_text":
        audio_path = str(payload.get("audioPath", "") or payload.get("audio_path", "") or "").strip()
        session_id = str(payload.get("sessionId", "") or payload.get("session_id", "") or "").strip()
        if not audio_path and not session_id:
            return "Hangi ses kaydını yazıya dökeyim?"
    if capability == "text_to_speech" and not str(payload.get("text", "") or "").strip():
        return "Sesli okumamı istediğin metin ne?"
    if capability == "shell_run" and not str(payload.get("command", "") or "").strip():
        return "Hangi komutu çalıştırayım?"
    return ""


def _retrieval_sources_for_provider(provider: str) -> list[str]:
    sources = ["workspace", "conversations"] if provider in {"ollama", "local"} else ["conversations"]
    if provider in {"ollama", "local"} and native_file_indexer.indexing_enabled() and native_file_indexer.approved_roots():
        sources.append("local_files")
    return sources


def _default_local_retrieval_sources() -> list[str]:
    sources = ["workspace", "conversations"]
    if native_file_indexer.indexing_enabled() and native_file_indexer.approved_roots():
        sources.append("local_files")
    return sources


def _retrieve_local_context_result(
    state: dict[str, Any],
    text: str,
    *,
    sources: list[str],
    conversation_id: str = "",
    limit: int = 6,
) -> dict[str, Any] | None:
    try:
        retrieved = run_capability(
            "retrieve_context",
            {
                "query": text,
                "sources": sources,
                "limit": limit,
                "conversationId": conversation_id,
            },
            state,
        )
    except Exception:
        return None
    if not retrieved.get("ok"):
        return None
    result = retrieved.get("result")
    return dict(result) if isinstance(result, dict) else None


def _filter_retrieval_matches(retrieval: dict[str, Any] | None, *, allowed_sources: list[str]) -> dict[str, Any] | None:
    if not isinstance(retrieval, dict):
        return None
    matches = retrieval.get("matches", [])
    matches = [item for item in matches if isinstance(item, dict) and str(item.get("source", "") or "") in allowed_sources]
    if not matches:
        return None
    return {
        "kind": "retrieve_context",
        "sources": allowed_sources,
        "matches": matches,
        "strategy": str(retrieval.get("strategy", "lexical") or "lexical"),
        "model": str(retrieval.get("model", "") or ""),
        "indexedAt": str(retrieval.get("indexedAt", "") or ""),
        "cacheReady": bool(retrieval.get("cacheReady", False)),
        "localIndexStatus": retrieval.get("localIndexStatus")
        if isinstance(retrieval.get("localIndexStatus"), dict)
        else {},
        "localFileIndex": retrieval.get("localFileIndex")
        if isinstance(retrieval.get("localFileIndex"), dict)
        else {},
        "sourceStatus": retrieval.get("sourceStatus")
        if isinstance(retrieval.get("sourceStatus"), dict)
        else {},
    }


def _format_retrieval_context(retrieval: dict[str, Any] | None) -> str:
    if not isinstance(retrieval, dict):
        return ""
    matches = retrieval.get("matches", [])
    if not isinstance(matches, list) or not matches:
        return ""
    lines: list[str] = []
    for item in matches[:4]:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source", "") or "").strip()
        title = str(item.get("title", "") or "").strip()
        snippet = str(item.get("snippet", "") or "").strip()
        if not snippet:
            continue
        compact_snippet = " ".join(snippet.split())
        if len(compact_snippet) > 220:
            compact_snippet = compact_snippet[:219].rstrip() + "…"
        lines.append(f"- [{source}] {title}: {compact_snippet}")
    if not lines:
        return ""
    return "Relevant local context:\n" + "\n".join(lines)


def _retrieve_planning_context(state: dict[str, Any], text: str, conversation_id: str = "") -> dict[str, Any] | None:
    return _retrieve_local_context_result(
        state,
        text,
        sources=_default_local_retrieval_sources(),
        conversation_id=conversation_id,
        limit=6,
    )


def _should_retrieve_context(text: str, privacy_class: str) -> bool:
    if privacy_class == "local_private":
        return True
    normalized = _normalise_text(text)
    return any(
        token in normalized
        for token in (
            "bunu",
            "onu",
            "onceki",
            "önceki",
            "gecen",
            "geçen",
            "workspace",
            "proje",
            "notlar",
            "madde",
            "maddeler",
            "konusma",
            "konuşma",
        )
    )


def _is_local_private_chat_request(text: str) -> bool:
    normalized = _normalise_text(text)
    return any(
        token in normalized
        for token in (
            "dosya",
            "belge",
            "pdf",
            "docx",
            "xlsx",
            "pptx",
            "excel",
            "word",
            "sunum",
            "ekran",
            "takvim",
            "hatirlatici",
            "hatırlatıcı",
            "uygulama",
            "terminal",
            "komut",
            "sistem",
        )
    )


def _plan_preview_with_retrieval(plan_preview: dict[str, Any] | None, retrieval: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(plan_preview, dict) or not isinstance(retrieval, dict):
        return plan_preview
    matches = retrieval.get("matches", [])
    if not isinstance(matches, list) or not matches:
        return plan_preview
    sources = sorted({str(item.get("source", "") or "").strip() for item in matches if isinstance(item, dict)})
    if not sources:
        return plan_preview
    summary = str(plan_preview.get("summary", "") or "").strip()
    source_summary = f" Kaynak: {', '.join(source for source in sources if source)}."
    if source_summary.strip() not in summary:
        plan_preview = dict(plan_preview)
        plan_preview["summary"] = (summary + source_summary).strip()
    return plan_preview


def _retrieval_result_metadata(retrieval: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(retrieval, dict):
        return {
            "retrievalUsed": False,
            "retrievalStrategy": "",
            "retrievalSources": [],
            "retrievalMatchCount": 0,
        }
    matches = retrieval.get("matches", [])
    matches = [item for item in matches if isinstance(item, dict)]
    sources = sorted({str(item.get("source", "") or "").strip() for item in matches if str(item.get("source", "") or "").strip()})
    return {
        "retrievalUsed": bool(matches),
        "retrievalStrategy": str(retrieval.get("strategy", "") or ""),
        "retrievalSources": sources,
        "retrievalMatchCount": len(matches),
    }


def _brain_profile_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _brain_profile_sections(profile: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    payload = _brain_profile_payload(profile)
    chat = _brain_profile_payload(payload.get("chat"))
    learning = _brain_profile_payload(payload.get("learning"))
    retrieval = _brain_profile_payload(payload.get("retrieval"))
    return chat, learning, retrieval


def _brain_profile_model_snapshot(profile: dict[str, Any] | None) -> dict[str, Any]:
    chat, learning, retrieval = _brain_profile_sections(profile)
    bridge = _brain_profile_payload(_brain_profile_payload(profile).get("bridge"))
    training = _brain_profile_payload(_brain_profile_payload(profile).get("training"))
    pipeline = _brain_profile_payload(training.get("pipeline"))
    promotion = _brain_profile_payload(pipeline.get("promotion"))
    inference_ready = bool(chat.get("inferenceReady", False))
    runtime_ready = bool(pipeline.get("runtimeReady", False))
    return {
        "dispatchPath": str(chat.get("dispatchPath", "") or ""),
        "brainProfilePath": str(chat.get("brainProfilePath", "") or ""),
        "realtimePath": str(chat.get("realtimePath", "") or ""),
        "activeSharedModel": str(chat.get("activeSharedModel", "") or ""),
        "activeUserModel": str(chat.get("activeUserModel", "") or ""),
        "localProviderHint": str(chat.get("localProviderHint", "") or ""),
        "inferenceReady": inference_ready,
        "servingProvider": str(chat.get("servingProvider", "") or ""),
        "baseModel": str(chat.get("baseModel", "") or ""),
        "activeAdapter": str(chat.get("activeAdapter", "") or ""),
        "warmupJobId": str(chat.get("warmupJobId", "") or ""),
        "serverBrainName": str(chat.get("serverBrainName", "") or "Elyan"),
        "serverTargetDeviceId": str(chat.get("serverTargetDeviceId", "") or ""),
        "runtimeReady": runtime_ready,
        "bridge": {
            "mode": str(bridge.get("mode", "") or ""),
            "taskRouting": str(bridge.get("taskRouting", "") or ""),
            "chatRouting": str(bridge.get("chatRouting", "") or ""),
            "desktopAvailable": bool(bridge.get("desktopAvailable", False)),
            "mobileAvailable": bool(bridge.get("mobileAvailable", False)),
            "connectedDesktopDevices": int(bridge.get("connectedDesktopDevices", 0) or 0),
            "serverBrainReady": bool(bridge.get("serverBrainReady", inference_ready)),
            "fallbackRoute": str(bridge.get("fallbackRoute", "") or ""),
        },
        "connection": {
            "mode": str(chat.get("connection", {}).get("mode", "") or ""),
            "desktopAvailable": bool(_brain_profile_payload(chat.get("connection")).get("desktopAvailable", False)),
            "mobileAvailable": bool(_brain_profile_payload(chat.get("connection")).get("mobileAvailable", False)),
            "connectedDesktopDevices": int(_brain_profile_payload(chat.get("connection")).get("connectedDesktopDevices", 0) or 0),
            "inferenceReady": bool(_brain_profile_payload(chat.get("connection")).get("inferenceReady", inference_ready)),
            "serverBrainReady": bool(_brain_profile_payload(chat.get("connection")).get("serverBrainReady", inference_ready)),
            "fallbackRoute": str(_brain_profile_payload(chat.get("connection")).get("fallbackRoute", "") or ""),
        },
        "promotionReadySharedModelCount": int(promotion.get("readySharedModelCount", 0) or 0),
        "promotionActiveSharedModelId": str(promotion.get("activeSharedModelId", "") or ""),
        "promotionRollbackSharedModelId": str(promotion.get("rollbackSharedModelId", "") or ""),
        "promotionEvaluationState": str(promotion.get("evaluationState", "") or ""),
        "isChatUsable": bool(chat.get("isChatUsable", inference_ready)),
        "userUnderstandingEnabled": bool(learning.get("userUnderstandingEnabled", False)),
        "personalizationEnabled": bool(learning.get("personalizationEnabled", False)),
        "readyDocuments": int(retrieval.get("readyDocuments", 0) or 0),
        "readyChunks": int(retrieval.get("readyChunks", 0) or 0),
    }


def _brain_profile_local_provider_hint(profile: dict[str, Any] | None) -> str:
    snapshot = _brain_profile_model_snapshot(profile)
    for key in ("servingProvider", "localProviderHint"):
        value = str(snapshot.get(key, "") or "").strip().lower()
        if value:
            return value
    return ""


def _shared_brain_search_items(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    source = _brain_profile_payload(payload)
    for key in ("results", "items", "matches", "documents", "chunks"):
        value = source.get(key)
        if isinstance(value, list):
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _safe_brain_snippet(value: Any, *, limit: int = 240) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return ""
    text = re.sub(r"(?:[A-Za-z]:)?[/~][^\s]+", "[redacted-path]", text)
    text = re.sub(r"\b[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{10,}\b", "[redacted-token]", text)
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _shared_brain_prompt_context(payload: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    items = _shared_brain_search_items(payload)
    if not items:
        return "", {
            "sharedRetrievalUsed": False,
            "sharedRetrievalCount": 0,
            "sharedRetrievalSources": [],
        }
    lines: list[str] = []
    sources: set[str] = set()
    for item in items[:4]:
        source = str(
            item.get("source")
            or item.get("sourceType")
            or item.get("kind")
            or item.get("collection")
            or "shared"
        ).strip()
        title = _safe_brain_snippet(
            item.get("title")
            or item.get("name")
            or item.get("documentTitle")
            or item.get("sourceTitle")
            or source,
            limit=80,
        )
        snippet = _safe_brain_snippet(
            item.get("snippet")
            or item.get("summary")
            or item.get("text")
            or item.get("content")
            or item.get("chunkText"),
        )
        if not snippet:
            continue
        sources.add(source or "shared")
        lines.append(f"- [{source or 'shared'}] {title}: {snippet}")
    if not lines:
        return "", {
            "sharedRetrievalUsed": False,
            "sharedRetrievalCount": 0,
            "sharedRetrievalSources": [],
        }
    return (
        "Relevant shared knowledge:\n" + "\n".join(lines),
        {
            "sharedRetrievalUsed": True,
            "sharedRetrievalCount": len(items),
            "sharedRetrievalSources": sorted(source for source in sources if source),
        },
    )


def _conversation_system_context(conversation: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in conversation:
        if not isinstance(item, dict):
            continue
        if str(item.get("role", "") or "").strip() != "system":
            continue
        text = str(item.get("text", "") or "").strip()
        if text:
            lines.append(text)
    return "\n\n".join(lines[:4])


def _artifact_selection_status_payload() -> dict[str, Any]:
    payload = STATE.artifact_selection_status()
    return payload if isinstance(payload, dict) else {"selectedCount": 0, "activeKinds": []}


def _semantic_understanding_prompt(
    text: str,
    state: dict[str, Any],
    retrieval_context: str = "",
    mcp_context: str = "",
) -> str:
    learning = _task_intelligence_prompt_context(state)
    skill_context = skill_runtime.planner_skill_context(state)
    platform_name = "macOS" if sys.platform == "darwin" else ("Windows" if os.name == "nt" else "Linux")
    guidance = (
        "You are Elyan local intent planner. Output one JSON object only. "
        "Map the request to one of these capabilities if possible: "
        "open_app, close_app, sys_info, get_weather, get_calendar_events, add_calendar_event, "
        "get_reminders, add_reminder, browser_control, send_whatsapp_message, save_whatsapp_contact, document_read, document_write, "
        "spreadsheet_write, presentation_write, ocr_read, image_read, data_analyze, chart_generate, math_solve, latex_parse, retrieve_context, "
        "mcp_call_tool, run_skill, "
        "speech_to_text, text_to_speech, "
        "analyze_screen, get_youtube_channel_report, shell_run, play_media. "
        "If the request is unsupported or general chat, use intent=chat and capability=\"\". "
        "Set confidence between 0 and 1. "
        "Set requiresConfirmation=true for side-effect actions, file writes, scheduling writes, personal actions, shell execution, or multi-step actions. "
        "Set privacyClass=local_private for files, screen, system details, calendar, reminders, personal actions, apps, shell; otherwise public_text. "
        "If a browser action is needed, args.action must be one of search, open_url, play_youtube. "
        "browser_control, play_media, and analyze_screen require explicit local permission before execution. "
        "add_calendar_event, add_reminder, send_whatsapp_message, and save_whatsapp_contact require explicit local personal-action permission before execution. "
        "If document_read is chosen, args.mode must be read, summary, or bullets. "
        "If send_whatsapp_message is chosen, args must include message and may include recipient_name, phone_number, app_target, send_now. "
        "If save_whatsapp_contact is chosen, args must include display_name and phone_number and may include aliases. "
        "If document_write is chosen, args may include outputPath, title, sourcePath, sourceContext, overwrite. "
        "If spreadsheet_write is chosen, args may include outputPath, title, columns, rows, sourceContext, overwrite. "
        "If presentation_write is chosen, args may include outputPath, title, slides, sourceContext, overwrite. "
        "If ocr_read is chosen, args.mode must be read, summary, or bullets. "
        "If image_read is chosen, args.mode must be summary, metadata, or palette. "
        "If data_analyze is chosen, args.mode must be summary, profile, or preview. "
        "If chart_generate is chosen, args.chartType must be bar, line, scatter, or histogram. "
        "If math_solve is chosen, args.mode must be solve, simplify, factor, expand, or evaluate. "
        "If latex_parse is chosen, args.mode must be parse or normalize. "
        "If retrieve_context is chosen, args must include query and optional sources. "
        "If mcp_call_tool is chosen, args must include serverId, toolName, and arguments. "
        "If run_skill is chosen, args must include skillId and may include payload. "
        "If speech_to_text is chosen, args may include audioPath, sessionId, and languageHint. "
        "If text_to_speech is chosen, args must include text and may include languageHint, voice, interrupt. "
        "If shell_run is chosen, args.command must be a simple argv-style command without shell operators. "
        "Prefer clarification over guessing missing targets, files, recipients, URLs, commands, or expressions. "
        "For complex requests, preserve the user's real goal, keep args minimal and exact, and use planPreview with ordered steps instead of collapsing everything into one guessed tool call. "
        "Do not invent file paths, app names, query text, recipients, or document contents. "
        "If the request clearly involves multiple sequential actions, set isMultiStep=true and include planPreview with summary and steps. "
        "Never invent unsupported capabilities."
    )
    if sys.platform != "darwin":
        guidance = (
            f"{guidance} Current platform is {platform_name}. "
            "Do not choose macOS-only capabilities such as open_app, close_app, calendar/reminder desktop helpers, "
            "analyze_screen, Spotify or Apple Music desktop playback, or WhatsApp desktop automation. "
            "Prefer browser_control, YouTube media playback, or WhatsApp Web draft flows when suitable."
        )
    if learning:
        guidance = f"{guidance}\n\n{learning}"
    if retrieval_context:
        guidance = f"{guidance}\n\n{retrieval_context}"
    if mcp_context:
        guidance = f"{guidance}\n\n{mcp_context}"
    if skill_context:
        guidance = f"{guidance}\n\n{skill_context}"
    return (
        f"{guidance}\n\n"
        "Return JSON with keys: intent, capability, args, confidence, isMultiStep, "
        "requiresConfirmation, privacyClass, planPreview.\n"
        f"User request: {text}"
    )


def _invoke_provider_chat(state: dict[str, Any], provider: str, conversation: list[dict[str, Any]], text: str) -> dict[str, Any]:
    if provider == "local":
        providers = _map_from(state.get("providers"))
        local_cfg = _map_from(providers.get("local"))
        runtime_family = str(local_cfg.get("runtimeFamily", "") or providers.get("defaultLocalRuntime", "") or "ollama").strip().lower()
        target = runtime_family if runtime_family in {"ollama", "lmstudio", "llamacpp"} else "ollama"
        return _invoke_provider_chat(state, target, conversation, text)
    if provider in {"openai", "anthropic", "gemini", "groq", "custom"} and litellm_adapter.available():
        routed = _chat_with_litellm(state, provider, conversation, text)
        if routed.get("ok"):
            return routed
    if provider == "ollama":
        return _chat_with_ollama(state, conversation, text)
    if provider in {"openai", "groq", "custom", "lmstudio", "llamacpp"}:
        return _chat_with_openai_compatible(state, provider, conversation, text)
    if provider == "anthropic":
        return _chat_with_anthropic(state, conversation, text)
    return _chat_with_google_live(state, conversation, text)


def _semantic_route(
    state: dict[str, Any],
    conversation: list[dict[str, Any]],
    text: str,
    *,
    conversation_id: str = "",
) -> dict[str, Any] | None:
    privacy_class = "local_private" if any(
        token in _normalise_text(text)
        for token in (
            "dosya",
            "belge",
            "pdf",
            "docx",
            "xlsx",
            "pptx",
            "gorsel",
            "görsel",
            "resim",
            "ses kaydi",
            "ses kaydı",
            "audio",
            "excel",
            "sunum",
            "ekran",
            "takvim",
            "hatirlatici",
            "uygulama",
            "terminal",
            "komut",
            "sistem",
        )
    ) else "public_text"
    retrieval = (
        _retrieve_planning_context(state, text, conversation_id)
        if _should_retrieve_context(text, privacy_class)
        else None
    )
    mcp_context = mcp_runtime.planner_mcp_context(state)
    for provider in _semantic_candidate_providers(state, privacy_class=privacy_class):
        filtered_retrieval = _filter_retrieval_matches(
            retrieval,
            allowed_sources=_retrieval_sources_for_provider(provider),
        )
        prompt = _semantic_understanding_prompt(
            text,
            state,
            retrieval_context=_format_retrieval_context(filtered_retrieval),
            mcp_context=mcp_context,
        )
        seeded_conversation = [{"role": "system", "text": prompt}]
        result = _invoke_provider_chat(state, provider, seeded_conversation, text)
        if not result.get("ok"):
            continue
        payload = _extract_json_object(str(result.get("content", "") or ""))
        if not isinstance(payload, dict):
            continue
        capability = str(payload.get("capability", "") or "").strip()
        intent = str(payload.get("intent", "") or "").strip() or "chat"
        args = payload.get("args", {})
        args = dict(args) if isinstance(args, dict) else {}
        confidence = _intent_confidence(payload.get("confidence"), 0.0)
        if capability and capability not in capability_names():
            continue
        if capability == "browser_control":
            action = str(args.get("action", "") or "").strip()
            if action not in {"search", "open_url", "play_youtube"}:
                continue
        if capability == "image_read":
            mode = str(args.get("mode", "") or "summary").strip().lower() or "summary"
            if mode not in {"summary", "metadata", "palette"}:
                continue
            args["mode"] = mode
        if capability == "data_analyze":
            mode = str(args.get("mode", "") or "summary").strip().lower() or "summary"
            if mode not in {"summary", "profile", "preview"}:
                continue
            args["mode"] = mode
        if capability == "chart_generate":
            chart_type = str(args.get("chartType", "") or args.get("chart_type", "") or "bar").strip().lower() or "bar"
            if chart_type not in {"bar", "line", "scatter", "histogram"}:
                continue
            args["chartType"] = chart_type
        if capability == "latex_parse":
            mode = str(args.get("mode", "") or "parse").strip().lower() or "parse"
            if mode not in {"parse", "normalize"}:
                continue
            args["mode"] = mode
        if capability == "mcp_call_tool":
            server_id = str(args.get("serverId", "") or args.get("server_id", "") or "").strip()
            tool_name = str(args.get("toolName", "") or args.get("tool_name", "") or "").strip()
            tool_args = args.get("arguments", {})
            tool_args = dict(tool_args) if isinstance(tool_args, dict) else {}
            if not server_id or not tool_name:
                continue
            metadata = mcp_runtime.mcp_tool_metadata(server_id, tool_name, state)
            if metadata is None:
                continue
            args = {
                "serverId": server_id,
                "toolName": tool_name,
                "arguments": tool_args,
                "_readOnlyHint": bool(metadata.get("readOnly", False)),
            }
            if not bool(metadata.get("readOnly", False)):
                payload["requiresConfirmation"] = True
            privacy_class = "local_private"
        if capability == "run_skill":
            skill_id = str(args.get("skillId", "") or args.get("skill_id", "") or "").strip()
            skill_payload = args.get("payload", {})
            skill_payload = dict(skill_payload) if isinstance(skill_payload, dict) else {}
            if not skill_id:
                continue
            try:
                prepared = skill_runtime.prepare_skill_run(skill_id, skill_payload, state)
            except SafeCapabilityError:
                continue
            args = {
                "skillId": skill_id,
                "payload": skill_payload,
            }
            if bool(prepared.get("requiresConfirmation", False)):
                payload["requiresConfirmation"] = True
            payload["planPreview"] = prepared.get("planPreview")
            privacy_class = "local_private"
        if capability in LOCAL_PRIVATE_CAPABILITIES:
            privacy_class = "local_private"
        return {
            "intent": intent,
            "capability": capability,
            "args": args,
            "confidence": confidence,
            "requiresConfirmation": bool(payload.get("requiresConfirmation", False)),
            "isMultiStep": bool(payload.get("isMultiStep", False)),
            "privacyClass": str(payload.get("privacyClass", privacy_class) or privacy_class),
            "planPreview": payload.get("planPreview") if isinstance(payload.get("planPreview"), dict) else None,
            "provider": provider,
            "model": str(result.get("model", "") or ""),
            "retrieval": filtered_retrieval,
        }
    return None


def _normalise_text(value: str) -> str:
    return " ".join(
        str(value or "")
        .strip()
        .lower()
        .replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
        .split()
    )


def _plan_steps_from_routed_task(routed: RoutedTask) -> list[dict[str, Any]]:
    if routed.steps:
        steps: list[dict[str, Any]] = []
        for step in routed.steps:
            if isinstance(step, dict):
                payload = dict(step)
                if "capability" not in payload and routed.tool_name:
                    payload["capability"] = routed.tool_name
                steps.append(payload)
        if steps:
            return steps
    return [{
        "capability": routed.tool_name,
        "args": dict(routed.args),
        "description": routed.plan_preview.get("summary") if isinstance(routed.plan_preview, dict) else routed.reason,
    }]


def _contextual_route(
    conversation_id: str,
    conversation: list[dict[str, Any]],
    text: str,
) -> RoutedTask | None:
    normalized = _normalise_text(text)
    if not normalized:
        return None
    learned_match = STATE.recent_route_match(text)
    if isinstance(learned_match, dict):
        learned_capability = str(learned_match.get("capability", "") or "").strip()
        learned_args = learned_match.get("args", {})
        learned_args = dict(learned_args) if isinstance(learned_args, dict) else {}
        if learned_capability and learned_args:
            return RoutedTask(
                learned_capability,
                learned_args,
                "learned_route_match",
                intent=str(learned_match.get("intent", "") or learned_capability),
                confidence=max(0.76, _intent_confidence(learned_match.get("confidence"), 0.76)),
                requires_confirmation=learned_capability in SIDE_EFFECT_CAPABILITIES,
                privacy_class="local_private" if learned_capability in LOCAL_PRIVATE_CAPABILITIES else "public_text",
            )
    last_route = STATE.latest_recent_route(conversation_id) or STATE.latest_recent_route()
    if not isinstance(last_route, dict):
        return None
    capability = str(last_route.get("capability", "") or "").strip()
    args = last_route.get("args", {})
    args = dict(args) if isinstance(args, dict) else {}

    if capability == "open_app" and _looks_like_app_followup(text) and any(
        token in normalized for token in ("kapat", "close")
    ):
        app_name = str(args.get("app_name", "") or "").strip()
        if app_name:
            return RoutedTask(
                "close_app",
                {"app_name": app_name},
                "context_followup_close_app",
                intent="close_app",
                confidence=0.86,
                privacy_class="local_private",
            )

    if capability in {"document_read", "ocr_read"} and _looks_like_document_followup(text):
        path = str(args.get("path", "") or "").strip()
        if path:
            mode = "summary"
            if any(token in normalized for token in ("madde", "listele", "bullet")):
                mode = "bullets"
            elif any(token in normalized for token in ("oku", "read")):
                mode = "read"
            return RoutedTask(
                capability,
                _with_selected_paths({"path": path, "mode": mode}, args),
                "context_followup_document",
                intent=capability,
                confidence=0.83,
                privacy_class="local_private",
            )
    if capability == "image_read" and _looks_like_image_followup(text):
        path = str(args.get("path", "") or "").strip()
        if path:
            mode = "summary"
            if any(token in normalized for token in ("palette", "palet", "renk")):
                mode = "palette"
            elif any(
                token in normalized
                for token in ("metadata", "meta", "boyut", "cozunurluk", "çözünürlük")
            ):
                mode = "metadata"
            return RoutedTask(
                "image_read",
                _with_selected_paths({"path": path, "mode": mode}, args),
                "context_followup_image",
                intent="image_read",
                confidence=0.82,
                privacy_class="local_private",
            )
    if capability == "speech_to_text" and _looks_like_audio_followup(text):
        audio_path = str(args.get("audioPath", "") or args.get("path", "") or "").strip()
        if audio_path:
            return RoutedTask(
                "speech_to_text",
                _with_selected_paths(
                    {
                        "audioPath": audio_path,
                        "languageHint": str(args.get("languageHint", "") or "tr"),
                    },
                    args,
                ),
                "context_followup_audio",
                intent="speech_to_text",
                confidence=0.82,
                privacy_class="local_private",
            )
    if capability in {"data_analyze", "chart_generate"} and _looks_like_data_followup(text):
        path = str(args.get("path", "") or "").strip()
        if path:
            return RoutedTask(
                "data_analyze",
                _with_selected_paths(
                    {
                        "path": path,
                        "mode": _data_followup_mode(text),
                    },
                    args,
                ),
                "context_followup_data",
                intent="data_analyze",
                confidence=0.83,
                privacy_class="local_private",
            )
    if capability in {"data_analyze", "chart_generate"} and _looks_like_chart_followup(text):
        path = str(args.get("path", "") or "").strip()
        if path:
            return RoutedTask(
                "chart_generate",
                _with_selected_paths(
                    {
                        "path": path,
                        "chartType": _chart_followup_type(text),
                        "title": Path(path).stem,
                    },
                    args,
                ),
                "context_followup_chart",
                intent="chart_generate",
                confidence=0.82,
                privacy_class="local_private",
            )
    if capability in {"document_read", "ocr_read"}:
        path = str(args.get("path", "") or "").strip()
        if path and any(token in normalized for token in ("docx", "word")) and any(
            token in normalized for token in ("yap", "cevir", "çevir", "olustur", "oluştur")
        ):
            target_path = str((Path.cwd() / "elyan_output" / f"{Path(path).stem or 'elyan-document'}.docx").resolve())
            return RoutedTask(
                "document_write",
                {
                    "prompt": text,
                    "sourcePath": path,
                    "outputPath": target_path,
                    "overwrite": False,
                },
                "context_followup_document_write",
                intent="document_write",
                confidence=0.84,
                requires_confirmation=True,
                privacy_class="local_private",
                plan_preview={
                    "summary": f"{Path(path).name} içeriğini {Path(target_path).name} DOCX dosyasına dönüştüreceğim.",
                    "steps": [
                        {
                            "capability": "document_write",
                            "args": {
                                "prompt": text,
                                "sourcePath": path,
                                "outputPath": target_path,
                                "overwrite": False,
                            },
                            "description": f"{Path(path).name} içeriği {Path(target_path).name} DOCX dosyasına dönüştürülecek.",
                        }
                    ],
                    "privacyClass": "local_private",
                },
                steps=(
                    {
                        "capability": "document_write",
                        "args": {
                            "prompt": text,
                            "sourcePath": path,
                            "outputPath": target_path,
                            "overwrite": False,
                        },
                        "description": f"{Path(path).name} içeriği {Path(target_path).name} DOCX dosyasına dönüştürülecek.",
                    },
                ),
            )
        if path and any(token in normalized for token in ("xlsx", "excel", "tablo")) and any(
            token in normalized for token in ("yap", "cevir", "çevir", "olustur", "oluştur")
        ):
            target_path = str((Path.cwd() / "elyan_output" / f"{Path(path).stem or 'elyan-sheet'}.xlsx").resolve())
            step = {
                "capability": "spreadsheet_write",
                "args": {
                    "prompt": text,
                    "sourceContext": f"{Path(path).name} içeriğinden tablo üret",
                    "outputPath": target_path,
                    "overwrite": False,
                },
                "description": f"{Path(target_path).name} XLSX çalışma sayfası oluşturulacak.",
            }
            return RoutedTask(
                "spreadsheet_write",
                {
                    "prompt": text,
                    "sourceContext": f"{Path(path).name} içeriğinden tablo üret",
                    "outputPath": target_path,
                    "overwrite": False,
                },
                "context_followup_spreadsheet_write",
                intent="spreadsheet_write",
                confidence=0.82,
                requires_confirmation=True,
                privacy_class="local_private",
                plan_preview={
                    "summary": f"{Path(path).name} bağlamından {Path(target_path).name} XLSX dosyasını oluşturacağım.",
                    "steps": [step],
                    "privacyClass": "local_private",
                },
                steps=(step,),
            )
        if path and any(token in normalized for token in ("pptx", "sunum", "slide", "powerpoint")) and any(
            token in normalized for token in ("yap", "cevir", "çevir", "olustur", "oluştur")
        ):
            target_path = str((Path.cwd() / "elyan_output" / f"{Path(path).stem or 'elyan-presentation'}.pptx").resolve())
            step = {
                "capability": "presentation_write",
                "args": {
                    "prompt": text,
                    "sourceContext": f"{Path(path).name} içeriğinden sunum üret",
                    "outputPath": target_path,
                    "overwrite": False,
                },
                "description": f"{Path(target_path).name} PPTX sunumu oluşturulacak.",
            }
            return RoutedTask(
                "presentation_write",
                {
                    "prompt": text,
                    "sourceContext": f"{Path(path).name} içeriğinden sunum üret",
                    "outputPath": target_path,
                    "overwrite": False,
                },
                "context_followup_presentation_write",
                intent="presentation_write",
                confidence=0.82,
                requires_confirmation=True,
                privacy_class="local_private",
                plan_preview={
                    "summary": f"{Path(path).name} bağlamından {Path(target_path).name} PPTX sunumunu oluşturacağım.",
                    "steps": [step],
                    "privacyClass": "local_private",
                },
                steps=(step,),
            )
    return None


def _record_successful_route(
    query: str,
    intent: str,
    capability: str,
    confidence: float,
    *,
    args: dict[str, Any] | None = None,
    conversation_id: str = "",
    confirmed: bool = False,
) -> None:
    try:
        STATE.record_recent_route(
            query=query,
            intent=intent,
            capability=capability,
            confidence=confidence,
            args=args,
            conversation_id=conversation_id,
            confirmed=confirmed,
        )
    except Exception:
        return


def _default_plan_preview(intent: str, capability: str, args: dict[str, Any], steps: list[dict[str, Any]], privacy_class: str) -> dict[str, Any]:
    title = capability or intent or "task"
    description = f"{title} çalıştırılacak."
    if capability == "add_calendar_event":
        description = f"Takvime '{str(args.get('title', '') or 'yeni etkinlik')}' eklenecek."
    elif capability == "add_reminder":
        description = f"'{str(args.get('title', '') or 'hatırlatıcı')}' için hatırlatıcı oluşturulacak."
    elif capability == "open_app":
        description = f"{str(args.get('app_name', '') or 'uygulama')} açılacak."
    elif capability == "browser_control":
        action = str(args.get("action", "") or "")
        if action == "open_url":
            description = f"{str(args.get('url', '') or 'web adresi')} açılacak."
        elif action == "search":
            description = f"Web'de '{str(args.get('query', '') or '')}' aranacak."
        elif action == "play_youtube":
            description = f"YouTube'da '{str(args.get('query', '') or '')}' açılacak."
    elif capability == "send_whatsapp_message":
        recipient = str(args.get("recipient_name", "") or "").strip()
        phone = str(args.get("phone_number", "") or "").strip()
        target = recipient or phone or "hedef kişi"
        description = f"WhatsApp için {target} hedefine mesaj taslağı hazırlanacak."
        if bool(args.get("send_now", False)):
            description = f"WhatsApp ile {target} hedefine mesaj gönderilecek."
    elif capability == "save_whatsapp_contact":
        target = str(args.get("display_name", "") or "").strip() or "kişi"
        description = f"{target} WhatsApp kişilerine kaydedilecek."
    elif capability == "shell_run":
        description = f"`{str(args.get('command', '') or 'komut')}` komutu çalıştırılacak."
    elif capability == "document_write":
        output_path = str(args.get("outputPath", "") or args.get("output_path", "") or "")
        description = f"{Path(output_path).name or 'elyan.docx'} DOCX dosyası oluşturulacak."
    elif capability == "spreadsheet_write":
        output_path = str(args.get("outputPath", "") or args.get("output_path", "") or "")
        description = f"{Path(output_path).name or 'elyan.xlsx'} XLSX çalışma sayfası oluşturulacak."
    elif capability == "presentation_write":
        output_path = str(args.get("outputPath", "") or args.get("output_path", "") or "")
        description = f"{Path(output_path).name or 'elyan.pptx'} PPTX sunumu oluşturulacak."
    elif capability == "image_generate":
        output_path = str(args.get("outputPath", "") or args.get("output_path", "") or "")
        description = f"{Path(output_path).name or 'elyan-output.png'} görseli üretilecek."
    elif capability == "mcp_call_tool":
        server_id = str(args.get("serverId", "") or args.get("server_id", "") or "").strip()
        tool_name = str(args.get("toolName", "") or args.get("tool_name", "") or "").strip()
        description = f"MCP aracı {tool_name or 'tool'} çalıştırılacak."
        if server_id:
            description = f"{server_id} üzerinde MCP aracı {tool_name or 'tool'} çalıştırılacak."
    return {
        "summary": description,
        "steps": steps,
        "privacyClass": privacy_class,
    }


def _backend_status(backend: BackendClient) -> dict[str, Any]:
    me = backend.auth_me()
    mobile = backend.mobile_bootstrap()
    realtime = backend.realtime_runtime()
    health = backend.health()
    return {
        "configured": backend.configured,
        "loopback": backend.loopback,
        "authMe": me.to_dict(),
        "mobileBootstrap": mobile.to_dict(),
        "realtimeRuntime": realtime.to_dict(),
        "health": health.to_dict(),
    }


def _ollama_status(state: dict[str, Any]) -> dict[str, Any]:
    providers = state.get("providers", {})
    model = ""
    if isinstance(providers, dict):
        model = str(providers.get("ollama", {}).get("defaultModel", "") or "")
    return _ollama_status_payload(
        base_url=str(providers.get("ollama", {}).get("baseUrl", "") or "") if isinstance(providers, dict) else None,
        default_model=model,
    )


def _permission_error(code: str, message: str) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
    }


def _tool_requires_confirmation(tool_name: str) -> bool:
    return tool_name in {"delete_memory", "delete_calendar_event", "shell_run", "email_send", *PERSONAL_ACTION_CAPABILITIES}


def _tool_permission_allowed(state: dict[str, Any], tool_name: str, args: dict[str, Any] | None = None) -> bool:
    permissions = state.get("permissions", {})
    if not isinstance(permissions, dict):
        return False
    payload = dict(args) if isinstance(args, dict) else {}
    if tool_name == "shell_run":
        return _is_truthy(permissions.get("allow_shell", False))
    if tool_name in PERSONAL_ACTION_CAPABILITIES:
        if not _is_truthy(permissions.get("allow_personal_actions", False)):
            return False
        if tool_name == "send_whatsapp_message" and _is_truthy(payload.get("send_now", False)):
            return _is_truthy(permissions.get("allow_destructive_tools", False))
        return True
    if _tool_requires_confirmation(tool_name):
        return _is_truthy(permissions.get("allow_destructive_tools", False))
    return True


def _run_tool(tool_name: str, args: dict[str, Any], state: dict[str, Any]) -> str:
    return run_capability_text(tool_name, args, state)


def _data_followup_mode(text: str) -> str:
    normalized = _normalise_text(text)
    if any(token in normalized for token in ("preview", "onizleme", "önizleme", "ilk satir", "ilk satır")):
        return "preview"
    if any(token in normalized for token in ("profil", "profile", "istatistik")):
        return "profile"
    return "summary"


def _chart_followup_type(text: str) -> str:
    normalized = _normalise_text(text)
    if any(token in normalized for token in ("histogram", "dagilim", "dağılım")):
        return "histogram"
    if "scatter" in normalized:
        return "scatter"
    if any(token in normalized for token in ("line", "cizgi", "çizgi")):
        return "line"
    return "bar"


def _execute_capability_with_preprocessing(
    capability: str,
    args: dict[str, Any],
    state: dict[str, Any],
    *,
    source: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = dict(args)
    readiness = capability_readiness(capability, state=state)
    if readiness.get("ready") is False:
        error_code = str(readiness.get("errorCode", "") or "CAPABILITY_UNAVAILABLE")
        if error_code == "UNSUPPORTED_PLATFORM":
            message = "Bu özellik bu işletim sisteminde desteklenmiyor."
            if capability in {"open_app", "close_app"}:
                message = "Bu özellik yalnizca macOS'ta kullanılabilir."
        elif error_code == "DEPENDENCY_UNAVAILABLE":
            message = "Bu özellik bu kurulumda hazır değil."
        else:
            message = "Bu özellik güvenli şekilde başlatılamadı."
        failed = {
            "ok": False,
            "tool": capability,
            "output": message,
            "error": {"code": error_code, "message": message},
        }
        return failed, [safe_tool_event(capability, failed, source=source)]
    if capability == "run_skill":
        skill_id = str(payload.get("skillId", "") or payload.get("skill_id", "") or "").strip()
        skill_payload = payload.get("payload", {})
        skill_payload = dict(skill_payload) if isinstance(skill_payload, dict) else {}
        confirmed = bool(payload.get("_confirmed", False))
        try:
            prepared = skill_runtime.prepare_skill_run(skill_id, skill_payload, state)
        except SafeCapabilityError as exc:
            failed = {
                "ok": False,
                "tool": "run_skill",
                "output": exc.message,
                "error": {"code": exc.code, "message": exc.message},
            }
            return failed, [safe_tool_event("run_skill", failed, source=source)]
        if prepared.get("requiresConfirmation") and not confirmed:
            denied = {
                "ok": False,
                "tool": "run_skill",
                "output": "Bu skill icin acik onay gerekiyor.",
                "error": {
                    "code": "PERMISSION_REQUIRED",
                    "message": "Bu skill icin acik onay gerekiyor.",
                },
            }
            return denied, [safe_tool_event("run_skill", denied, source=source)]
        events: list[dict[str, Any]] = []
        outputs: list[str] = []
        structured_result: dict[str, Any] | None = None
        artifacts: list[dict[str, Any]] = []
        previous_output = ""
        previous_result: dict[str, Any] | None = None
        previous_artifacts: list[dict[str, Any]] = []
        for step in prepared.get("steps", []):
            if not isinstance(step, dict):
                continue
            step_args = dict(step.get("args", {}) or {})
            if confirmed:
                step_args["_confirmed"] = True
            if previous_output:
                step_args["_previousOutput"] = previous_output
            if previous_result:
                step_args["_previousResult"] = previous_result
            if previous_artifacts:
                step_args["_previousArtifacts"] = list(previous_artifacts)
            for target_key in step.get("argsFromPreviousOutput", []) or []:
                target_name = str(target_key or "").strip()
                if target_name and previous_output:
                    step_args[target_name] = previous_output
            previous_result_map = step.get("argsFromPreviousResult", {})
            if isinstance(previous_result_map, dict) and previous_result:
                for target_key, source_key in previous_result_map.items():
                    target_name = str(target_key or "").strip()
                    source_name = str(source_key or "").strip()
                    if not target_name or not source_name:
                        continue
                    if source_name in previous_result:
                        step_args[target_name] = previous_result.get(source_name)
            tool_result, step_events = _execute_capability_with_preprocessing(
                str(step.get("capability", "") or ""),
                step_args,
                state,
                source=source,
            )
            events.extend(step_events)
            if not tool_result.get("ok"):
                return tool_result, events
            output = str(tool_result.get("output", "") or "").strip()
            if output:
                outputs.append(output)
                previous_output = output
            result_payload = tool_result.get("result")
            if isinstance(result_payload, dict):
                structured_result = dict(result_payload)
                previous_result = dict(result_payload)
            step_artifacts = tool_result.get("artifacts", [])
            if isinstance(step_artifacts, list):
                cleaned_artifacts = [item for item in step_artifacts if isinstance(item, dict)]
                artifacts.extend(cleaned_artifacts)
                previous_artifacts = cleaned_artifacts
        skill_result = {
            "ok": True,
            "tool": "run_skill",
            "output": "\n".join(item for item in outputs if item).strip() or "Skill tamamlandi.",
            "result": {
                "kind": "run_skill",
                "skillId": skill_id,
                "skill": prepared.get("skill"),
                "lastStepResult": structured_result,
            },
            "artifacts": artifacts,
            "error": None,
        }
        return skill_result, [safe_tool_event("run_skill", skill_result, source=source), *events]
    latex_input = str(payload.get("_latexInput", "") or "").strip()
    if capability == "math_solve" and latex_input:
        parse_result = run_capability(
            "latex_parse",
            {"expression": latex_input, "mode": "normalize"},
            state,
        )
        events = [safe_tool_event("latex_parse", parse_result, source=source)]
        if not parse_result.get("ok"):
            return parse_result, events
        parse_payload = parse_result.get("result") if isinstance(parse_result.get("result"), dict) else {}
        normalized_expression = str(parse_payload.get("normalizedExpression", "") or "").strip()
        if not normalized_expression:
            failure = {
                "ok": False,
                "tool": "latex_parse",
                "output": "LaTeX ifadesi çözümlenemedi.",
                "error": {
                    "code": "INVALID_ARGUMENT",
                    "message": "LaTeX ifadesi çözümlenemedi.",
                },
            }
            events[0] = safe_tool_event("latex_parse", failure, source=source)
            return failure, events
        payload["expression"] = normalized_expression
        payload.pop("_latexInput", None)
        tool_result = run_capability(capability, payload, state)
        events.append(safe_tool_event(capability, tool_result, source=source))
        if tool_result.get("ok") and isinstance(tool_result.get("result"), dict):
            enriched = dict(tool_result["result"])
            enriched["latexParse"] = parse_payload
            tool_result = {**tool_result, "result": enriched}
        return tool_result, events

    tool_result = run_capability(capability, payload, state)
    return tool_result, [safe_tool_event(capability, tool_result, source=source)]


def _chat_with_ollama(state: dict[str, Any], conversation: list[dict[str, Any]], text: str) -> dict[str, Any]:
    providers = state.get("providers", {})
    ollama_cfg = providers.get("ollama", {}) if isinstance(providers, dict) else {}
    model = str(ollama_cfg.get("defaultModel", "") or providers.get("local", {}).get("defaultModel", "") or "")
    if not model:
        return {"ok": False, "error": "ollama_model_missing"}
    client = _make_ollama_client(
        base_url=str(ollama_cfg.get("baseUrl", "") or "http://127.0.0.1:11434"),
        default_model=model,
    )
    if client is None:
        return {"ok": False, "error": "ollama_client_unavailable"}
    messages = _chat_messages(conversation, text, allow_system=True)
    result = client.chat(model, messages)
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error", "ollama_chat_failed")}
    return {
        "ok": True,
        "content": str(result.get("content", "") or "").strip(),
        "provider": "ollama",
        "model": model,
        "router": "native",
    }


def _chat_with_litellm(state: dict[str, Any], provider: str, conversation: list[dict[str, Any]], text: str) -> dict[str, Any]:
    cfg = _provider_config(state, provider)
    model = _model_for_provider(state, provider)
    api_key = str(cfg.get("apiKey", "") or "").strip()
    base_url = str(cfg.get("baseUrl", "") or "").strip().rstrip("/")
    if not model:
        return {"ok": False, "error": f"{provider}_config_missing"}
    if provider in {"openai", "anthropic", "gemini", "groq"} and not api_key:
        return {"ok": False, "error": f"{provider}_config_missing"}
    if provider == "custom" and (not api_key or not base_url):
        return {"ok": False, "error": "custom_config_missing"}
    return litellm_adapter.chat_completion(
        provider=provider,
        model=model,
        messages=_chat_messages(conversation, text, allow_system=True),
        api_key=api_key,
        base_url=base_url,
        temperature=0.2,
        timeout=60,
    )


def _chat_with_openai_compatible(state: dict[str, Any], provider: str, conversation: list[dict[str, Any]], text: str) -> dict[str, Any]:
    cfg = _provider_config(state, provider)
    api_key = str(cfg.get("apiKey", "") or "").strip()
    base_url = str(cfg.get("baseUrl", "") or "").strip().rstrip("/")
    model = _model_for_provider(state, provider)
    requires_auth = provider in {"openai", "groq", "custom"}
    if ((requires_auth and not api_key) or not base_url or not model):
        return {"ok": False, "error": f"{provider}_config_missing"}
    url = f"{base_url}/chat/completions" if base_url.endswith("/v1") else f"{base_url}/v1/chat/completions"
    messages = _chat_messages(conversation, text, allow_system=True)
    headers = {
        "Content-Type": "application/json",
    }
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        response = requests.post(
            url,
            headers=headers,
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.2,
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        if provider in {"lmstudio", "llamacpp"}:
            return {"ok": False, "error": "request_timeout" if isinstance(exc, requests.Timeout) else "provider_unreachable"}
        return {"ok": False, "error": str(exc)}
    if not response.ok:
        return {"ok": False, "error": "provider_unreachable" if provider in {"lmstudio", "llamacpp"} else response.text[:500]}
    try:
        payload = response.json() if response.text else {}
    except ValueError:
        return {"ok": False, "error": "invalid_response" if provider in {"lmstudio", "llamacpp"} else "openai_compatible_invalid_response"}
    choices = payload.get("choices", []) if isinstance(payload, dict) else []
    content = ""
    if choices and isinstance(choices[0], dict):
        message = choices[0].get("message", {})
        if isinstance(message, dict):
            content = str(message.get("content", "") or "").strip()
    return {"ok": True, "content": content, "provider": provider, "model": model, "router": "native"}


def _chat_with_anthropic(state: dict[str, Any], conversation: list[dict[str, Any]], text: str) -> dict[str, Any]:
    cfg = _provider_config(state, "anthropic")
    api_key = str(cfg.get("apiKey", "") or "").strip()
    base_url = str(cfg.get("baseUrl", "") or "https://api.anthropic.com").strip().rstrip("/")
    model = _model_for_provider(state, "anthropic")
    if not api_key or not model:
        return {"ok": False, "error": "anthropic_config_missing"}
    messages = _chat_messages(conversation, text, allow_system=False)
    system = _build_system_instruction()
    conversation_system = _conversation_system_context(conversation)
    if conversation_system:
        system = f"{system}\n\n{conversation_system}"
    try:
        response = requests.post(
            f"{base_url}/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 1024,
                "system": system,
                "messages": messages,
            },
            timeout=60,
        )
    except requests.RequestException as exc:
        return {"ok": False, "error": str(exc)}
    if not response.ok:
        return {"ok": False, "error": response.text[:500]}
    payload = response.json() if response.text else {}
    content = ""
    if isinstance(payload, dict):
        content_items = payload.get("content", [])
        if content_items and isinstance(content_items, list):
            first = content_items[0]
            if isinstance(first, dict):
                content = str(first.get("text", "") or "").strip()
    return {"ok": True, "content": content, "provider": "anthropic", "model": model, "router": "native"}


def _chat_with_google_live(state: dict[str, Any], conversation: list[dict[str, Any]], text: str) -> dict[str, Any]:
    google_genai, google_types = _google_live_sdk()
    if google_genai is None or google_types is None:
        return {"ok": False, "error": "google_genai_missing"}
    cfg = _provider_config(state, "gemini")
    api_key = str(
        cfg.get("apiKey", "")
        or get_app_config_value("gemini_api_key", "")
        or os.environ.get("ELYAN_GOOGLE_API_KEY", "")
        or ""
    ).strip()
    if not api_key:
        return {"ok": False, "error": "google_api_key_missing"}
    client = google_genai.Client(api_key=api_key, http_options={"api_version": "v1alpha"})
    model = str(_model_for_provider(state, "gemini") or os.environ.get("ELYAN_GOOGLE_MODEL", "") or get_app_config_value("gemini_model", GOOGLE_LIVE_MODEL_DEFAULT) or GOOGLE_LIVE_MODEL_DEFAULT).strip()

    async def _run() -> dict[str, Any]:
        config = google_types.LiveConnectConfig(
            response_modalities=["TEXT"],
            system_instruction=_build_system_instruction(),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
        )
        collected: list[str] = []
        tool_events: list[dict[str, Any]] = []
        async with client.aio.live.connect(model=model, config=config) as session:
            turns = [
                google_types.Content(role=msg["role"], parts=[google_types.Part(text=msg["text"])])
                for msg in conversation
                if msg["role"] in {"user", "assistant"}
            ]
            await session.send_client_content(
                turns=turns + [google_types.Content(role="user", parts=[google_types.Part(text=text)])],
                turn_complete=True,
            )
            async for response in session.receive():
                if response.server_content and response.server_content.model_turn:
                    for part in response.server_content.model_turn.parts or []:
                        if getattr(part, "text", None):
                            collected.append(str(part.text))
                if response.tool_call:
                    fn_responses = []
                    for fc in response.tool_call.function_calls:
                        tool_name = str(fc.name)
                        args = dict(fc.args or {})
                        try:
                            tool_output = await asyncio.wait_for(
                                asyncio.to_thread(_run_tool, tool_name, args, state),
                                timeout=120,
                            )
                        except asyncio.TimeoutError:
                            tool_output = f"araç zaman aşımı: {tool_name}"
                        tool_events.append({"tool": tool_name, "args": args, "output": tool_output})
                        fn_responses.append(
                            google_types.FunctionResponse(
                                id=fc.id,
                                name=tool_name,
                                response={"result": tool_output},
                            )
                        )
                    await session.send_tool_response(function_responses=fn_responses)
                if response.server_content and response.server_content.turn_complete:
                    break
        return {
            "ok": True,
            "content": "".join(collected).strip(),
            "provider": "gemini",
            "model": model,
            "router": "google_live",
            "toolEvents": tool_events,
        }

    try:
        return asyncio.run(_run())
    except Exception:
        return {"ok": False, "error": "google_live_failed"}


def _chat_provider_candidates(state: dict[str, Any], *, privacy_class: str) -> list[str]:
    active = _current_provider(state)
    policy = _routing_policy(state)
    fallback_to_cloud = _is_truthy(state.get("providers", {}).get("fallbackToCloud", True))

    def append_unique(items: list[str], value: str) -> None:
        if value and value not in items:
            items.append(value)

    configured_cloud = [
        provider
        for provider in ("openai", "gemini", "anthropic", "groq", "custom")
        if _provider_enabled(state, provider) and _provider_is_configured_for_chat(state, provider)
    ]

    if policy == "provider_lock":
        if active == "local":
            local_cfg = _map_from(_map_from(state.get("providers")).get("local"))
            runtime_family = str(local_cfg.get("runtimeFamily", "") or _map_from(state.get("providers")).get("defaultLocalRuntime", "") or "ollama").strip().lower()
            locked = runtime_family if runtime_family in {"ollama", "lmstudio", "llamacpp"} else "ollama"
        else:
            locked = active
        return [locked] if _provider_is_configured_for_chat(state, locked) else []

    ordered: list[str] = []
    if policy == "cloud_fallback":
        if active not in {"local", "ollama", "lmstudio", "llamacpp"} and _provider_is_configured_for_chat(state, active):
            append_unique(ordered, active)
        for provider in configured_cloud:
            append_unique(ordered, provider)
        for provider in ("ollama", "lmstudio", "llamacpp"):
            if _provider_enabled(state, provider) and _provider_is_configured_for_chat(state, provider):
                append_unique(ordered, provider)
        return ordered

    for provider in ("ollama", "lmstudio", "llamacpp"):
        if _provider_enabled(state, provider) and _provider_is_configured_for_chat(state, provider):
            append_unique(ordered, provider)
    if fallback_to_cloud and privacy_class == "public_text":
        if active not in {"local", "ollama", "lmstudio", "llamacpp"} and _provider_is_configured_for_chat(state, active):
            append_unique(ordered, active)
        for provider in configured_cloud:
            append_unique(ordered, provider)
    return ordered


def _route_chat(
    state: dict[str, Any],
    conversation: list[dict[str, Any]],
    text: str,
    *,
    conversation_id: str = "",
    selected_artifacts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    routed = route_text_to_tool(text, selected_artifacts=selected_artifacts)
    contextual = _contextual_route(conversation_id, conversation, text)
    if contextual is not None and (
        routed is None
        or (routed.tool_name in {"open_app", "close_app"} and not str(routed.args.get("app_name", "") or "").strip())
    ):
        routed = contextual
    clarification = artifact_target_clarification(text, selected_artifacts)
    if clarification is not None and routed is None and contextual is None:
        try:
            STATE.increment_clarification_count()
        except Exception:
            pass
        _record_task_intelligence_outcome(
            "clarified",
            query=text,
            intent=str(clarification.get("kind", "") or "clarification"),
            capability="",
            conversation_id=conversation_id,
            question=str(clarification.get("question", "") or ""),
        )
        return _clarification_response(
            str(clarification.get("question", "") or "Hedef dosyayı netleştirmen gerekiyor."),
            intent=str(clarification.get("kind", "") or "clarification"),
            privacy_class="local_private",
        )
    if routed is not None:
        if routed.requires_confirmation or routed.is_multi_step:
            try:
                STATE.increment_clarification_count()
            except Exception:
                pass
            return {
                "ok": True,
                "content": str(
                    routed.plan_preview.get("summary")
                    if isinstance(routed.plan_preview, dict)
                    else "Bu görev için önce yürütme planı hazırlanacak."
                ),
                "provider": "local_planner",
                "toolEvents": [],
                "intent": routed.intent or routed.reason,
                "confidence": routed.confidence,
                "executionMode": "plan_preview",
                "needsConfirmation": True,
                "privacyClass": routed.privacy_class,
                "planPreview": routed.plan_preview or _default_plan_preview(
                    routed.intent or routed.reason,
                    routed.tool_name,
                    routed.args,
                    _plan_steps_from_routed_task(routed),
                    routed.privacy_class,
                ),
                "pendingPlan": {
                    "query": text,
                    "intent": routed.intent or routed.reason,
                    "capability": routed.tool_name,
                    "confidence": routed.confidence,
                    "privacyClass": routed.privacy_class,
                    "steps": _plan_steps_from_routed_task(routed),
                    "source": "deterministic_router",
                },
            }
        tool_result, events = _execute_capability_with_preprocessing(
            routed.tool_name,
            routed.args,
            state,
            source="deterministic_router",
        )
        if tool_result.get("ok"):
            _record_successful_route(
                text,
                routed.intent or routed.reason,
                routed.tool_name,
                routed.confidence,
                args=routed.args,
                conversation_id=conversation_id,
            )
            _record_task_intelligence_outcome(
                "correct",
                query=text,
                intent=routed.intent or routed.reason,
                capability=routed.tool_name,
                args=routed.args,
                conversation_id=conversation_id,
            )
            return {
                "ok": True,
                "content": str(tool_result.get("output", "") or "").strip(),
                "provider": "local_tool",
                "toolEvents": events,
                "structuredResult": tool_result.get("result"),
                "artifacts": tool_result.get("artifacts", []),
                "intent": routed.intent or routed.reason,
                "confidence": routed.confidence,
                "executionMode": "local_tool",
                "needsConfirmation": False,
                "privacyClass": routed.privacy_class,
                "planPreview": None,
            }
        error = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
        if str(error.get("code") or "") == "PERMISSION_REQUIRED":
            return _permission_needed_response(
                str(error.get("message") or tool_result.get("output") or "") or "Bu işlem için açık izin gerekiyor.",
                intent=routed.intent or routed.reason,
                privacy_class=routed.privacy_class,
            )
        _record_task_intelligence_outcome(
            "misrouted",
            query=text,
            intent=routed.intent or routed.reason,
            capability=routed.tool_name,
            args=routed.args,
            conversation_id=conversation_id,
        )
        return {
            "ok": False,
            "error": str(error.get("code") or "TOOL_EXECUTION_FAILED"),
            "message": str(error.get("message") or tool_result.get("output") or ""),
            "provider": "local_tool",
            "toolEvents": events,
            "intent": routed.intent or routed.reason,
            "confidence": routed.confidence,
            "executionMode": "local_tool",
            "needsConfirmation": False,
            "privacyClass": routed.privacy_class,
        }

    local_private_request = _is_local_private_chat_request(text)
    tool_capable_request = _requires_tool_capable_route(text)
    local_runtime_error = _selected_local_runtime_error(state)
    if local_runtime_error and (local_private_request or tool_capable_request):
        privacy_class = "local_private" if local_private_request else "public_text"
        return {
            "ok": False,
            "error": local_runtime_error,
            "message": _safe_chat_error_message(local_runtime_error),
            "provider": _local_runtime_family_from_state(state),
            "toolEvents": [],
            "intent": "tool_request" if tool_capable_request else "chat",
            "confidence": 0.0,
            "executionMode": "local_model_unavailable",
            "needsConfirmation": False,
            "privacyClass": privacy_class,
        }

    semantic = _semantic_route(state, conversation, text, conversation_id=conversation_id)
    if semantic and not semantic.get("capability"):
        if _requires_tool_capable_route(text):
            question = "Görevi netleştirmem gerekiyor. Hangi uygulama, dosya veya hedef üzerinde işlem yapmamı istiyorsun?"
            try:
                STATE.increment_clarification_count()
            except Exception:
                pass
            _record_task_intelligence_outcome(
                "clarified",
                query=text,
                intent=str(semantic.get("intent", "") or "clarification"),
                capability="",
                conversation_id=conversation_id,
                question=question,
            )
            return _clarification_response(question, privacy_class=str(semantic.get("privacyClass", "public_text") or "public_text"))
    if semantic and semantic.get("capability"):
        capability = str(semantic.get("capability", "") or "")
        args = semantic.get("args", {})
        args = dict(args) if isinstance(args, dict) else {}
        intent = str(semantic.get("intent", "") or capability or "task")
        confidence = _intent_confidence(semantic.get("confidence"), 0.64)
        privacy_class = str(semantic.get("privacyClass", "public_text") or "public_text")
        retrieval_metadata = _retrieval_result_metadata(
            semantic.get("retrieval") if isinstance(semantic.get("retrieval"), dict) else None
        )
        confidence_threshold = _semantic_acceptance_threshold(state) + _semantic_capability_penalty(capability)
        if confidence < confidence_threshold:
            question = "Görevi netleştirmem gerekiyor. Hangi hedef üzerinde ne yapmamı istediğini biraz daha açık yazar mısın?"
            try:
                STATE.increment_clarification_count()
            except Exception:
                pass
            _record_task_intelligence_outcome(
                "clarified",
                query=text,
                intent=intent or "clarification",
                capability=capability,
                args=args,
                conversation_id=conversation_id,
                question=question,
            )
            return {
                **_clarification_response(
                    question,
                    intent=intent or "clarification",
                    privacy_class=privacy_class,
                ),
                **retrieval_metadata,
            }
        missing_argument_question = _semantic_missing_argument_question(capability, args)
        if missing_argument_question:
            try:
                STATE.increment_clarification_count()
            except Exception:
                pass
            _record_task_intelligence_outcome(
                "clarified",
                query=text,
                intent=intent or "clarification",
                capability=capability,
                args=args,
                conversation_id=conversation_id,
                question=missing_argument_question,
            )
            return {
                **_clarification_response(
                    missing_argument_question,
                    intent=intent or "clarification",
                    privacy_class=privacy_class,
                ),
                **retrieval_metadata,
            }
        misroute_question = _semantic_misroute_question(state, text, capability)
        if misroute_question:
            try:
                STATE.increment_clarification_count()
            except Exception:
                pass
            _record_task_intelligence_outcome(
                "clarified",
                query=text,
                intent=intent or "clarification",
                capability=capability,
                args=args,
                conversation_id=conversation_id,
                question=misroute_question,
            )
            return {
                **_clarification_response(
                    misroute_question,
                    intent=intent or "clarification",
                    privacy_class=privacy_class,
                ),
                **retrieval_metadata,
            }
        steps = semantic.get("planPreview", {}).get("steps", []) if isinstance(semantic.get("planPreview"), dict) else []
        if not isinstance(steps, list) or not steps:
            steps = [{"capability": capability, "args": args, "description": capability}]
        requires_confirmation = bool(semantic.get("requiresConfirmation", False)) or bool(
            semantic.get("isMultiStep", False)
        ) or capability in SIDE_EFFECT_CAPABILITIES or _semantic_requires_plan_from_history(capability)
        if requires_confirmation:
            try:
                STATE.increment_clarification_count()
            except Exception:
                pass
            semantic_plan_preview = semantic.get("planPreview")
            if isinstance(semantic_plan_preview, dict):
                semantic_plan_preview = _plan_preview_with_retrieval(
                    semantic_plan_preview,
                    semantic.get("retrieval") if isinstance(semantic.get("retrieval"), dict) else None,
                )
            elif semantic.get("retrieval"):
                semantic_plan_preview = _plan_preview_with_retrieval(
                    _default_plan_preview(intent, capability, args, steps, privacy_class),
                    semantic.get("retrieval") if isinstance(semantic.get("retrieval"), dict) else None,
                )
            return {
                "ok": True,
                "content": str(
                    semantic_plan_preview.get("summary")
                    if isinstance(semantic_plan_preview, dict)
                    else "Bu görev için önce yürütme planı hazırlanacak."
                ),
                "provider": str(semantic.get("provider", "") or "semantic_planner"),
                "toolEvents": [],
                "intent": intent,
                "confidence": confidence,
                "executionMode": "plan_preview",
                "needsConfirmation": True,
                "privacyClass": privacy_class,
                "planPreview": semantic_plan_preview
                if isinstance(semantic_plan_preview, dict)
                else _default_plan_preview(intent, capability, args, steps, privacy_class),
                "pendingPlan": {
                    "query": text,
                    "intent": intent,
                    "capability": capability,
                    "confidence": confidence,
                    "privacyClass": privacy_class,
                    "steps": steps,
                    "source": "semantic_router",
                    "retrieval": semantic.get("retrieval") if isinstance(semantic.get("retrieval"), dict) else None,
                },
                **retrieval_metadata,
            }
        tool_result, events = _execute_capability_with_preprocessing(
            capability,
            args,
            state,
            source="semantic_router",
        )
        if tool_result.get("ok"):
            _record_successful_route(
                text,
                intent,
                capability,
                confidence,
                args=args,
                conversation_id=conversation_id,
            )
            _record_task_intelligence_outcome(
                "correct",
                query=text,
                intent=intent,
                capability=capability,
                args=args,
                conversation_id=conversation_id,
            )
            return {
                "ok": True,
                "content": str(tool_result.get("output", "") or "").strip(),
                "provider": "local_tool",
                "toolEvents": events,
                "structuredResult": tool_result.get("result"),
                "artifacts": tool_result.get("artifacts", []),
                "intent": intent,
                "confidence": confidence,
                "executionMode": "local_tool",
                "needsConfirmation": False,
                "privacyClass": privacy_class,
                "planPreview": None,
                **retrieval_metadata,
            }
        error = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
        if str(error.get("code") or "") == "PERMISSION_REQUIRED":
            return {
                **_permission_needed_response(
                    str(error.get("message") or tool_result.get("output") or "") or "Bu işlem için açık izin gerekiyor.",
                    intent=intent,
                    privacy_class=privacy_class,
                ),
                **retrieval_metadata,
            }
        _record_task_intelligence_outcome(
            "misrouted",
            query=text,
            intent=intent,
            capability=capability,
            args=args,
            conversation_id=conversation_id,
        )
        return {
            "ok": False,
            "error": str(error.get("code") or "TOOL_EXECUTION_FAILED"),
            "message": str(error.get("message") or tool_result.get("output") or ""),
            "provider": "local_tool",
            "toolEvents": events,
            "intent": intent,
            "confidence": confidence,
            "executionMode": "local_tool",
            "needsConfirmation": False,
            "privacyClass": privacy_class,
            **retrieval_metadata,
        }

    if _requires_tool_capable_route(text):
        question = "Bu görev için daha net bir ifade veya desteklenen bir yerel araç gerekiyor."
        _record_task_intelligence_outcome(
            "clarified",
            query=text,
            intent="clarification",
            capability="",
            conversation_id=conversation_id,
            question=question,
        )
        return {
            "ok": False,
            "error": "UNKNOWN_CAPABILITY",
            "message": question,
            "provider": "",
            "toolEvents": [],
            "intent": "tool_request",
            "confidence": 0.0,
            "executionMode": "unresolved",
            "needsConfirmation": False,
            "privacyClass": "local_private",
        }

    chat_privacy_class = "local_private" if local_private_request else "public_text"
    local_chat_retrieval = (
        _retrieve_local_context_result(
            state,
            text,
            sources=_default_local_retrieval_sources(),
            conversation_id=conversation_id,
            limit=6,
        )
        if _should_retrieve_context(text, chat_privacy_class)
        else None
    )
    if local_private_request:
        local_candidates = _semantic_candidate_providers(state, privacy_class="local_private")
        public_cloud_candidates = [
            provider
            for provider in ("openai", "gemini", "anthropic", "groq", "custom")
            if _provider_enabled(state, provider) and _provider_is_configured_for_chat(state, provider)
        ]
        if not local_candidates and public_cloud_candidates:
            return _permission_needed_response(
                "Bu yerel görev için açık hedef veya açık izin olmadan bulut yükseltmesi kullanamam."
            )

    for provider in _chat_provider_candidates(state, privacy_class="public_text"):
        filtered_retrieval = _filter_retrieval_matches(
            local_chat_retrieval,
            allowed_sources=_retrieval_sources_for_provider(provider),
        )
        seeded_conversation = conversation
        retrieval_context = _format_retrieval_context(filtered_retrieval)
        if retrieval_context:
            seeded_conversation = [{"role": "system", "text": retrieval_context}, *conversation]
        result = _invoke_provider_chat(state, provider, seeded_conversation, text)
        if not result.get("ok"):
            continue
        return {
            "ok": True,
            "content": str(result.get("content", "") or "").strip(),
            "provider": str(result.get("provider", provider) or provider),
            "model": str(result.get("model", "") or ""),
            "toolEvents": result.get("toolEvents", []),
            "intent": "chat",
            "confidence": 0.56 if provider == "ollama" else 0.62,
            "executionMode": "local_model" if provider == "ollama" else "cloud_model",
            "needsConfirmation": False,
            "privacyClass": "public_text",
            "planPreview": None,
            **_retrieval_result_metadata(filtered_retrieval),
        }

    if _requires_tool_capable_route(text):
        question = "Görevi netleştirmem gerekiyor. Hangi uygulama, dosya veya hedef üzerinde işlem yapmamı istiyorsun?"
        try:
            STATE.increment_clarification_count()
        except Exception:
            pass
        return _clarification_response(question, privacy_class="local_private" if local_private_request else "public_text")

    if local_runtime_error:
        return {
            "ok": False,
            "error": local_runtime_error,
            "message": _safe_chat_error_message(local_runtime_error),
            "provider": _local_runtime_family_from_state(state),
            "toolEvents": [],
            "intent": "chat",
            "confidence": 0.0,
            "executionMode": "local_model_unavailable",
            "needsConfirmation": False,
            "privacyClass": chat_privacy_class,
        }

    return {"ok": False, "error": "provider_disabled"}


@dataclass(slots=True)
class RuntimeContext:
    started_at: str
    request_count: int = 0


class RuntimeBridge:
    def __init__(self):
        self.root = BASE_DIR
        self.backend = BackendClient(
            os.environ.get("APP_BASE_URL"),
            capabilities_provider=_runtime_advertised_capabilities,
        )
        self.context = RuntimeContext(started_at=_utc_now_iso())
        self._relay_stop = threading.Event()
        self._relay_thread: threading.Thread | None = None
        self._runtime_ws_stop = threading.Event()
        self._runtime_ws_thread: threading.Thread | None = None
        self._runtime_ws_app: Any | None = None
        self._runtime_ws_lock = threading.RLock()
        self._runtime_ws_connected = False
        self._runtime_ws_last_error = ""
        self._runtime_register_retry_lock = threading.RLock()
        self._runtime_register_retry_thread: threading.Thread | None = None
        self._runtime_register_retry_target: dict[str, str] | None = None
        self._runtime_register_retry_generation = 0
        self._runtime_register_retry_wake = threading.Event()
        self._assigned_task_lock = threading.RLock()
        self._assigned_task_inflight: set[str] = set()
        self._assigned_task_recent_terminal: dict[str, float] = {}
        self._assigned_task_fetch_requested = threading.Event()
        self._last_assigned_task_fetch_at = 0.0
        self._last_shared_brain_error_code = ""
        self.executor_core = ExecutorCore()
        self._start_runtime_register_retry_if_needed()
        native_file_indexer.handle_state_change()

    def _runtime_diag(self, event: str, **details: Any) -> None:
        payload = " ".join(
            f"{key}={str(value)}"
            for key, value in details.items()
            if str(value or "").strip()
        )
        suffix = f" {payload}" if payload else ""
        print(f"runtime {event}{suffix}", file=sys.stderr)

    def _log_backend_result(self, action: str, result: BackendResult) -> None:
        self._runtime_diag(
            "backend",
            action=action,
            status=result.status_code,
            request_id=result.x_request_id or result.request_id,
            ok=result.ok,
        )

    def _shared_brain_retrieval_eligible(self) -> bool:
        return bool(self._user_auth_ready() and hasattr(self.backend, "brain_retrieval_search"))

    def _record_executor_retrieval_usage(
        self,
        result: dict[str, Any],
        *,
        shared_metadata: dict[str, Any] | None = None,
    ) -> None:
        local_hits = 0
        shared_hits = 0
        fallback = False
        if isinstance(result, dict):
            if bool(result.get("retrievalUsed", False)):
                try:
                    local_hits = max(0, int(result.get("retrievalMatchCount", 0) or 0))
                except (TypeError, ValueError):
                    local_hits = 0
                fallback = str(result.get("retrievalStrategy", "") or "").strip().lower() == "lexical"
        if isinstance(shared_metadata, dict):
            try:
                shared_hits = max(0, int(shared_metadata.get("sharedRetrievalCount", 0) or 0))
            except (TypeError, ValueError):
                shared_hits = 0
            if shared_hits > 0 and local_hits == 0:
                fallback = True
        if local_hits > 0 or shared_hits > 0 or fallback:
            self.executor_core.record_retrieval(
                retrieval_hits=local_hits,
                shared_retrieval_hits=shared_hits,
                fallback=fallback,
            )

    def _local_provider_readiness(self, local_models: dict[str, Any]) -> dict[str, Any]:
        runtimes = local_models.get("runtimes", {}) if isinstance(local_models, dict) else {}
        runtimes = runtimes if isinstance(runtimes, dict) else {}
        state = STATE.snapshot()
        readiness: dict[str, Any] = {}
        for provider_id in ("ollama", "lmstudio", "llamacpp"):
            runtime_status = runtimes.get(provider_id)
            runtime_status = runtime_status if isinstance(runtime_status, dict) else {}
            readiness[provider_id] = {
                "enabled": _provider_enabled(state, provider_id),
                "configured": _provider_is_configured_for_chat(state, provider_id),
                "available": bool(runtime_status.get("available", False)),
                "reachable": bool(runtime_status.get("reachable", runtime_status.get("available", False))),
                "baseUrl": str(runtime_status.get("baseUrl", "") or ""),
                "defaultModel": _model_for_provider(state, provider_id),
                "latencyMs": max(0, int(runtime_status.get("latencyMs", 0) or 0)),
                "lastCheckedAt": str(runtime_status.get("lastCheckedAt", "") or ""),
                "errorCode": str(runtime_status.get("errorCode", "") or runtime_status.get("error", "") or ""),
            }
        return readiness

    def _cloud_provider_readiness(self) -> dict[str, Any]:
        state = STATE.snapshot()
        readiness: dict[str, Any] = {}
        for provider_id in ("openai", "gemini", "anthropic", "groq", "custom"):
            readiness[provider_id] = {
                "enabled": _provider_enabled(state, provider_id),
                "configured": _provider_is_configured_for_chat(state, provider_id),
                "defaultModel": _model_for_provider(state, provider_id),
                "liteLLMEligible": litellm_adapter.available(),
            }
        return readiness

    def _record_executor_model_route(self, execution_id: str, result: dict[str, Any], state: dict[str, Any]) -> None:
        provider = str(result.get("provider", "") or "").strip()
        if not provider:
            return
        model = str(result.get("model", "") or _model_for_provider(state, provider) or "").strip()
        execution_mode = str(result.get("executionMode", "") or "").strip()
        self.executor_core.record_model_route(
            execution_id,
            provider=provider,
            model=model,
            reason=execution_mode or provider,
        )
        if provider not in {"", "ollama", "lmstudio", "llamacpp", "local_tool", "local_planner"}:
            self.executor_core.record_fallback("local-first cloud fallback")

    def _execute_prompt_with_executor(
        self,
        *,
        source: str,
        conversation_id: str,
        task_id: str,
        text: str,
        route_fn: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        execution_id = self.executor_core.begin_execution(
            source=source,
            task_id=task_id,
            conversation_id=conversation_id,
            summary=text,
        )
        try:
            self.executor_core.record_stage(execution_id, "planning", detail=source)
            result = route_fn()
            self._record_executor_model_route(execution_id, result, STATE.snapshot())
            if result.get("needsConfirmation") is True:
                self.executor_core.record_stage(execution_id, "permission_gate", detail="pending_approval", status="waiting")
            elif result.get("clarificationNeeded") is True:
                self.executor_core.record_stage(execution_id, "verification", detail="clarification", status="completed")
            else:
                self.executor_core.record_stage(
                    execution_id,
                    "verification",
                    detail=str(result.get("executionMode", "") or "completed"),
                    status="completed" if result.get("ok") else "failed",
                )
            self.executor_core.finish_execution(
                execution_id,
                ok=bool(result.get("ok", False)),
                detail=str(result.get("content", "") or result.get("message", "") or ""),
            )
            return result
        except Exception as exc:
            self.executor_core.finish_execution(execution_id, ok=False, detail=str(exc) or "executor_prompt_failed")
            raise

    def _ollama_client_from_state(self) -> Any | None:
        state = STATE.snapshot()
        _, client = _local_runtime_client_from_state(state, "ollama")
        return client

    def _local_runtime_family(self, state: dict[str, Any] | None = None) -> str:
        current_state = state if isinstance(state, dict) else STATE.snapshot()
        return _local_runtime_family_from_state(current_state)

    def _lmstudio_client_from_state(self) -> Any | None:
        state = STATE.snapshot()
        _, client = _local_runtime_client_from_state(state, "lmstudio")
        return client

    def _llamacpp_client_from_state(self) -> Any | None:
        state = STATE.snapshot()
        _, client = _local_runtime_client_from_state(state, "llamacpp")
        return client

    def _selected_local_client(self, provider_id: str | None = None) -> tuple[str, Any | None]:
        state = STATE.snapshot()
        return _local_runtime_client_from_state(state, str(provider_id or "").strip().lower())

    def _runtime_transport_mode(self) -> str:
        return "websocket" if _websocket_runtime_available() else "heartbeat"

    def _runtime_register_identity_error(self) -> dict[str, str] | None:
        resolver = getattr(self.backend, "runtime_register_identity_error", None)
        if callable(resolver):
            return resolver()
        return None

    def _repair_invalid_runtime_identity(self, identity_error: dict[str, str]) -> None:
        self._invalidate_runtime_register_retry()
        error_code = str(identity_error.get("code", "") or "RUNTIME_REGISTER_INVALID_IDENTITY")
        repair = getattr(self.backend, "repair_invalid_runtime_identity", None)
        if callable(repair):
            repair(error_code)
            return
        safe_error_code = _safe_error_code(error_code).lower()
        STATE.update_state(
            {
                "runtime": {
                    "runtimeToken": "",
                    "deviceId": "",
                    "deviceSecret": "",
                    "connectionId": "",
                    "currentTaskId": "",
                    "ready": False,
                    "lifecycleState": "offline",
                    "websocketConnected": False,
                    "lastErrorCode": safe_error_code,
                    "lastXRequestId": "",
                },
                "pairing": {
                    "lastSessionId": "",
                    "desktopDeviceId": "",
                    "pairingToken": "",
                    "pairingCode": "",
                    "qrText": "",
                    "expiresAt": "",
                    "lastSessionStatus": "",
                    "lastErrorCode": safe_error_code,
                    "realtimeReady": False,
                    "lastHeartbeatAt": "",
                },
            }
        )

    def _runtime_register_retry_backoff_seconds(self) -> list[float]:
        return [0.0, 1.0, 2.0, 4.0]

    def _runtime_register_retry_snapshot(self) -> dict[str, Any]:
        state = STATE.snapshot()
        account = state.get("account", {})
        account = account if isinstance(account, dict) else {}
        pairing = state.get("pairing", {})
        pairing = pairing if isinstance(pairing, dict) else {}
        runtime = state.get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        return {
            "accessToken": str(account.get("accessToken", "") or "").strip(),
            "lastSessionId": str(pairing.get("lastSessionId", "") or "").strip(),
            "desktopDeviceId": str(pairing.get("desktopDeviceId", "") or "").strip(),
            "expiresAt": str(pairing.get("expiresAt", "") or "").strip(),
            "lastSessionStatus": str(pairing.get("lastSessionStatus", "") or "").strip(),
            "deviceId": str(runtime.get("deviceId", "") or "").strip(),
            "deviceSecret": str(runtime.get("deviceSecret", "") or "").strip(),
            "ready": bool(runtime.get("ready", False)),
        }

    def _runtime_register_retry_target_from_snapshot(self, snapshot: dict[str, Any]) -> dict[str, str] | None:
        last_session_id = str(snapshot.get("lastSessionId", "") or "").strip()
        desktop_device_id = str(snapshot.get("desktopDeviceId", "") or "").strip()
        device_id = str(snapshot.get("deviceId", "") or "").strip()
        if not last_session_id or not desktop_device_id or not device_id:
            return None
        return {
            "lastSessionId": last_session_id,
            "desktopDeviceId": desktop_device_id,
            "deviceId": device_id,
        }

    def _runtime_register_retry_eligible(self, snapshot: dict[str, Any]) -> bool:
        if not str(snapshot.get("accessToken", "") or "").strip():
            return False
        if str(snapshot.get("lastSessionStatus", "") or "").strip() != "claimed":
            return False
        if bool(snapshot.get("ready", False)):
            return False
        if _pairing_expired(str(snapshot.get("expiresAt", "") or "").strip()):
            return False
        return self._runtime_register_identity_error() is None

    def _runtime_register_retry_should_continue(
        self,
        target: dict[str, str],
        *,
        generation: int,
    ) -> bool:
        with self._runtime_register_retry_lock:
            if generation != self._runtime_register_retry_generation:
                return False
            active_target = self._runtime_register_retry_target
        if active_target != target:
            return False
        snapshot = self._runtime_register_retry_snapshot()
        if not self._runtime_register_retry_eligible(snapshot):
            return False
        current_target = self._runtime_register_retry_target_from_snapshot(snapshot)
        return current_target == target

    def _invalidate_runtime_register_retry(self) -> None:
        with self._runtime_register_retry_lock:
            self._runtime_register_retry_generation += 1
            self._runtime_register_retry_target = None
            self._runtime_register_retry_wake.set()

    def _start_runtime_register_retry_if_needed(self) -> None:
        snapshot = self._runtime_register_retry_snapshot()
        if not self._runtime_register_retry_eligible(snapshot):
            return
        target = self._runtime_register_retry_target_from_snapshot(snapshot)
        if target is None:
            return
        with self._runtime_register_retry_lock:
            if (
                self._runtime_register_retry_thread
                and self._runtime_register_retry_thread.is_alive()
                and self._runtime_register_retry_target == target
            ):
                return
            self._runtime_register_retry_generation += 1
            generation = self._runtime_register_retry_generation
            self._runtime_register_retry_target = target
            self._runtime_register_retry_wake.clear()
            thread = threading.Thread(
                target=self._runtime_register_retry_loop,
                args=(target, generation),
                name="elyan-runtime-register-retry",
                daemon=True,
            )
            self._runtime_register_retry_thread = thread
            thread.start()

    def _runtime_register_retry_loop(self, target: dict[str, str], generation: int) -> None:
        try:
            backoff = self._runtime_register_retry_backoff_seconds()
            attempt = 0
            while self._runtime_register_retry_should_continue(target, generation=generation):
                delay_seconds = backoff[attempt] if attempt < len(backoff) else 8.0
                if delay_seconds > 0:
                    if self._runtime_register_retry_wake.wait(delay_seconds):
                        return
                    if not self._runtime_register_retry_should_continue(target, generation=generation):
                        return
                result = self.ensure_runtime_registered()
                if result.get("ok"):
                    return
                register = result.get("register")
                register = register if isinstance(register, dict) else {}
                error_code = _safe_error_code(
                    register.get("error")
                    or result.get("error", {}).get("code")
                    or "runtime_register_failed"
                )
                self._runtime_state_patch(
                    lifecycle_state="claimed_registering",
                    ready=False,
                    websocket_connected=False,
                    error_code=error_code,
                )
                attempt += 1
        finally:
            with self._runtime_register_retry_lock:
                if generation == self._runtime_register_retry_generation:
                    self._runtime_register_retry_target = None
                if self._runtime_register_retry_thread is threading.current_thread():
                    self._runtime_register_retry_thread = None

    def _mark_runtime_connecting(self, request_id: str | None = None) -> None:
        self._runtime_state_patch(
            lifecycle_state="runtime_connecting",
            ready=False,
            websocket_connected=False,
            error_code="",
            x_request_id=request_id,
        )

    def _connect_runtime_transport(self) -> tuple[bool, BackendResult | None]:
        connected = self._start_runtime_websocket_if_needed()
        heartbeat = None
        if not connected:
            heartbeat = self._send_backend_runtime_heartbeat("online")
            if heartbeat.ok:
                self._runtime_state_patch(
                    lifecycle_state="ready",
                    ready=True,
                    websocket_connected=False,
                    error_code="",
                    x_request_id=heartbeat.x_request_id or heartbeat.request_id,
                )
            else:
                lifecycle = "reconnecting" if self._paired_runtime_ready() else "offline"
                self._runtime_state_patch(
                    lifecycle_state=lifecycle,
                    ready=False,
                    websocket_connected=False,
                    error_code=_safe_error_code(heartbeat.error or "runtime_heartbeat_failed"),
                    x_request_id=heartbeat.x_request_id or heartbeat.request_id,
                )
        if connected or (heartbeat and heartbeat.ok):
            self._start_task_relay_if_ready()
        return connected, heartbeat

    def _runtime_heartbeat_payload(self, status: str, current_task_id: str | None = None) -> dict[str, Any]:
        runtime_state = STATE.snapshot().get("runtime", {})
        runtime_state = runtime_state if isinstance(runtime_state, dict) else {}
        runtime_capabilities = _runtime_advertised_capabilities()
        local_models_state = self._local_models_capability_state()
        payload: dict[str, Any] = {
            "status": status,
            "capabilities": runtime_capabilities,
            "capabilityStates": _runtime_capability_states_payload(
                runtime_capabilities,
                runtime_state,
                local_models_state,
            ),
        }
        if current_task_id:
            payload["currentTaskId"] = current_task_id
        return payload

    def _local_models_capability_state(self) -> dict[str, Any]:
        models_payload = self.local_models_status()
        status = _map_from(models_payload.get("selectedRuntimeStatus") or models_payload.get("status"))
        models = _map_from(models_payload.get("models"))
        model_list = models.get("models") if isinstance(models.get("models"), list) else []
        selected_runtime = str(models_payload.get("selectedRuntime") or self._local_runtime_family()).strip() or "ollama"
        default_local_model = str(models_payload.get("defaultLocalModel") or status.get("defaultModel") or "").strip()
        base_url = str(status.get("baseUrl") or "").strip()
        available = bool(status.get("available")) or bool(models.get("available"))
        reachable = bool(status.get("reachable", available))
        configured = bool(status.get("configured", bool(default_local_model)))
        ready = reachable and configured and bool(default_local_model)
        error_code = ""
        if not reachable:
            error_code = str(status.get("errorCode", "") or f"{selected_runtime}_client_unavailable")
        elif not configured or not default_local_model:
            error_code = "local_model_not_selected"
        return {
            "available": available,
            "ready": ready,
            "version": selected_runtime,
            "stats": {
                "modelCount": len(model_list),
                "selectedRuntime": selected_runtime,
                "selectedRuntimeReady": ready,
                "selectedRuntimeReachable": reachable,
                "selectedRuntimeErrorCode": error_code,
                "defaultLocalModel": default_local_model,
                "baseUrl": base_url,
                "latencyMs": max(0, int(status.get("latencyMs", 0) or 0)),
                "lastCheckedAt": str(status.get("lastCheckedAt", "") or ""),
                "jobsRunning": len(models_payload.get("jobs", [])) if isinstance(models_payload.get("jobs"), list) else 0,
            },
            "errorCode": error_code,
        }

    def _control_plane_snapshot(self, local_models: dict[str, Any] | None = None) -> dict[str, Any]:
        state = STATE.snapshot()
        control_plane = state.get("controlPlane", {})
        control_plane = control_plane if isinstance(control_plane, dict) else {}
        health = _map_from(control_plane.get("health"))
        database = _map_from(health.get("database"))
        agent = _map_from(health.get("agent"))
        brain_profile = _map_from(control_plane.get("brainProfile"))
        brain_chat = _map_from(brain_profile.get("chat"))
        runtime_session = _map_from(control_plane.get("runtimeSession"))
        auth_me = _map_from(control_plane.get("authMe"))
        mobile_bootstrap = _map_from(control_plane.get("mobileBootstrap"))
        local_models_payload = local_models if isinstance(local_models, dict) else self.local_models_status()
        local_models_status = _map_from(local_models_payload.get("selectedRuntimeStatus") or local_models_payload.get("status"))
        local_models_models = _map_from(local_models_payload.get("models"))
        default_local_model = str(
            local_models_payload.get("defaultLocalModel") or local_models_status.get("defaultModel") or ""
        ).strip()
        local_models_available = bool(local_models_status.get("reachable", local_models_status.get("available", False))) or bool(local_models_models.get("available"))
        server_brain_ready = bool(brain_chat.get("isChatUsable", agent.get("serverBrainReady", health.get("ok", False))))
        database_ready = str(database.get("status", "") or "").lower() == "up"
        return {
            "ok": bool(health.get("ok", False)) and database_ready,
            "authMe": auth_me,
            "mobileBootstrap": mobile_bootstrap,
            "health": health,
            "brainProfile": brain_profile,
            "runtimeSession": runtime_session,
            "localModels": local_models_payload,
            "databaseReady": database_ready,
            "serverBrainReady": server_brain_ready,
            "localModelsReady": local_models_available and bool(local_models_status.get("configured", False)) and bool(default_local_model),
        }

    def _send_backend_runtime_heartbeat(self, status: str, current_task_id: str | None = None) -> BackendResult:
        self._runtime_state_patch(current_task_id=str(current_task_id or "").strip())
        return self.backend.heartbeat(self._runtime_heartbeat_payload(status, current_task_id))

    def _send_socket_runtime_heartbeat(self, status: str, current_task_id: str | None = None) -> bool:
        self._runtime_state_patch(current_task_id=str(current_task_id or "").strip())
        payload = {"type": "heartbeat", **self._runtime_heartbeat_payload(status, current_task_id)}
        return self._send_runtime_socket_message(payload)

    def _runtime_state_patch(
        self,
        *,
        lifecycle_state: str | None = None,
        ready: bool | None = None,
        websocket_connected: bool | None = None,
        current_task_id: str | None = None,
        error_code: str | None = None,
        x_request_id: str | None = None,
    ) -> None:
        runtime_patch: dict[str, Any] = {}
        pairing_patch: dict[str, Any] = {}
        if lifecycle_state is not None:
            runtime_patch["lifecycleState"] = lifecycle_state
        if ready is not None:
            runtime_patch["ready"] = ready
        if websocket_connected is not None:
            runtime_patch["websocketConnected"] = websocket_connected
        if current_task_id is not None:
            runtime_patch["currentTaskId"] = current_task_id
        if ready is not None or websocket_connected is not None:
            current_runtime = STATE.snapshot().get("runtime", {})
            current_runtime = current_runtime if isinstance(current_runtime, dict) else {}
            current_websocket = bool(current_runtime.get("websocketConnected")) if websocket_connected is None else websocket_connected
            current_ready = bool(current_runtime.get("ready")) if ready is None else ready
            pairing_patch["realtimeReady"] = bool(current_websocket or current_ready)
        if error_code is not None:
            runtime_patch["lastErrorCode"] = error_code
        if x_request_id is not None:
            runtime_patch["lastXRequestId"] = x_request_id
        patch: dict[str, Any] = {}
        if runtime_patch:
            patch["runtime"] = runtime_patch
        if pairing_patch:
            patch["pairing"] = pairing_patch
        if patch:
            STATE.update_state(patch)

    def _runtime_backend_snapshot(self) -> dict[str, Any]:
        me = self.backend.auth_me()
        mobile = self.backend.mobile_bootstrap()
        health = self.backend.health()
        brain_profile = self._brain_profile_result() if me.ok else BackendResult(
            ok=False,
            request_id=_request_id(),
            status_code=None,
            data=None,
            error="user_token_missing",
        )
        if mobile.ok and isinstance(mobile.data, dict):
            self._sync_task_inbox_from_bootstrap_payload(mobile.data)
        runtime_session = self.backend.runtime_session() if self._runtime_auth_ready() else BackendResult(
            ok=False,
            request_id=_request_id(),
            status_code=None,
            data=None,
            error="runtime_token_missing",
        )
        if runtime_session.ok and isinstance(runtime_session.data, dict):
            readiness = runtime_session.data.get("readiness", {})
            connection = runtime_session.data.get("connection", {})
            if not isinstance(readiness, dict):
                readiness = {}
            if not isinstance(connection, dict):
                connection = {}
            runtime_info = readiness.get("runtime", {})
            if not isinstance(runtime_info, dict):
                runtime_info = {}
            target_status = str(readiness.get("targetStatus", "") or "").strip().lower()
            can_receive_tasks = readiness.get("canReceiveTasks") is True
            is_connected = (
                str(connection.get("status", "") or "").strip().lower() == "online"
            )
            if can_receive_tasks and target_status == "ready":
                self._runtime_state_patch(
                    lifecycle_state="ready",
                    ready=True,
                    websocket_connected=is_connected,
                    error_code="",
                    x_request_id=runtime_session.x_request_id or runtime_session.request_id,
                )
                heartbeat_at = str(
                    runtime_info.get("lastHeartbeatAt")
                    or connection.get("lastHeartbeatAt")
                    or ""
                ).strip()
                pairing_patch: dict[str, Any] = {"realtimeReady": True}
                if heartbeat_at:
                    pairing_patch["lastHeartbeatAt"] = heartbeat_at
                STATE.update_state({"pairing": pairing_patch})
            else:
                lifecycle = "reconnecting" if self._paired_runtime_ready() else "offline"
                self._runtime_state_patch(
                    lifecycle_state=lifecycle,
                    ready=False,
                    websocket_connected=is_connected,
                    error_code="",
                    x_request_id=runtime_session.x_request_id or runtime_session.request_id,
                )
                STATE.update_state({"pairing": {"realtimeReady": False}})
        return {
            "configured": self.backend.configured,
            "loopback": self.backend.loopback,
            "authMe": me.to_dict(),
            "mobileBootstrap": mobile.to_dict(),
            "health": health.to_dict(),
            "brainProfile": brain_profile.to_dict(),
            "runtimeSession": runtime_session.to_dict(),
            "controlPlane": self._control_plane_snapshot(),
            "realtimeRuntime": {
                "ok": self._runtime_ws_connected,
                "transport": self._runtime_transport_mode(),
                "connected": self._runtime_ws_connected,
                "error": self._runtime_ws_last_error or None,
            },
        }

    def _task_inbox_items(self) -> list[dict[str, Any]]:
        inbox = STATE.get_task_inbox()
        items = inbox.get("items", [])
        if not isinstance(items, list):
            return []
        return [dict(item) for item in items if isinstance(item, dict)]

    def _normalized_task_inbox_item(
        self,
        task: dict[str, Any],
        *,
        artifact_count: int | None = None,
    ) -> dict[str, Any]:
        task_id = str(task.get("id", "") or "").strip()
        existing = STATE.get_task_inbox_item(task_id) or {}
        approval_request = task.get("approvalRequest")
        if not isinstance(approval_request, dict):
            approval_request = dict(existing.get("approvalRequest", {}) or {})
        if artifact_count is None:
            try:
                artifact_count = int(task.get("artifactCount") or existing.get("artifactCount") or 0)
            except (TypeError, ValueError):
                artifact_count = 0
        summary = str(task.get("summary", "") or "").strip() or str(existing.get("summary", "") or "").strip()
        error = str(task.get("error", "") or "").strip() or str(existing.get("error", "") or "").strip()
        updated_at = str(task.get("updatedAt", "") or "").strip() or _utc_now_iso()
        status = str(task.get("status", "") or existing.get("status", "") or "queued").strip()[:64]
        route_decision = task.get("routeDecision")
        if not isinstance(route_decision, dict):
            route_decision = dict(existing.get("routeDecision", {}) or {})
        return {
            "id": task_id,
            "title": str(task.get("title", "") or existing.get("title", "") or "Yeni görev").strip()[:200],
            "status": status,
            "targetDeviceId": str(task.get("targetDeviceId", "") or existing.get("targetDeviceId", "") or "").strip()[:80],
            "queuePosition": int(task.get("queuePosition") or existing.get("queuePosition") or 0),
            "summary": summary[:1000],
            "error": error[:240],
            "approvalRequest": approval_request,
            "routeDecision": route_decision,
            "deliveryState": str(task.get("deliveryState", "") or existing.get("deliveryState", "") or "").strip()[:32],
            "runtimeConnectionId": str(task.get("runtimeConnectionId", "") or existing.get("runtimeConnectionId", "") or "").strip()[:80],
            "dispatchLeaseId": str(task.get("dispatchLeaseId", "") or existing.get("dispatchLeaseId", "") or "").strip()[:120],
            "dispatchLeaseExpiresAt": str(task.get("dispatchLeaseExpiresAt", "") or existing.get("dispatchLeaseExpiresAt", "") or "").strip()[:80],
            "dispatchAckAt": str(task.get("dispatchAckAt", "") or existing.get("dispatchAckAt", "") or "").strip()[:80],
            "lastDispatchAttemptAt": str(task.get("lastDispatchAttemptAt", "") or existing.get("lastDispatchAttemptAt", "") or "").strip()[:80],
            "createdAt": str(task.get("createdAt", "") or existing.get("createdAt", "") or "").strip()[:80],
            "startedAt": str(task.get("startedAt", "") or existing.get("startedAt", "") or "").strip()[:80],
            "completedAt": str(task.get("completedAt", "") or existing.get("completedAt", "") or "").strip()[:80],
            "canceledAt": str(task.get("canceledAt", "") or existing.get("canceledAt", "") or "").strip()[:80],
            "updatedAt": updated_at[:80],
            "lastVerifiedAt": _utc_now_iso(),
            "lastRemoteStatus": status,
            "artifactCount": max(0, artifact_count or 0),
            "origin": "mobile",
        }

    def _reconcile_task_inbox_active_truth(self, active_task_ids: set[str]) -> None:
        STATE.reconcile_task_inbox(active_task_ids, last_synced_at=_utc_now_iso())

    def _sync_task_inbox_from_bootstrap_payload(self, payload: dict[str, Any]) -> None:
        recent_tasks = payload.get("recentTasks", [])
        if not isinstance(recent_tasks, list):
            return
        items = [
            self._normalized_task_inbox_item(task)
            for task in recent_tasks
            if isinstance(task, dict) and str(task.get("id", "") or "").strip()
        ]
        summary = payload.get("summary", {})
        summary = summary if isinstance(summary, dict) else {}
        try:
            pending_count = int(summary.get("pendingApprovals")) if "pendingApprovals" in summary else None
        except (TypeError, ValueError):
            pending_count = None
        try:
            active_count = int(summary.get("activeTasks")) if "activeTasks" in summary else None
        except (TypeError, ValueError):
            active_count = None
        STATE.sync_task_inbox(
            items,
            pending_count=pending_count,
            active_count=active_count,
            last_synced_at=_utc_now_iso(),
        )
        self._reconcile_task_inbox_active_truth(
            {
                str(task.get("id", "") or "").strip()
                for task in recent_tasks
                if isinstance(task, dict)
            }
        )

    def _sync_task_inbox_item_from_detail(self, payload: dict[str, Any]) -> None:
        task = payload.get("task", {})
        if not isinstance(task, dict):
            return
        artifacts = payload.get("artifacts", [])
        artifact_count = len(artifacts) if isinstance(artifacts, list) else None
        STATE.upsert_task_inbox_item(
            self._normalized_task_inbox_item(task, artifact_count=artifact_count),
            last_synced_at=_utc_now_iso(),
        )

    def _sync_task_inbox_status(self, task_id: str, payload: dict[str, Any]) -> None:
        existing = STATE.get_task_inbox_item(task_id) or {"id": task_id}
        artifacts = payload.get("artifacts", [])
        artifact_count = existing.get("artifactCount", 0)
        if isinstance(artifacts, list):
            artifact_count = len(artifacts)
        approval_request = payload.get("approvalRequest")
        if not isinstance(approval_request, dict):
            approval_request = {}
        summary = str(payload.get("summary", "") or "").strip()
        if not summary:
            summary = str(payload.get("message", "") or "").strip()
        task = {
            **existing,
            "id": task_id,
            "status": str(payload.get("status", "") or existing.get("status", "") or "queued"),
            "summary": summary or str(existing.get("summary", "") or ""),
            "error": str(payload.get("error", "") or "").strip() or str(existing.get("error", "") or ""),
            "approvalRequest": approval_request,
            "updatedAt": _utc_now_iso(),
            "lastVerifiedAt": _utc_now_iso(),
            "lastRemoteStatus": str(payload.get("status", "") or existing.get("status", "") or "queued"),
            "artifactCount": artifact_count,
        }
        STATE.upsert_task_inbox_item(task, last_synced_at=_utc_now_iso())

    def _sync_task_inbox_artifacts(self, task_id: str, artifacts: list[dict[str, Any]]) -> None:
        existing = STATE.get_task_inbox_item(task_id) or {"id": task_id}
        artifact_count = len(artifacts) if isinstance(artifacts, list) else int(existing.get("artifactCount") or 0)
        STATE.upsert_task_inbox_item(
            {
                **existing,
                "id": task_id,
                "artifactCount": artifact_count,
                "updatedAt": _utc_now_iso(),
            },
            last_synced_at=_utc_now_iso(),
        )

    def _resync_terminal_remote_task(self, task_id: str) -> None:
        def _run() -> None:
            for delay_seconds in (0.0, 0.35, 1.0):
                if delay_seconds > 0:
                    time.sleep(delay_seconds)
                try:
                    detail = self.backend.task_detail(task_id)
                except Exception:
                    return
                if detail.ok and isinstance(detail.data, dict):
                    self._sync_task_inbox_item_from_detail(detail.data)
                    return
                if detail.status_code in {404, 410}:
                    self._reconcile_task_inbox_active_truth(set())
                    return

        threading.Thread(
            target=_run,
            name="elyan-runtime-task-resync",
            daemon=True,
        ).start()

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = str(item or "").strip()
            if text:
                result.append(text)
        return result

    def _truncate_text(self, value: Any, limit: int) -> str:
        text = str(value or "").strip()
        if len(text) <= limit:
            return text
        return text[: limit - 1].rstrip() + "…"

    def _approval_request_payload(self, local_result: dict[str, Any]) -> dict[str, Any]:
        plan_preview = local_result.get("planPreview", {})
        plan_preview = plan_preview if isinstance(plan_preview, dict) else {}
        structured_result = local_result.get("structuredResult", {})
        structured_result = structured_result if isinstance(structured_result, dict) else {}
        structured_kind = str(
            structured_result.get("kind", "") or local_result.get("kind", "") or "",
        ).strip()
        structured_to = self._string_list(
            structured_result.get("to") if "to" in structured_result else local_result.get("to")
        )
        structured_subject = self._truncate_text(
            structured_result.get("subject") if "subject" in structured_result else local_result.get("subject"),
            180,
        )
        structured_body = str(
            structured_result.get("body", "") or structured_result.get("message", "") or "",
        ).strip()
        body_preview = self._truncate_text(
            structured_body or local_result.get("assistantMessage", ""),
            280,
        )
        raw_steps = plan_preview.get("steps", [])
        safe_steps: list[dict[str, Any]] = []
        if isinstance(raw_steps, list):
            for step in raw_steps[:6]:
                if not isinstance(step, dict):
                    continue
                description = str(step.get("description", "") or step.get("capability", "") or "").strip()[:180]
                capability = str(step.get("capability", "") or "").strip()[:80]
                entry: dict[str, Any] = {}
                if capability:
                    entry["capability"] = capability
                if description:
                    entry["description"] = description
                if entry:
                    safe_steps.append(entry)
        summary = str(
            plan_preview.get("summary", "")
            or local_result.get("assistantMessage", "")
            or "Yerel işlem onayı gerekiyor."
        ).strip()[:500]
        title = "Onay gerekli"
        if structured_kind == "email_send":
            title = "Mail gönderilsin mi?"
        elif structured_kind == "email_draft":
            title = "Mail taslağı hazır mı?"
        message_parts: list[str] = []
        if structured_to:
            message_parts.append(f"Alıcı: {', '.join(structured_to)}")
        if structured_subject:
            message_parts.append(f"Konu: {structured_subject}")
        if body_preview:
            message_parts.append(f"Özet: {body_preview}")
        message = self._truncate_text("\n".join(message_parts) or summary or "Yerel işlem onayı gerekiyor.", 700)
        payload: dict[str, Any] = {
            "title": title,
            "message": message,
            "summary": summary or "Yerel işlem onayı gerekiyor.",
            "reason": "Desktop üzerinde yan etkili yerel işlem için onay gerekiyor.",
            "steps": safe_steps,
            "source": "desktop_runtime",
        }
        if structured_kind:
            payload["kind"] = structured_kind
        if structured_to:
            payload["to"] = structured_to
            payload["recipientCount"] = len(structured_to)
        if structured_subject:
            payload["subject"] = structured_subject
        if body_preview:
            payload["bodyPreview"] = body_preview
        provider = str(structured_result.get("provider", "") or "").strip()
        if provider:
            payload["provider"] = provider
        return {
            **payload,
            "confirmLabel": "Onayla",
            "rejectLabel": "Reddet",
        }

    def _pending_plan_permission_error(self, pending_plan_id: str) -> dict[str, str] | None:
        plan = STATE.get_pending_plan(pending_plan_id)
        if not isinstance(plan, dict):
            return None
        steps = plan.get("steps", [])
        steps = [dict(step) for step in steps if isinstance(step, dict)]
        fallback_capability = str(plan.get("capability", "") or "").strip()
        for step in steps or [{"capability": fallback_capability, "args": {}}]:
            capability = str(step.get("capability", "") or fallback_capability).strip()
            if capability not in PERSONAL_ACTION_CAPABILITIES:
                continue
            args = step.get("args", {})
            args = dict(args) if isinstance(args, dict) else {}
            decision = evaluate_tool(capability, {**args, "_confirmed": True}, STATE.snapshot())
            if not decision.allowed:
                return {
                    "code": decision.code or "PERMISSION_REQUIRED",
                    "message": decision.message or "Bu işlem için açık izin gerekiyor.",
                }
        return None

    def _summary_artifacts(self, assistant_message: str, provider: str) -> list[dict[str, Any]]:
        if not assistant_message:
            return []
        return [
            {
                "kind": "summary",
                "name": "elyan-result.txt",
                "contentType": "text/plain; charset=utf-8",
                "textContent": assistant_message,
                "metadata": {"provider": provider},
            }
        ]

    def _set_runtime_task_heartbeat(
        self,
        dispatched_via_websocket: bool,
        status: str,
        task_id: str = "",
    ) -> None:
        normalized_status = str(status or "").strip().lower()
        if dispatched_via_websocket:
            socket_status = "busy" if normalized_status == "busy" else "online"
            self._send_socket_runtime_heartbeat(socket_status, task_id if socket_status == "busy" else "")
            return
        backend_status = "busy" if normalized_status == "busy" else "idle"
        self._send_backend_runtime_heartbeat(backend_status, task_id if backend_status == "busy" else "")

    def _runtime_task_result_payload(self, local_result: dict[str, Any]) -> dict[str, Any]:
        structured_result = local_result.get("structuredResult")
        result_payload: dict[str, Any] = {
            "assistantMessage": str(local_result.get("assistantMessage", "") or "").strip(),
            "provider": str(local_result.get("provider", "") or ""),
            "toolEvents": local_result.get("toolEvents", []) if isinstance(local_result.get("toolEvents"), list) else [],
            "conversationId": local_result.get("conversationId", ""),
            "structuredResult": structured_result,
        }
        if isinstance(structured_result, dict) and isinstance(structured_result.get("quantum"), dict):
            result_payload["quantum"] = dict(structured_result["quantum"])
        return result_payload

    def _runtime_task_terminal_payload(
        self,
        local_result: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        chat_ok = local_result.get("chatOk", True) is not False
        assistant_message = str(local_result.get("assistantMessage", "") or "").strip()
        provider = str(local_result.get("provider", "") or "")
        artifacts = [
            dict(item)
            for item in (local_result.get("artifacts", []) if isinstance(local_result.get("artifacts"), list) else [])
            if isinstance(item, dict)
        ]
        if assistant_message and not any(str(item.get("kind", "") or "").strip() == "summary" for item in artifacts):
            artifacts.extend(self._summary_artifacts(assistant_message, provider))
        payload: dict[str, Any] = {
            "status": "completed" if chat_ok else "failed",
            "message": "Görev tamamlandı." if chat_ok else "Görev güvenli şekilde tamamlanamadı.",
            "summary": assistant_message[:1000],
            "approvalRequest": {},
            "result": self._runtime_task_result_payload(local_result),
            "artifacts": artifacts,
        }
        if not chat_ok:
            payload["error"] = str(
                local_result.get("error", {}).get("code", "runtime_task_failed")
                if isinstance(local_result.get("error"), dict)
                else "runtime_task_failed"
            )
        return payload, artifacts, chat_ok

    def _report_runtime_task_terminal_result(
        self,
        task_id: str,
        local_result: dict[str, Any],
        *,
        dispatched_via_websocket: bool,
        separate_artifacts: bool = False,
    ) -> dict[str, Any]:
        status_payload, artifacts, chat_ok = self._runtime_task_terminal_payload(local_result)
        should_split_artifacts = dispatched_via_websocket or separate_artifacts
        artifact_report = None
        if should_split_artifacts:
            artifact_report = self._report_runtime_task_artifacts(task_id, artifacts)
            status_payload["artifacts"] = []
        report = self._report_runtime_task_status(task_id, status_payload)
        return {
            "taskId": task_id,
            "ok": bool(chat_ok and report and report.ok),
            "status": status_payload["status"],
            "report": report.to_dict() if report else None,
            "artifactReport": artifact_report.to_dict() if artifact_report else None,
            "local": {
                "conversationId": local_result.get("conversationId", ""),
                "provider": str(local_result.get("provider", "") or ""),
            },
        }

    def _apply_runtime_registration_result(self, result: BackendResult) -> None:
        if not result.ok or not isinstance(result.data, dict):
            return
        runtime = result.data.get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        tokens = result.data.get("tokens", {})
        tokens = tokens if isinstance(tokens, dict) else {}
        patch: dict[str, Any] = {
            "runtime": {
                "runtimeToken": str(tokens.get("accessToken", "") or tokens.get("access_token", "") or ""),
                "deviceId": str(runtime.get("deviceId", "") or ""),
                "connectionId": str(runtime.get("connectionId", "") or ""),
                "currentTaskId": "",
                "ready": False,
                "lifecycleState": "runtime_connecting",
                "websocketConnected": False,
                "lastErrorCode": "",
                "lastXRequestId": result.x_request_id or result.request_id,
            }
        }
        current_runtime = STATE.snapshot().get("runtime", {})
        if isinstance(current_runtime, dict) and str(current_runtime.get("deviceSecret", "") or "").strip():
            patch["runtime"]["deviceSecret"] = str(current_runtime.get("deviceSecret", "") or "")
        STATE.update_state(patch)

    def _has_active_remote_tasks(self) -> bool:
        active_statuses = {"queued", "planning", "running", "waiting_approval"}
        for item in self._task_inbox_items():
            status = str(item.get("status", "") or "").strip().lower()
            if status in active_statuses:
                return True
        return False

    def _relay_mode(self) -> str:
        if self._has_active_remote_tasks():
            return "active"
        runtime = STATE.snapshot().get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        lifecycle = str(runtime.get("lifecycleState", "") or "").strip().lower()
        if lifecycle in {"claimed_registering", "runtime_connecting", "reconnecting"}:
            return "reconnecting"
        return "idle"

    def _relay_interval_seconds(self) -> float:
        try:
            active_raw = float(os.environ.get("ELYAN_RUNTIME_RELAY_ACTIVE_INTERVAL_SECONDS", "2.0"))
        except ValueError:
            active_raw = 2.0
        try:
            reconnecting_raw = float(
                os.environ.get("ELYAN_RUNTIME_RELAY_RECONNECTING_INTERVAL_SECONDS", "3.25")
            )
        except ValueError:
            reconnecting_raw = 3.25
        try:
            idle_raw = float(os.environ.get("ELYAN_RUNTIME_RELAY_IDLE_INTERVAL_SECONDS", "5"))
        except ValueError:
            idle_raw = 5.0
        mode = self._relay_mode()
        if mode == "active":
            raw = active_raw
        elif mode == "reconnecting":
            raw = reconnecting_raw
        else:
            raw = idle_raw
        return min(30.0, max(1.5, raw))

    def _relay_task_fetch_limit(self) -> int:
        mode = self._relay_mode()
        if mode == "active":
            return 2
        if mode == "reconnecting":
            return 3
        return 1

    def _assigned_task_poll_fallback_seconds(self) -> float:
        mode = self._relay_mode()
        if mode == "reconnecting":
            return 4.0
        if mode == "active":
            return 8.0
        return 12.0

    def _request_assigned_task_fetch(self) -> None:
        self._assigned_task_fetch_requested.set()

    def _should_poll_assigned_tasks(self) -> bool:
        if not self._runtime_ws_connected:
            return True
        if self._assigned_task_fetch_requested.is_set():
            return True
        if self._last_assigned_task_fetch_at <= 0:
            return True
        return (time.monotonic() - self._last_assigned_task_fetch_at) >= self._assigned_task_poll_fallback_seconds()

    def _runtime_auth_ready(self) -> bool:
        runtime = STATE.snapshot().get("runtime", {})
        if not isinstance(runtime, dict):
            return False
        return bool(str(runtime.get("runtimeToken", "") or "").strip())

    def _user_auth_ready(self) -> bool:
        account = STATE.snapshot().get("account", {})
        if not isinstance(account, dict):
            return False
        return bool(str(account.get("accessToken", "") or "").strip())

    def _paired_runtime_ready(self) -> bool:
        runtime = STATE.snapshot().get("runtime", {})
        if not isinstance(runtime, dict):
            return False
        return bool(
            str(runtime.get("deviceId", "") or "").strip()
            and str(runtime.get("deviceSecret", "") or "").strip()
        )

    def _prime_runtime_task_delivery(self) -> None:
        try:
            heartbeat = self._send_backend_runtime_heartbeat("online")
            if heartbeat.ok:
                self._runtime_state_patch(
                    lifecycle_state="ready",
                    ready=True,
                    websocket_connected=self._runtime_ws_connected,
                    error_code="",
                    x_request_id=heartbeat.x_request_id or heartbeat.request_id,
                )
            self._request_assigned_task_fetch()
            self.execute_assigned_runtime_tasks(limit=2)
        except Exception as exc:
            print(f"runtime relay prime error type={type(exc).__name__}", file=sys.stderr)

    def _try_mark_assigned_task_inflight(self, task_id: str) -> bool:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return False
        with self._assigned_task_lock:
            if normalized_task_id in self._assigned_task_inflight:
                return False
            self._assigned_task_inflight.add(normalized_task_id)
            return True

    def _recent_terminal_ttl_seconds(self) -> float:
        try:
            raw = float(os.environ.get("ELYAN_RUNTIME_RECENT_TERMINAL_TASK_TTL_SECONDS", "600"))
        except ValueError:
            raw = 600.0
        return min(3600.0, max(30.0, raw))

    def _prune_recent_terminal_tasks_locked(self) -> None:
        if not self._assigned_task_recent_terminal:
            return
        cutoff = time.monotonic() - self._recent_terminal_ttl_seconds()
        self._assigned_task_recent_terminal = {
            task_id: timestamp
            for task_id, timestamp in self._assigned_task_recent_terminal.items()
            if timestamp >= cutoff
        }
        if len(self._assigned_task_recent_terminal) > 128:
            self._assigned_task_recent_terminal = dict(
                sorted(
                    self._assigned_task_recent_terminal.items(),
                    key=lambda item: item[1],
                    reverse=True,
                )[:128]
            )

    def _remember_terminal_assigned_task(self, task_id: str) -> None:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return
        with self._assigned_task_lock:
            self._prune_recent_terminal_tasks_locked()
            self._assigned_task_recent_terminal[normalized_task_id] = time.monotonic()

    def _is_recent_terminal_assigned_task(self, task_id: str) -> bool:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return False
        with self._assigned_task_lock:
            self._prune_recent_terminal_tasks_locked()
            return normalized_task_id in self._assigned_task_recent_terminal

    def _clear_assigned_task_inflight(self, task_id: str) -> None:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return
        with self._assigned_task_lock:
            self._assigned_task_inflight.discard(normalized_task_id)

    def _begin_assigned_task_execution(self, task_id: str) -> str:
        normalized_task_id = str(task_id or "").strip()
        if not normalized_task_id:
            return "missing_task_id"
        if self._is_recent_terminal_assigned_task(normalized_task_id):
            return "skipped_recent_terminal"
        if not self._try_mark_assigned_task_inflight(normalized_task_id):
            return "skipped_duplicate"
        return "accepted"

    def _execute_websocket_dispatched_task(self, task_id: str, task: dict[str, Any]) -> None:
        try:
            self._execute_runtime_task(task, True)
        finally:
            self._clear_assigned_task_inflight(task_id)

    def _runtime_register_payload(self) -> dict[str, Any] | None:
        identity_error = self._runtime_register_identity_error()
        if identity_error is not None:
            return None
        runtime = STATE.snapshot().get("runtime", {})
        if not isinstance(runtime, dict):
            return None
        device_id = str(runtime.get("deviceId", "") or "").strip()
        device_secret = str(runtime.get("deviceSecret", "") or "").strip()
        if not device_id or not device_secret:
            return None
        runtime_capabilities = _runtime_advertised_capabilities()
        local_models_state = self._local_models_capability_state()
        return {
            "deviceId": device_id,
            "deviceSecret": device_secret,
            "runtimeVersion": "1.0.0",
            "capabilities": runtime_capabilities,
            "capabilityStates": _runtime_capability_states_payload(
                runtime_capabilities,
                runtime,
                local_models_state,
            ),
        }

    def _runtime_ws_headers(self) -> list[str]:
        token = str(STATE.snapshot().get("runtime", {}).get("runtimeToken", "") or "").strip()
        if not token:
            return []
        return [f"Authorization: Bearer {token}"]

    def _runtime_ws_enabled(self) -> bool:
        return _websocket_runtime_available() and bool(self.backend.runtime_websocket_url())

    def _runtime_ws_should_run(self) -> bool:
        return not self._runtime_ws_stop.is_set() and self._runtime_auth_ready() and self._runtime_ws_enabled()

    def _stop_runtime_websocket(self) -> None:
        self._runtime_ws_stop.set()
        with self._runtime_ws_lock:
            app = self._runtime_ws_app
            self._runtime_ws_app = None
        try:
            if app is not None:
                app.close()
        except Exception:
            pass
        thread = self._runtime_ws_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._runtime_ws_thread = None
        self._runtime_ws_connected = False
        self._runtime_state_patch(
            lifecycle_state="offline",
            ready=False,
            websocket_connected=False,
        )

    def _start_runtime_websocket_if_needed(self) -> bool:
        if not self._runtime_ws_enabled() or not self._runtime_auth_ready():
            return False
        with self._runtime_ws_lock:
            if self._runtime_ws_thread and self._runtime_ws_thread.is_alive():
                return True
            self._runtime_ws_stop.clear()
            self._runtime_ws_thread = threading.Thread(
                target=self._runtime_ws_loop,
                name="elyan-runtime-websocket",
                daemon=True,
            )
            self._runtime_ws_thread.start()
        return True

    def _send_runtime_socket_message(self, payload: dict[str, Any]) -> bool:
        if not self._runtime_ws_connected:
            return False
        with self._runtime_ws_lock:
            app = self._runtime_ws_app
        if app is None:
            return False
        try:
            app.send(json.dumps(payload, ensure_ascii=False))
            return True
        except Exception as exc:
            self._runtime_ws_last_error = type(exc).__name__
            self._runtime_diag("ws_send_failed", error=type(exc).__name__)
            return False

    def _start_task_relay_if_ready(self) -> None:
        if not self._runtime_auth_ready():
            return
        if self._relay_thread and self._relay_thread.is_alive():
            return
        self._relay_thread = threading.Thread(target=self._task_relay_loop, name="elyan-runtime-relay", daemon=True)
        self._relay_thread.start()

    def _runtime_ws_loop(self) -> None:
        websocket_module = _websocket_module()
        if websocket_module is None:
            return

        backoff_seconds = 1.0
        while not self._runtime_ws_stop.is_set():
            if not self._runtime_ws_should_run():
                self._runtime_state_patch(
                    lifecycle_state="offline",
                    ready=False,
                    websocket_connected=False,
                )
                return

            ws_url = self.backend.runtime_websocket_url()
            headers = self._runtime_ws_headers()
            if not ws_url or not headers:
                return

            self._runtime_state_patch(
                lifecycle_state="runtime_connecting",
                ready=False,
                websocket_connected=False,
                error_code="",
            )

            def _on_open(_app: Any) -> None:
                self._runtime_ws_connected = True
                self._runtime_ws_last_error = ""
                self._runtime_state_patch(
                    lifecycle_state="ready",
                    ready=True,
                    websocket_connected=True,
                    error_code="",
                )
                self._runtime_diag("ws_open")
                self._send_socket_runtime_heartbeat("online")
                self._prime_runtime_task_delivery()

            def _on_message(_app: Any, message: Any) -> None:
                self._handle_runtime_ws_message(message)

            def _on_error(_app: Any, error: Any) -> None:
                self._runtime_ws_last_error = type(error).__name__ if not isinstance(error, str) else error
                self._runtime_state_patch(
                    lifecycle_state="reconnecting",
                    ready=False,
                    websocket_connected=False,
                    error_code=self._runtime_ws_last_error,
                )
                self._runtime_diag("ws_error", error=self._runtime_ws_last_error)

            def _on_close(_app: Any, status_code: Any, message: Any) -> None:
                self._runtime_ws_connected = False
                lifecycle = "offline" if self._runtime_ws_stop.is_set() or not self._paired_runtime_ready() else "reconnecting"
                self._runtime_state_patch(
                    lifecycle_state=lifecycle,
                    ready=False,
                    websocket_connected=False,
                )
                self._runtime_diag(
                    "ws_close",
                    status=status_code,
                    reason=message,
                )

            app = websocket_module.WebSocketApp(  # type: ignore[union-attr]
                ws_url,
                header=headers,
                on_open=_on_open,
                on_message=_on_message,
                on_error=_on_error,
                on_close=_on_close,
            )
            with self._runtime_ws_lock:
                self._runtime_ws_app = app

            try:
                app.run_forever(
                    ping_interval=20,
                    ping_timeout=10,
                    ping_payload="elyan",
                    skip_utf8_validation=True,
                )
            except Exception as exc:
                self._runtime_ws_last_error = type(exc).__name__
                self._runtime_diag("ws_run_failed", error=type(exc).__name__)
            finally:
                with self._runtime_ws_lock:
                    if self._runtime_ws_app is app:
                        self._runtime_ws_app = None

            if self._runtime_ws_stop.is_set() or not self._paired_runtime_ready():
                return

            refreshed = self._refresh_runtime_registration_for_reconnect()
            if not refreshed:
                lifecycle = "reconnecting" if self._paired_runtime_ready() else "offline"
                self._runtime_state_patch(
                    lifecycle_state=lifecycle,
                    ready=False,
                    websocket_connected=False,
                    error_code="runtime_register_failed",
                )
                self._runtime_ws_stop.wait(min(30.0, backoff_seconds))
                backoff_seconds = min(30.0, backoff_seconds * 2)
                continue

            backoff_seconds = 1.0

    def _refresh_runtime_registration_for_reconnect(self) -> bool:
        payload = self._runtime_register_payload()
        if payload is None:
            return False
        register = self.backend.register_runtime(payload)
        if not register.ok:
            self._runtime_diag(
                "runtime_register_failed",
                status=register.status_code,
                request_id=register.x_request_id or register.request_id,
            )
            return False
        self._apply_runtime_registration_result(register)
        self._mark_runtime_connecting(register.x_request_id or register.request_id)
        self._prime_runtime_task_delivery()
        self._runtime_diag(
            "runtime_register_ok",
            request_id=register.x_request_id or register.request_id,
        )
        return True

    def _handle_runtime_ws_message(self, raw_message: Any) -> None:
        try:
            payload = json.loads(str(raw_message))
        except Exception:
            self._runtime_diag("ws_message_invalid")
            return
        if not isinstance(payload, dict):
            return

        message_type = str(payload.get("type", "") or "")
        if message_type == "task.dispatch":
            task = payload.get("task", {})
            if isinstance(task, dict):
                task_id = str(task.get("id", "") or "").strip()
                lease_id = str(payload.get("leaseId", "") or task.get("leaseId", "") or "").strip()
                dispatch_state = self._begin_assigned_task_execution(task_id)
                if dispatch_state != "accepted":
                    self._runtime_diag("ws_dispatch_skipped", task_id=task_id, reason=dispatch_state)
                    return
                if lease_id:
                    ack_payload = {"type": "task.ack", "taskId": task_id, "leaseId": lease_id}
                    if not self._send_runtime_socket_message(ack_payload):
                        self._clear_assigned_task_inflight(task_id)
                        self._runtime_diag("ws_ack_failed", task_id=task_id, lease_id=lease_id)
                        return
                threading.Thread(
                    target=self._execute_websocket_dispatched_task,
                    args=(task_id, task),
                    name="elyan-runtime-task-dispatch",
                    daemon=True,
                ).start()
            return

        if message_type == "task.approval":
            task_id = str(payload.get("taskId", "") or "").strip()
            approved = bool(payload.get("approved", False))
            if task_id:
                threading.Thread(
                    target=self._resume_remote_task_after_approval,
                    args=(task_id, approved),
                    name="elyan-runtime-task-approval",
                    daemon=True,
                ).start()
            return

        if message_type == "task.cancel":
            task_id = str(payload.get("taskId", "") or "").strip()
            if task_id:
                self._cancel_remote_pending_task(task_id)
            return

        if message_type == "error":
            self._runtime_ws_last_error = str(payload.get("message", "") or "runtime_socket_error")
            self._runtime_diag("ws_server_error", message=self._runtime_ws_last_error)

    def _task_relay_loop(self) -> None:
        while not self._relay_stop.is_set():
            try:
                if self._runtime_auth_ready():
                    if not self._runtime_ws_connected:
                        self._start_runtime_websocket_if_needed()
                    self._send_backend_runtime_heartbeat("online")
                    if self._should_poll_assigned_tasks():
                        self.execute_assigned_runtime_tasks(limit=self._relay_task_fetch_limit())
                elif self._paired_runtime_ready():
                    self._start_runtime_register_retry_if_needed()
            except Exception as exc:
                print(f"runtime relay error type={type(exc).__name__}", file=sys.stderr)
            interval = self._relay_interval_seconds()
            self._relay_stop.wait(interval)

    def bootstrap(self) -> dict[str, Any]:
        backend_snapshot = self._runtime_backend_snapshot()
        state = STATE.snapshot()
        return {
            "state": state,
            "workspace": {
                "projects": _workspace_projects(),
            },
            "conversations": _conversation_entries(),
            "runtime": self.status(),
            "backend": backend_snapshot,
            "localModels": self.local_models_status(),
        }

    def status(self) -> dict[str, Any]:
        state = STATE.snapshot()
        runtime = state.get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        transport_mode = self._runtime_transport_mode()
        runtime_ready = bool(runtime.get("ready")) or self._runtime_ws_connected
        runtime_capabilities_raw = runtime.get("capabilities")
        runtime_capabilities = []
        if isinstance(runtime_capabilities_raw, list):
            runtime_capabilities = sorted(
                {
                    str(item or "").strip()
                    for item in runtime_capabilities_raw
                    if str(item or "").strip()
                }
            )
        if not runtime_capabilities:
            runtime_capabilities = _runtime_advertised_capabilities()
        runtime_capability_groups = capability_groups(runtime_capabilities)
        local_models = self.local_models_status()
        runtime_capability_states = _runtime_capability_states_payload(
            runtime_capabilities,
            runtime,
            self._local_models_capability_state(),
        )
        retrieval_status = _retrieval_status_payload()
        retrieval_status["sharedBrainEligible"] = self._shared_brain_retrieval_eligible()
        retrieval_status["lastSharedBrainErrorCode"] = self._last_shared_brain_error_code
        executor_status = self.executor_core.status_payload(
            state=state,
            runtime_capabilities=runtime_capabilities,
            local_provider_readiness=self._local_provider_readiness(local_models),
            cloud_provider_readiness=self._cloud_provider_readiness(),
        )
        return {
            "ok": True,
            "startedAt": self.context.started_at,
            "pythonVersion": sys.version.split()[0],
            "bridgePid": os.getpid(),
            "requestCount": self.context.request_count,
            "googleAvailable": _google_live_available(),
            "backendConfigured": self.backend.configured,
            "backendLoopback": self.backend.loopback,
            "activeProvider": _current_provider(state),
            "activeConversationId": str(state.get("conversation", {}).get("activeId", "") or ""),
            "runtimeLifecycleState": str(runtime.get("lifecycleState", "offline") or "offline"),
            "runtimeCurrentTaskId": str(runtime.get("currentTaskId", "") or "").strip(),
            "runtimeCapabilities": runtime_capabilities,
            "runtimeCapabilityStates": runtime_capability_states,
            "runtimeCapabilityGroups": runtime_capability_groups,
            "runtimeCapabilityCount": len(runtime_capabilities),
            "runtimeCapabilityMetadataSummary": capability_metadata_summary(runtime_capabilities),
            "runtimeReady": runtime_ready,
            "runtimeWebsocketConnected": self._runtime_ws_connected,
            "controlPlane": self._control_plane_snapshot(local_models),
            "localModels": local_models,
            "executorStatus": executor_status,
            "agentStatus": executor_status.get("agentStatus", {}) if isinstance(executor_status, dict) else {},
            "runtimeTransport": {
                "mode": transport_mode,
                "connected": self._runtime_ws_connected if transport_mode == "websocket" else runtime_ready,
                "lastErrorCode": str(runtime.get("lastErrorCode", "") or "").strip(),
                "lastXRequestId": str(runtime.get("lastXRequestId", "") or "").strip(),
            },
            "dependencyStatus": _dependency_status_payload(),
            "speechStatus": _speech_status_payload(),
            "retrievalStatus": retrieval_status,
            "desktopNativeStatus": _native_desktop_dependency_status(),
            "taskIntelligenceStatus": STATE.get_task_intelligence_status(),
            "artifactSelectionStatus": _artifact_selection_status_payload(),
            "mcpStatus": _mcp_status_payload(),
            "skillStatus": _skill_status_payload(),
            "taskInbox": STATE.get_task_inbox(),
        }

    def get_state(self) -> dict[str, Any]:
        return {
            "state": STATE.snapshot(),
            "workspace": {"projects": _workspace_projects()},
            "conversations": _conversation_entries(),
        }

    def update_state(self, patch: dict[str, Any]) -> dict[str, Any]:
        updated = STATE.update_state(patch)
        if isinstance(patch, dict) and any(key in patch for key in {"permissions", "localIndexing"}):
            native_file_indexer.handle_state_change()
        return {
            "state": updated,
            "conversations": _conversation_entries(),
        }

    def create_conversation(self, title: str = "") -> dict[str, Any]:
        created = STATE.create_conversation(title)
        return {
            "conversation": created,
            "conversations": _conversation_entries(),
            "state": STATE.snapshot(),
        }

    def select_conversation(self, conversation_id: str) -> dict[str, Any]:
        state = STATE.snapshot()
        state.setdefault("conversation", {})["activeId"] = conversation_id
        state = STATE.save_state(state)
        return {"state": state, "activeConversationId": conversation_id, "conversations": _conversation_entries()}

    def _store_pending_plan(self, conversation_id: str, result: dict[str, Any], text: str) -> dict[str, Any] | None:
        pending = result.get("pendingPlan")
        if not isinstance(pending, dict):
            return None
        payload = dict(pending)
        payload["conversationId"] = conversation_id
        payload["query"] = text
        payload["createdAt"] = _utc_now_iso()
        return STATE.save_pending_plan(payload)

    def _pending_plan_exists(self, plan_id: str) -> bool:
        return STATE.get_pending_plan(plan_id) is not None

    def _execute_plan_steps(
        self,
        steps: list[dict[str, Any]],
    ) -> tuple[bool, str, list[dict[str, Any]], str, dict[str, Any] | None, list[dict[str, Any]]]:
        return self.executor_core.execute_plan_steps(
            steps=steps,
            state_factory=STATE.snapshot,
            execute_step=lambda capability, args, state, source: _execute_capability_with_preprocessing(
                capability,
                args,
                state,
                source=source,
            ),
            source="confirmed_plan",
        )

    def revise_conversation_plan(self, conversation_id: str, pending_plan_id: str, revision_text: str) -> dict[str, Any]:
        plan = STATE.get_pending_plan(pending_plan_id)
        if plan is None:
            safe_message = "Onay bekleyen plan bulunamadı."
            if conversation_id:
                STATE.append_message(
                    conversation_id,
                    "assistant",
                    safe_message,
                    {"provider": "local_planner", "error": True, "errorCode": "PENDING_PLAN_MISSING"},
                )
            return {
                "ok": True,
                "chatOk": False,
                "capability": "conversation.revise_plan",
                "conversationId": conversation_id,
                "assistantMessage": safe_message,
                "provider": "local_planner",
                "toolEvents": [],
                "error": {"code": "PENDING_PLAN_MISSING", "message": safe_message},
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }

        revised_payload = revise_plan_payload(plan, revision_text)
        active_conversation_id = conversation_id or str(plan.get("conversationId", "") or "")
        if revised_payload is None:
            question = "Planı güncellemek için değişikliği biraz daha açık yazar mısın?"
            _record_task_intelligence_outcome(
                "clarified",
                query=revision_text,
                intent=str(plan.get("intent", "") or "clarification"),
                capability=str(plan.get("capability", "") or ""),
                args=plan.get("steps", [{}])[0].get("args", {}) if isinstance(plan.get("steps"), list) and plan.get("steps") else {},
                conversation_id=active_conversation_id,
                question=question,
            )
            if active_conversation_id:
                STATE.append_message(
                    active_conversation_id,
                    "assistant",
                    question,
                    {
                        "provider": "local_planner",
                        "intent": str(plan.get("intent", "") or "clarification"),
                        "executionMode": "clarification",
                        "clarificationNeeded": True,
                        "clarificationQuestion": question,
                        "pendingPlanId": pending_plan_id,
                        "revisePlanSupported": True,
                    },
                )
            return {
                "ok": True,
                "chatOk": True,
                "capability": "conversation.revise_plan",
                "conversationId": active_conversation_id,
                "assistantMessage": question,
                "provider": "local_planner",
                "toolEvents": [],
                "intent": str(plan.get("intent", "") or "clarification"),
                "confidence": 0.0,
                "executionMode": "clarification",
                "needsConfirmation": True,
                "clarificationNeeded": True,
                "clarificationQuestion": question,
                "pendingPlanId": pending_plan_id,
                "revisePlanSupported": True,
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }

        revised_plan = STATE.revise_pending_plan(
            pending_plan_id,
            {
                "capability": revised_payload.get("capability", plan.get("capability", "")),
                "steps": revised_payload.get("steps", plan.get("steps", [])),
                "planPreview": revised_payload.get("planPreview", plan.get("planPreview", {})),
                "lastRevisionText": revision_text,
            },
        )
        if revised_plan is None:
            return {
                "ok": True,
                "chatOk": False,
                "capability": "conversation.revise_plan",
                "conversationId": active_conversation_id,
                "assistantMessage": "Plan güvenli şekilde güncellenemedi.",
                "provider": "local_planner",
                "toolEvents": [],
                "error": {"code": "PLAN_REVISION_FAILED", "message": "Plan güvenli şekilde güncellenemedi."},
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }

        summary = str(
            revised_payload.get("planPreview", {}).get("summary")
            if isinstance(revised_payload.get("planPreview"), dict)
            else "Plan güncellendi."
        ).strip() or "Plan güncellendi."
        _record_task_intelligence_outcome(
            "revised",
            query=str(plan.get("query", "") or ""),
            intent=str(plan.get("intent", "") or revised_plan.get("intent", "") or "task"),
            capability=str(plan.get("capability", "") or revised_plan.get("capability", "") or ""),
            args=revised_payload.get("steps", [{}])[0].get("args", {})
            if isinstance(revised_payload.get("steps"), list) and revised_payload.get("steps")
            else {},
            conversation_id=active_conversation_id,
            corrected_to=revision_text,
        )
        if active_conversation_id:
            STATE.append_message(
                active_conversation_id,
                "assistant",
                summary,
                {
                    "provider": "local_planner",
                    "intent": str(plan.get("intent", "") or revised_plan.get("intent", "") or "task"),
                    "confidence": _intent_confidence(plan.get("confidence"), 0.72),
                    "executionMode": "plan_revised",
                    "needsConfirmation": True,
                    "planPreview": revised_payload.get("planPreview", {}),
                    "pendingPlanId": pending_plan_id,
                    "revisePlanSupported": True,
                },
            )
        return {
            "ok": True,
            "chatOk": True,
            "capability": "conversation.revise_plan",
            "conversationId": active_conversation_id,
            "assistantMessage": summary,
            "provider": "local_planner",
            "toolEvents": [],
            "intent": str(plan.get("intent", "") or revised_plan.get("intent", "") or "task"),
            "confidence": _intent_confidence(plan.get("confidence"), 0.72),
            "executionMode": "plan_revised",
            "needsConfirmation": True,
            "planPreview": revised_payload.get("planPreview", {}),
            "pendingPlanId": pending_plan_id,
            "revisePlanSupported": True,
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def confirm_conversation_plan(self, conversation_id: str, pending_plan_id: str, approved: bool) -> dict[str, Any]:
        plan = STATE.get_pending_plan(pending_plan_id)
        if plan is None:
            safe_message = "Onay bekleyen plan bulunamadı."
            if conversation_id:
                STATE.append_message(
                    conversation_id,
                    "assistant",
                    safe_message,
                    {"provider": "local_planner", "error": True, "errorCode": "PENDING_PLAN_MISSING"},
                )
            return {
                "ok": True,
                "chatOk": False,
                "capability": "conversation.confirm_plan",
                "conversationId": conversation_id,
                "assistantMessage": safe_message,
                "provider": "local_planner",
                "toolEvents": [],
                "error": {"code": "PENDING_PLAN_MISSING", "message": safe_message},
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }

        active_conversation_id = conversation_id or str(plan.get("conversationId", "") or "")
        if not active_conversation_id:
            created = STATE.create_conversation("")
            active_conversation_id = str(created.get("id", "") or "")

        STATE.remove_pending_plan(pending_plan_id)
        intent = str(plan.get("intent", "") or "task")
        capability = str(plan.get("capability", "") or "")
        confidence = _intent_confidence(plan.get("confidence"), 0.7)
        if not approved:
            content = "İşlem iptal edildi."
            retrieval_metadata = _retrieval_result_metadata(
                plan.get("retrieval") if isinstance(plan.get("retrieval"), dict) else None
            )
            _record_task_intelligence_outcome(
                "rejected",
                query=str(plan.get("query", "") or ""),
                intent=intent,
                capability=capability,
                args=plan.get("steps", [{}])[0].get("args", {}) if isinstance(plan.get("steps"), list) and plan.get("steps") else {},
                conversation_id=active_conversation_id,
            )
            STATE.append_message(
                active_conversation_id,
                "assistant",
                content,
                {
                    "provider": "local_planner",
                    "intent": intent,
                    "confidence": confidence,
                    "executionMode": "plan_cancelled",
                    "pendingPlanId": pending_plan_id,
                    **retrieval_metadata,
                },
            )
            return {
                "ok": True,
                "chatOk": True,
                "capability": "conversation.confirm_plan",
                "conversationId": active_conversation_id,
                "assistantMessage": content,
                "provider": "local_planner",
                "toolEvents": [],
                "intent": intent,
                "confidence": confidence,
                "executionMode": "plan_cancelled",
                "needsConfirmation": False,
                "pendingPlanId": pending_plan_id,
                "revisePlanSupported": False,
                **retrieval_metadata,
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }

        steps = plan.get("steps", [])
        if not isinstance(steps, list):
            steps = []
        ok, content, tool_events, error_code, structured_result, artifacts = self._execute_plan_steps(steps)
        retrieval_metadata = _retrieval_result_metadata(
            plan.get("retrieval") if isinstance(plan.get("retrieval"), dict) else None
        )
        if ok:
            first_args = {}
            if steps and isinstance(steps[0], dict):
                first_args = dict(steps[0].get("args", {}) or {})
            _record_successful_route(
                str(plan.get("query", "") or ""),
                intent,
                capability,
                confidence,
                args=first_args,
                conversation_id=active_conversation_id,
                confirmed=True,
            )
            try:
                STATE.record_confirmed_plan_pattern(
                    query=str(plan.get("query", "") or ""),
                    intent=intent,
                    capability=capability,
                )
            except Exception:
                pass
            _record_task_intelligence_outcome(
                "correct",
                query=str(plan.get("query", "") or ""),
                intent=intent,
                capability=capability,
                args=first_args,
                conversation_id=active_conversation_id,
            )
        else:
            first_args = {}
            if steps and isinstance(steps[0], dict):
                first_args = dict(steps[0].get("args", {}) or {})
            _record_task_intelligence_outcome(
                "misrouted",
                query=str(plan.get("query", "") or ""),
                intent=intent,
                capability=capability,
                args=first_args,
                conversation_id=active_conversation_id,
            )
        STATE.append_message(
            active_conversation_id,
            "assistant",
            content,
                {
                    "provider": "local_tool" if ok else "local_planner",
                    "intent": intent,
                    "confidence": confidence,
                    "executionMode": "confirmed_plan",
                    "toolEvents": tool_events,
                    "structuredResult": structured_result,
                    "artifacts": artifacts,
                    **retrieval_metadata,
                },
            )
        payload: dict[str, Any] = {
            "ok": True,
            "chatOk": ok,
            "capability": "conversation.confirm_plan",
            "conversationId": active_conversation_id,
            "assistantMessage": content,
            "provider": "local_tool" if ok else "local_planner",
            "toolEvents": tool_events,
            "intent": intent,
            "confidence": confidence,
            "executionMode": "confirmed_plan",
            "needsConfirmation": False,
            "pendingPlanId": pending_plan_id,
            "revisePlanSupported": False,
            "structuredResult": structured_result,
            "artifacts": artifacts,
            **retrieval_metadata,
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }
        if not ok:
            payload["error"] = {"code": _safe_error_code(error_code), "message": content}
        return payload

    def send_conversation(
        self,
        conversation_id: str,
        text: str,
        title: str | None = None,
        selected_artifacts: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        state = STATE.snapshot()
        normalized_selected = STATE.normalize_selected_artifacts(
            selected_artifacts if isinstance(selected_artifacts, list) else STATE.get_selected_artifacts()
        )
        if normalized_selected:
            state = STATE.update_state({"composer": {"selectedArtifacts": normalized_selected}})

        def _clear_selected_artifacts() -> dict[str, Any]:
            return STATE.update_state({"composer": {"selectedArtifacts": []}})

        if not conversation_id:
            created = STATE.create_conversation(title or "")
            conversation_id = str(created["id"])
            state = STATE.snapshot()
        conversation = None
        for item in state.get("conversation", {}).get("items", []):
            if isinstance(item, dict) and str(item.get("id", "")) == conversation_id:
                conversation = item
                break
        if conversation is None:
            conversation = STATE.create_conversation(title or "")
            conversation_id = str(conversation["id"])
            state = STATE.snapshot()
        messages = conversation.get("messages", []) if isinstance(conversation, dict) else []
        message_list = messages if isinstance(messages, list) else []
        chat_context = []
        if isinstance(messages, list):
            for message in messages[-20:]:
                if isinstance(message, dict):
                    role = str(message.get("role", "user") or "user")
                    chat_context.append({"role": role, "text": str(message.get("text", "") or "")})
        user_extra = {"selectedArtifacts": normalized_selected} if normalized_selected else None
        STATE.append_message(conversation_id, "user", text, user_extra)
        active_plan = STATE.latest_pending_plan(conversation_id)
        if isinstance(active_plan, dict):
            active_plan_id = str(active_plan.get("id", "") or "").strip()
            if active_plan_id and _approve_like_request(text):
                response = self.confirm_conversation_plan(conversation_id, active_plan_id, True)
                cleared_state = _clear_selected_artifacts()
                response["state"] = cleared_state
                return response
            if active_plan_id and _cancel_like_request(text):
                response = self.confirm_conversation_plan(conversation_id, active_plan_id, False)
                cleared_state = _clear_selected_artifacts()
                response["state"] = cleared_state
                return response
            if active_plan_id and _looks_like_plan_revision(text):
                response = self.revise_conversation_plan(conversation_id, active_plan_id, text)
                cleared_state = _clear_selected_artifacts()
                response["state"] = cleared_state
                return response

        shared_prompt_context, shared_metadata, _shared_profile = self._shared_brain_context_for_conversation(
            text=text,
            conversation_id=conversation_id,
            enabled=not message_list,
        )
        state = STATE.snapshot()
        route_conversation = list(chat_context)
        if shared_prompt_context:
            route_conversation.insert(0, {"role": "system", "text": shared_prompt_context})
        result = self._execute_prompt_with_executor(
            source="conversation",
            conversation_id=conversation_id,
            task_id="",
            text=text,
            route_fn=lambda: _route_chat(
                state,
                route_conversation,
                text,
                conversation_id=conversation_id,
                selected_artifacts=normalized_selected,
            ),
        )
        self._record_executor_retrieval_usage(result, shared_metadata=shared_metadata)
        agent_status = _agent_status_from_result(result)
        if not result.get("ok"):
            error = result.get("error", "chat_failed")
            safe_message = str(result.get("message", "") or "").strip() or _safe_chat_error_message(error)
            STATE.append_message(
                conversation_id,
                "assistant",
                safe_message,
                {
                    "error": True,
                    "errorCode": _safe_error_code(error),
                    "provider": result.get("provider", ""),
                    "intent": result.get("intent", ""),
                    "confidence": result.get("confidence", 0.0),
                    "executionMode": result.get("executionMode", "failed"),
                    "clarificationNeeded": bool(result.get("clarificationNeeded", False)),
                    "clarificationQuestion": str(result.get("clarificationQuestion", "") or ""),
                    "permissionNeeded": bool(result.get("permissionNeeded", False)),
                    "permissionReason": str(result.get("permissionReason", "") or ""),
                    "revisePlanSupported": bool(result.get("revisePlanSupported", False)),
                    "retrievalUsed": bool(result.get("retrievalUsed", False)),
                    "retrievalStrategy": str(result.get("retrievalStrategy", "") or ""),
                    "retrievalSources": result.get("retrievalSources", []) if isinstance(result.get("retrievalSources"), list) else [],
                    "agentStatus": agent_status,
                    **shared_metadata,
                },
            )
            cleared_state = _clear_selected_artifacts()
            return {
                "ok": True,
                "chatOk": False,
                "capability": "conversation.send",
                "conversationId": conversation_id,
                "assistantMessage": safe_message,
                "provider": result.get("provider", ""),
                "toolEvents": result.get("toolEvents", []),
                "intent": result.get("intent", ""),
                "confidence": result.get("confidence", 0.0),
                "executionMode": result.get("executionMode", "failed"),
                "needsConfirmation": False,
                "planPreview": None,
                "pendingPlanId": None,
                "clarificationNeeded": bool(result.get("clarificationNeeded", False)),
                "clarificationQuestion": str(result.get("clarificationQuestion", "") or ""),
                "permissionNeeded": bool(result.get("permissionNeeded", False)),
                "permissionReason": str(result.get("permissionReason", "") or ""),
                "revisePlanSupported": bool(result.get("revisePlanSupported", False)),
                "retrievalUsed": bool(result.get("retrievalUsed", False)),
                "retrievalStrategy": str(result.get("retrievalStrategy", "") or ""),
                "retrievalSources": result.get("retrievalSources", []) if isinstance(result.get("retrievalSources"), list) else [],
                "agentStatus": agent_status,
                **shared_metadata,
                "error": {"code": _safe_error_code(error), "message": safe_message},
                "state": cleared_state,
                "conversations": _conversation_entries(),
                "runtime": {"agentStatus": agent_status},
            }

        content = str(result.get("content", "") or "").strip()
        if not content:
            content = "Mesaj işlendi ama içerik döndürülmedi."
        stored_plan = self._store_pending_plan(conversation_id, result, text)
        STATE.append_message(
            conversation_id,
            "assistant",
            content,
            {
                "provider": result.get("provider", ""),
                "intent": result.get("intent", ""),
                "confidence": result.get("confidence", 0.0),
                "executionMode": result.get("executionMode", "chat"),
                "structuredResult": result.get("structuredResult"),
                "artifacts": result.get("artifacts", []),
                "needsConfirmation": bool(result.get("needsConfirmation", False)),
                "planPreview": result.get("planPreview"),
                "pendingPlanId": stored_plan.get("id") if isinstance(stored_plan, dict) else None,
                "clarificationNeeded": bool(result.get("clarificationNeeded", False)),
                "clarificationQuestion": str(result.get("clarificationQuestion", "") or ""),
                "permissionNeeded": bool(result.get("permissionNeeded", False)),
                "permissionReason": str(result.get("permissionReason", "") or ""),
                "revisePlanSupported": bool(result.get("revisePlanSupported", False)),
                "retrievalUsed": bool(result.get("retrievalUsed", False)),
                "retrievalStrategy": str(result.get("retrievalStrategy", "") or ""),
                "retrievalSources": result.get("retrievalSources", []) if isinstance(result.get("retrievalSources"), list) else [],
                "agentStatus": agent_status,
                **shared_metadata,
            },
        )
        if title:
            STATE.update_conversation_title(conversation_id, title)
        cleared_state = _clear_selected_artifacts()
        response: dict[str, Any] = {
            "ok": True,
            "chatOk": True,
            "capability": "conversation.send",
            "conversationId": conversation_id,
            "assistantMessage": content,
            "provider": result.get("provider", ""),
            "toolEvents": result.get("toolEvents", []),
            "structuredResult": result.get("structuredResult"),
            "artifacts": result.get("artifacts", []),
            "intent": result.get("intent", ""),
            "confidence": result.get("confidence", 0.0),
            "executionMode": result.get("executionMode", "chat"),
            "needsConfirmation": bool(result.get("needsConfirmation", False)),
            "planPreview": result.get("planPreview"),
            "pendingPlanId": stored_plan.get("id") if isinstance(stored_plan, dict) else None,
            "clarificationNeeded": bool(result.get("clarificationNeeded", False)),
            "clarificationQuestion": str(result.get("clarificationQuestion", "") or ""),
            "permissionNeeded": bool(result.get("permissionNeeded", False)),
            "permissionReason": str(result.get("permissionReason", "") or ""),
            "revisePlanSupported": bool(result.get("revisePlanSupported", False)),
            "retrievalUsed": bool(result.get("retrievalUsed", False)),
            "retrievalStrategy": str(result.get("retrievalStrategy", "") or ""),
            "retrievalSources": result.get("retrievalSources", []) if isinstance(result.get("retrievalSources"), list) else [],
            "agentStatus": agent_status,
            **shared_metadata,
            "state": cleared_state,
            "conversations": _conversation_entries(),
            "runtime": {"agentStatus": agent_status},
        }
        return response

    def local_models_status(self) -> dict[str, Any]:
        state = STATE.snapshot()
        providers = _map_from(state.get("providers"))
        selected_runtime = self._local_runtime_family(state)
        default_model = ""
        if providers:
            default_model = str(
                _map_from(providers.get("local")).get("defaultModel", "")
                or _map_from(providers.get(selected_runtime)).get("defaultModel", "")
                or ""
            )
        runtime_statuses: dict[str, Any] = {}
        for provider_id in ("ollama", "lmstudio", "llamacpp"):
            _, runtime_status = _local_runtime_status_from_state(state, provider_id)
            runtime_statuses[provider_id] = runtime_status
        provider_id, client = self._selected_local_client(selected_runtime)
        selected_runtime_status = _map_from(runtime_statuses.get(provider_id))
        if client is None:
            return {
                "status": selected_runtime_status or runtime_statuses.get(provider_id, _ollama_status_payload(
                    base_url=str(_map_from(providers.get("ollama")).get("baseUrl", "") or "http://127.0.0.1:11434"),
                    default_model=default_model,
                )),
                "models": {
                    "ok": False,
                    "available": False,
                    "models": [],
                    "error": f"{provider_id}_client_unavailable",
                },
                "jobs": [],
                "selectedRuntime": provider_id,
                "selectedRuntimeStatus": selected_runtime_status,
                "runtimes": runtime_statuses,
                "defaultLocalModel": default_model,
            }
        models_payload = client.list_models() if hasattr(client, "list_models") else {"ok": False, "available": False, "models": [], "error": f"{provider_id}_list_unavailable"}
        jobs_payload = client.jobs() if hasattr(client, "jobs") else []
        return {
            "status": selected_runtime_status,
            "models": models_payload,
            "jobs": jobs_payload,
            "selectedRuntime": provider_id,
            "selectedRuntimeStatus": selected_runtime_status,
            "runtimes": runtime_statuses,
            "defaultLocalModel": default_model,
        }

    def local_models_list(self) -> dict[str, Any]:
        return self.local_models_status()

    def local_models_download(self, model: str) -> dict[str, Any]:
        provider_id, client = self._selected_local_client()
        if provider_id != "ollama":
            return {"ok": False, "error": "managed_download_only_supported_for_ollama"}
        if client is None:
            return {"ok": False, "error": "ollama_client_unavailable"}
        return client.pull_model(model)

    def local_models_remove(self, model: str) -> dict[str, Any]:
        provider_id, client = self._selected_local_client()
        if provider_id != "ollama":
            return {"ok": False, "error": "managed_remove_only_supported_for_ollama"}
        if client is None:
            return {"ok": False, "error": "ollama_client_unavailable"}
        return client.remove_model(model)

    def local_models_set_default(self, model: str) -> dict[str, Any]:
        selected_runtime = self._local_runtime_family()
        updated = STATE.update_state({
            "providers": {
                "active": selected_runtime,
                selected_runtime: {"defaultModel": model},
                "local": {"defaultModel": model, "runtimeFamily": selected_runtime},
            }
        })
        return {"ok": True, "state": updated, "defaultLocalModel": model}

    def local_model_job(self, job_id: str) -> dict[str, Any]:
        _, client = self._selected_local_client()
        if client is None:
            return {"ok": False, "error": "local_model_client_unavailable"}
        return {"ok": True, "job": client.job(job_id) if hasattr(client, "job") else None}

    def local_model_cancel(self, job_id: str) -> dict[str, Any]:
        _, client = self._selected_local_client()
        if client is None:
            return {"ok": False, "error": "local_model_client_unavailable"}
        return client.cancel_job(job_id) if hasattr(client, "cancel_job") else {"ok": False, "error": "local_model_cancel_unavailable"}

    def local_model_start(self, provider_id: str = "") -> dict[str, Any]:
        target_provider = provider_id.strip().lower() or self._local_runtime_family()
        _, client = self._selected_local_client(target_provider)
        if client is None:
            return {"ok": False, "error": f"{target_provider}_client_unavailable"}
        if not hasattr(client, "start_server"):
            return {"ok": False, "error": f"{target_provider}_start_unavailable"}
        return client.start_server()

    def _provider_catalog_payload(self) -> dict[str, Any]:
        state = STATE.snapshot()
        providers = _map_from(state.get("providers"))
        local_models = self.local_models_status()
        selected_runtime = str(local_models.get("selectedRuntime") or self._local_runtime_family(state)).strip() or "ollama"
        runtime_statuses = _map_from(local_models.get("runtimes"))
        provider_rows: list[dict[str, Any]] = []
        labels = {
            "openai": "OpenAI",
            "gemini": "Gemini",
            "anthropic": "Anthropic",
            "groq": "Groq",
            "custom": "Custom",
            "ollama": "Ollama",
            "lmstudio": "LM Studio",
            "llamacpp": "llama.cpp",
        }
        primary_cloud_ids = {"openai", "anthropic", "gemini"}
        advanced_provider_ids = {"groq", "custom", "lmstudio", "llamacpp"}
        for provider_id in ("openai", "gemini", "anthropic", "groq", "custom", "ollama", "lmstudio", "llamacpp"):
            cfg = _map_from(providers.get(provider_id))
            runtime_status = _map_from(runtime_statuses.get(provider_id))
            status_key, display_status = _simple_local_runtime_status(provider_id, runtime_status) if provider_id in {"ollama", "lmstudio", "llamacpp"} else (
                ("ready", "Bağlı") if _provider_is_configured_for_chat(state, provider_id) else ("not_connected", "Bağlı değil")
            )
            display_hint = (
                _simple_local_runtime_hint(provider_id, runtime_status, str(cfg.get("defaultModel", "") or ""))
                if provider_id in {"ollama", "lmstudio", "llamacpp"}
                else ("Kullanıma hazır." if _provider_is_configured_for_chat(state, provider_id) else "Bağlantı anahtarı ekleyebilirsin.")
            )
            provider_rows.append(
                {
                    "id": provider_id,
                    "label": labels.get(provider_id, provider_id),
                    "enabled": bool(cfg.get("enabled", False)),
                    "active": _current_provider(state) == provider_id or (provider_id == selected_runtime and _current_provider(state) == "local"),
                    "defaultModel": str(cfg.get("defaultModel", "") or ""),
                    "baseUrl": str(cfg.get("baseUrl", "") or ""),
                    "configured": _provider_is_configured_for_chat(state, provider_id),
                    "secretConfigured": bool(_provider_secret(provider_id)),
                    "validationStatus": str(cfg.get("validationStatus", "") or "idle"),
                    "lastValidatedAt": str(cfg.get("lastValidatedAt", "") or ""),
                    "binaryPath": str(cfg.get("binaryPath", "") or ""),
                    "modelPath": str(cfg.get("modelPath", "") or ""),
                    "autoStart": bool(cfg.get("autoStart", False)),
                    "managed": bool(cfg.get("managed", False)),
                    "runtimeStatus": runtime_status,
                    "displayStatus": display_status,
                    "displayStatusKey": status_key,
                    "displayHint": display_hint,
                }
            )
        local_summary_status, local_summary_label = _simple_local_runtime_status(selected_runtime, _map_from(runtime_statuses.get(selected_runtime)))
        local_summary = {
            "statusKey": local_summary_status,
            "status": local_summary_label,
            "hint": _simple_local_runtime_hint(
                selected_runtime,
                _map_from(runtime_statuses.get(selected_runtime)),
                str(local_models.get("defaultLocalModel", "") or ""),
            ),
            "selectedRuntime": selected_runtime,
            "managedDownloads": selected_runtime == "ollama",
        }
        return {
            "providers": provider_rows,
            "cloudProviders": [row for row in provider_rows if str(row.get("id", "")) in primary_cloud_ids],
            "advancedProviders": [row for row in provider_rows if str(row.get("id", "")) in advanced_provider_ids],
            "activeProvider": _current_provider(state),
            "routingPolicy": _routing_policy(state),
            "fallbackToCloud": bool(providers.get("fallbackToCloud", True)),
            "defaultLocalRuntime": str(providers.get("defaultLocalRuntime", "") or selected_runtime),
            "localModels": {
                **local_models,
                "summary": local_summary,
                "recommendedModels": list(RECOMMENDED_LOCAL_MODELS),
            },
        }

    def providers_catalog(self) -> dict[str, Any]:
        return {
            "ok": True,
            "result": self._provider_catalog_payload(),
            "state": STATE.snapshot(),
        }

    def providers_secret_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider_id = str(payload.get("providerId", "") or payload.get("provider_id", "") or "").strip().lower()
        if provider_id not in KNOWN_PROVIDER_IDS:
            return {"ok": False, "error": {"code": "UNKNOWN_PROVIDER", "message": "Bilinmeyen sağlayıcı."}}
        secret = str(payload.get("secret", "") or "").strip()
        if bool(payload.get("remove", False)) or not secret:
            _PROVIDER_SECRET_OVERRIDES.pop(provider_id, None)
            return {"ok": True, "providerId": provider_id, "removed": True}
        _PROVIDER_SECRET_OVERRIDES[provider_id] = secret
        return {"ok": True, "providerId": provider_id, "removed": False}

    def providers_update_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = STATE.snapshot()
        providers = _map_from(state.get("providers"))
        provider_id = str(payload.get("providerId", "") or payload.get("provider_id", "") or "").strip().lower()
        if provider_id and provider_id not in KNOWN_PROVIDER_IDS:
            return {"ok": False, "error": {"code": "UNKNOWN_PROVIDER", "message": "Bilinmeyen sağlayıcı."}}
        patch: dict[str, Any] = {"providers": {}}
        provider_patch = patch["providers"]
        if "activeProvider" in payload or "active_provider" in payload:
            active_provider = str(payload.get("activeProvider", "") or payload.get("active_provider", "") or "").strip().lower()
            if active_provider in KNOWN_PROVIDER_IDS:
                provider_patch["active"] = active_provider
        if "routingPolicy" in payload or "routing_policy" in payload:
            routing_policy = str(payload.get("routingPolicy", "") or payload.get("routing_policy", "") or "").strip().lower()
            if routing_policy in {"local_first", "cloud_fallback", "provider_lock"}:
                provider_patch["routingPolicy"] = routing_policy
        if "fallbackToCloud" in payload or "fallback_to_cloud" in payload:
            provider_patch["fallbackToCloud"] = bool(payload.get("fallbackToCloud", payload.get("fallback_to_cloud", True)))
        if "defaultLocalRuntime" in payload or "default_local_runtime" in payload:
            default_runtime = str(payload.get("defaultLocalRuntime", "") or payload.get("default_local_runtime", "") or "").strip().lower()
            if default_runtime in {"ollama", "lmstudio", "llamacpp"}:
                provider_patch["defaultLocalRuntime"] = default_runtime
                provider_patch["local"] = {"runtimeFamily": default_runtime}
        if provider_id:
            current_cfg = _map_from(providers.get(provider_id))
            next_cfg: dict[str, Any] = {}
            for source_key, target_key in (
                ("enabled", "enabled"),
                ("baseUrl", "baseUrl"),
                ("base_url", "baseUrl"),
                ("defaultModel", "defaultModel"),
                ("default_model", "defaultModel"),
                ("binaryPath", "binaryPath"),
                ("binary_path", "binaryPath"),
                ("modelPath", "modelPath"),
                ("model_path", "modelPath"),
                ("autoStart", "autoStart"),
                ("auto_start", "autoStart"),
                ("runtimeFamily", "runtimeFamily"),
                ("runtime_family", "runtimeFamily"),
            ):
                if source_key in payload:
                    next_cfg[target_key] = payload.get(source_key)
            if provider_id == "local":
                runtime_family = str(next_cfg.get("runtimeFamily", "") or current_cfg.get("runtimeFamily", "") or "").strip().lower()
                if runtime_family in {"ollama", "lmstudio", "llamacpp"}:
                    next_cfg["runtimeFamily"] = runtime_family
                    provider_patch["defaultLocalRuntime"] = runtime_family
            if "enabled" in next_cfg:
                next_cfg["enabled"] = bool(next_cfg["enabled"])
            if "autoStart" in next_cfg:
                next_cfg["autoStart"] = bool(next_cfg["autoStart"])
            if next_cfg:
                provider_patch[provider_id] = next_cfg
        saved = STATE.update_state(patch)
        return {
            "ok": True,
            "state": saved,
            "result": self._provider_catalog_payload(),
        }

    def providers_validate(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = STATE.snapshot()
        provider_id = str(payload.get("providerId", "") or payload.get("provider_id", "") or "").strip().lower()
        if provider_id == "local":
            provider_id = self._local_runtime_family(state)
        if provider_id not in KNOWN_PROVIDER_IDS:
            return {"ok": False, "error": {"code": "UNKNOWN_PROVIDER", "message": "Bilinmeyen sağlayıcı."}}
        validation: dict[str, Any]
        if provider_id == "ollama":
            client = self._ollama_client_from_state()
            models = client.list_models() if client is not None else {"ok": False, "error": "ollama_client_unavailable", "models": [], "available": False}
            validation = {
                "ok": bool(models.get("ok")),
                "providerId": provider_id,
                "models": models.get("models", []),
                "available": bool(models.get("available")),
                "error": str(models.get("error", "") or ""),
            }
        elif provider_id == "lmstudio":
            client = self._lmstudio_client_from_state()
            models = client.list_models() if client is not None else {"ok": False, "error": "lmstudio_client_unavailable", "models": [], "available": False}
            validation = {
                "ok": bool(models.get("ok")),
                "providerId": provider_id,
                "models": models.get("models", []),
                "available": bool(models.get("available")),
                "error": str(models.get("error", "") or ""),
            }
        elif provider_id == "llamacpp":
            client = self._llamacpp_client_from_state()
            models = client.list_models() if client is not None else {"ok": False, "error": "llamacpp_client_unavailable", "models": [], "available": False}
            validation = {
                "ok": bool(models.get("ok")),
                "providerId": provider_id,
                "models": models.get("models", []),
                "available": bool(models.get("available")),
                "error": str(models.get("error", "") or ""),
            }
        elif provider_id in {"openai", "groq", "custom"}:
            cfg = _provider_config(state, provider_id)
            api_key = str(cfg.get("apiKey", "") or "").strip()
            base_url = str(cfg.get("baseUrl", "") or "").strip().rstrip("/")
            url = f"{base_url}/models" if base_url.endswith("/v1") else f"{base_url}/v1/models"
            try:
                response = requests.get(
                    url,
                    headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
                    timeout=12,
                )
                payload_json = response.json() if response.text else {}
                models = payload_json.get("data", []) if isinstance(payload_json, dict) else []
                validation = {
                    "ok": response.ok,
                    "providerId": provider_id,
                    "models": models,
                    "available": response.ok,
                    "error": "" if response.ok else response.text[:240],
                }
            except requests.RequestException as exc:
                validation = {"ok": False, "providerId": provider_id, "models": [], "available": False, "error": str(exc)}
        elif provider_id == "anthropic":
            cfg = _provider_config(state, provider_id)
            api_key = str(cfg.get("apiKey", "") or "").strip()
            base_url = str(cfg.get("baseUrl", "") or "https://api.anthropic.com").strip().rstrip("/")
            try:
                response = requests.get(
                    f"{base_url}/v1/models",
                    headers={
                        "x-api-key": api_key,
                        "anthropic-version": "2023-06-01",
                    },
                    timeout=12,
                )
                payload_json = response.json() if response.text else {}
                validation = {
                    "ok": response.ok,
                    "providerId": provider_id,
                    "models": payload_json.get("data", []) if isinstance(payload_json, dict) else [],
                    "available": response.ok,
                    "error": "" if response.ok else response.text[:240],
                }
            except requests.RequestException as exc:
                validation = {"ok": False, "providerId": provider_id, "models": [], "available": False, "error": str(exc)}
        else:
            cfg = _provider_config(state, "gemini")
            api_key = str(cfg.get("apiKey", "") or "").strip()
            base_url = str(cfg.get("baseUrl", "") or "https://generativelanguage.googleapis.com").rstrip("/")
            try:
                response = requests.get(f"{base_url}/v1beta/models?key={api_key}", timeout=12)
                payload_json = response.json() if response.text else {}
                validation = {
                    "ok": response.ok,
                    "providerId": "gemini",
                    "models": payload_json.get("models", []) if isinstance(payload_json, dict) else [],
                    "available": response.ok,
                    "error": "" if response.ok else response.text[:240],
                }
            except requests.RequestException as exc:
                validation = {"ok": False, "providerId": "gemini", "models": [], "available": False, "error": str(exc)}
        validation_status = "ready" if validation.get("ok") else "error"
        STATE.update_state(
            {
                "providers": {
                    provider_id: {
                        "validationStatus": validation_status,
                        "lastValidatedAt": _utc_now_iso(),
                    }
                }
            }
        )
        return {
            "ok": bool(validation.get("ok")),
            "result": validation,
            "state": STATE.snapshot(),
            "catalog": self._provider_catalog_payload(),
        }

    def _first_available_ollama_model(self) -> str:
        try:
            models_payload = self.local_models_status()
            models_container = _map_from(models_payload.get("models"))
            models = [dict(item) for item in models_container.get("models", []) if isinstance(item, dict)]
            for item in models:
                name = str(item.get("name", "") or "").strip()
                if name:
                    return name
        except Exception:
            return ""
        return ""

    def _apply_brain_profile_preferences(self, result: BackendResult) -> None:
        try:
            if not result.ok or not isinstance(result.data, dict):
                return
            if _brain_profile_local_provider_hint(result.data) != "ollama":
                return
            state = STATE.snapshot()
            providers = _map_from(state.get("providers"))
            default_local_model = str(providers.get("defaultLocalModel", "") or "").strip()
            local_default = str(_map_from(providers.get("local")).get("defaultModel", "") or "").strip()
            if default_local_model or local_default:
                return
            preferred_model = self._first_available_ollama_model()
            if not preferred_model:
                return
            STATE.update_state(
                {
                    "providers": {
                        "active": "ollama",
                        "defaultLocalModel": preferred_model,
                        "local": {"defaultModel": preferred_model},
                        "ollama": {"defaultModel": preferred_model},
                    }
                }
            )
        except Exception:
            return

    def _apply_auth_result_truth(self, payload: dict[str, Any] | None) -> None:
        data = _map_from(payload)
        if not data:
            return
        user = _map_from(data.get("user"))
        tokens = _map_from(data.get("tokens"))
        subscription = _map_from(data.get("subscription"))
        account_patch: dict[str, Any] = {}
        email = str(user.get("email", "") or data.get("email", "") or "").strip()
        display_name = str(
            user.get("displayName", "")
            or user.get("name", "")
            or data.get("displayName", "")
            or data.get("display_name", "")
            or ""
        ).strip()
        access_token = str(
            tokens.get("accessToken", "")
            or tokens.get("access_token", "")
            or data.get("accessToken", "")
            or data.get("access_token", "")
            or ""
        ).strip()
        refresh_token = str(
            tokens.get("refreshToken", "")
            or tokens.get("refresh_token", "")
            or data.get("refreshToken", "")
            or data.get("refresh_token", "")
            or ""
        ).strip()
        if email:
            account_patch["email"] = email
        if display_name:
            account_patch["displayName"] = display_name
        if "hasAvatar" in user or "hasAvatar" in data:
            account_patch["hasAvatar"] = bool(user.get("hasAvatar", data.get("hasAvatar", False)))
        if "avatarVersion" in user or "avatarVersion" in data:
            try:
                account_patch["avatarVersion"] = max(0, int(user.get("avatarVersion", data.get("avatarVersion", 0)) or 0))
            except (TypeError, ValueError):
                account_patch["avatarVersion"] = 0
        if access_token:
            account_patch["accessToken"] = access_token
        if refresh_token:
            account_patch["refreshToken"] = refresh_token
        if account_patch:
            account_patch["onboardingCompleted"] = True
            STATE.update_state({"account": account_patch})
        if subscription:
            plan_code = str(subscription.get("planCode", "") or subscription.get("code", "") or "").strip()
            status = str(subscription.get("status", "") or "").strip()
            billing_patch: dict[str, Any] = {}
            if plan_code:
                billing_patch["subscriptionPlan"] = plan_code
            if status:
                billing_patch["subscriptionStatus"] = status
            if billing_patch:
                STATE.update_state({"billing": billing_patch})

    def _brain_profile_result(self) -> BackendResult:
        if not self._user_auth_ready():
            return BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=None,
                data=None,
                error="user_token_missing",
            )
        if not hasattr(self.backend, "brain_profile"):
            return BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=None,
                data=None,
                error="brain_profile_unavailable",
            )
        result = self.backend.brain_profile()
        self._apply_brain_profile_preferences(result)
        return result

    def _shared_brain_context_for_conversation(
        self,
        *,
        text: str,
        conversation_id: str,
        enabled: bool,
    ) -> tuple[str, dict[str, Any], dict[str, Any]]:
        empty_metadata = {
            "sharedRetrievalUsed": False,
            "sharedRetrievalCount": 0,
            "sharedRetrievalSources": [],
            "sharedModelSnapshot": {},
        }
        self._last_shared_brain_error_code = ""
        if not enabled or not self._user_auth_ready():
            return "", empty_metadata, {}
        brain_profile = self._brain_profile_result()
        profile_data = _map_from(brain_profile.data) if brain_profile.ok and isinstance(brain_profile.data, dict) else {}
        metadata = {
            **empty_metadata,
            "sharedModelSnapshot": _brain_profile_model_snapshot(profile_data),
        }
        if not hasattr(self.backend, "brain_retrieval_search"):
            self._last_shared_brain_error_code = "shared_brain_unavailable"
            return "", metadata, profile_data
        search_payload = {
            "query": str(text or "").strip(),
            "limit": 4,
            "conversationId": str(conversation_id or "").strip(),
        }
        search_result = self.backend.brain_retrieval_search(search_payload)
        self._log_backend_result("brain_retrieval_search", search_result)
        if not search_result.ok or not isinstance(search_result.data, dict):
            self._last_shared_brain_error_code = _safe_error_code(
                search_result.error or "shared_retrieval_failed"
            )
            return "", metadata, profile_data
        prompt_context, retrieval_metadata = _shared_brain_prompt_context(search_result.data)
        return prompt_context, {**metadata, **retrieval_metadata}, profile_data

    def backend_auth_me(self) -> dict[str, Any]:
        result = self.backend.auth_me()
        self._log_backend_result("auth_me", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def _hydrate_backend_truth(self) -> dict[str, Any]:
        auth_me = self.backend.auth_me()
        mobile_bootstrap = self.backend.mobile_bootstrap()
        health = self.backend.health()
        brain_profile = self._brain_profile_result() if auth_me.ok else BackendResult(
            ok=False,
            request_id=_request_id(),
            status_code=None,
            data=None,
            error="user_token_missing",
        )
        runtime_session = self.backend.runtime_session() if self._runtime_auth_ready() else BackendResult(
            ok=False,
            request_id=_request_id(),
            status_code=None,
            data=None,
            error="runtime_token_missing",
        )
        self._log_backend_result("auth_me", auth_me)
        self._log_backend_result("mobile_bootstrap", mobile_bootstrap)
        self._log_backend_result("health", health)
        self._log_backend_result("brain_profile", brain_profile)
        self._log_backend_result("runtime_session", runtime_session)
        if mobile_bootstrap.ok and isinstance(mobile_bootstrap.data, dict):
            self._sync_task_inbox_from_bootstrap_payload(mobile_bootstrap.data)
        ok = auth_me.ok and mobile_bootstrap.ok and health.ok
        return {
            "ok": ok,
            "authMe": auth_me.to_dict(),
            "mobileBootstrap": mobile_bootstrap.to_dict(),
            "health": health.to_dict(),
            "brainProfile": brain_profile.to_dict(),
            "runtimeSession": runtime_session.to_dict(),
            "controlPlane": self._control_plane_snapshot(),
            "state": STATE.snapshot(),
        }

    def backend_auth_login(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.auth_login(
            str(payload.get("email", "") or ""),
            str(payload.get("password", "") or ""),
        )
        self._log_backend_result("auth_login", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_login_failed", "Giriş yapılamadı."),
            }
        self._apply_auth_result_truth(result.data if isinstance(result.data, dict) else None)
        hydrated = self._hydrate_backend_truth()
        self._start_runtime_register_retry_if_needed()
        return {
            "ok": True,
            "hydrationOk": bool(hydrated.get("ok")),
            "result": result.to_dict(),
            "authMe": hydrated["authMe"],
            "mobileBootstrap": hydrated["mobileBootstrap"],
            "health": hydrated["health"],
            "brainProfile": hydrated["brainProfile"],
            "runtimeSession": hydrated["runtimeSession"],
            "controlPlane": hydrated["controlPlane"],
            "state": hydrated["state"],
            "runtime": self.status(),
        }

    def backend_auth_register(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.auth_register(
            str(payload.get("email", "") or ""),
            str(payload.get("password", "") or ""),
            str(payload.get("displayName", "") or payload.get("display_name", "") or "") or None,
        )
        self._log_backend_result("auth_register", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_register_failed", "Hesap oluşturulamadı."),
            }
        self._apply_auth_result_truth(result.data if isinstance(result.data, dict) else None)
        hydrated = self._hydrate_backend_truth()
        self._start_runtime_register_retry_if_needed()
        return {
            "ok": True,
            "hydrationOk": bool(hydrated.get("ok")),
            "result": result.to_dict(),
            "authMe": hydrated["authMe"],
            "mobileBootstrap": hydrated["mobileBootstrap"],
            "health": hydrated["health"],
            "brainProfile": hydrated["brainProfile"],
            "runtimeSession": hydrated["runtimeSession"],
            "controlPlane": hydrated["controlPlane"],
            "state": hydrated["state"],
            "runtime": self.status(),
        }

    def backend_auth_refresh(self) -> dict[str, Any]:
        result = self.backend.auth_refresh()
        self._log_backend_result("auth_refresh", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_refresh_failed", "Oturum yenilenemedi."),
            }
        self._apply_auth_result_truth(result.data if isinstance(result.data, dict) else None)
        hydrated = self._hydrate_backend_truth()
        self._start_runtime_register_retry_if_needed()
        return {
            "ok": True,
            "hydrationOk": bool(hydrated.get("ok")),
            "result": result.to_dict(),
            "authMe": hydrated["authMe"],
            "mobileBootstrap": hydrated["mobileBootstrap"],
            "health": hydrated["health"],
            "brainProfile": hydrated["brainProfile"],
            "runtimeSession": hydrated["runtimeSession"],
            "controlPlane": hydrated["controlPlane"],
            "state": hydrated["state"],
            "runtime": self.status(),
        }

    def backend_auth_logout(self) -> dict[str, Any]:
        self._invalidate_runtime_register_retry()
        if self._runtime_auth_ready():
            self._log_backend_result("runtime_disconnect", self.backend.disconnect_runtime())
        self._stop_runtime_websocket()
        result = self.backend.auth_logout()
        self._log_backend_result("auth_logout", result)
        health = self.backend.health()
        self._log_backend_result("health", health)
        return {
            "ok": True,
            "result": result.to_dict(),
            "authMe": BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=401,
                data=None,
                error="logged_out",
            ).to_dict(),
            "mobileBootstrap": BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=401,
                data=None,
                error="logged_out",
            ).to_dict(),
            "health": health.to_dict(),
            "brainProfile": BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=401,
                data=None,
                error="logged_out",
            ).to_dict(),
            "runtimeSession": BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=401,
                data=None,
                error="logged_out",
            ).to_dict(),
            "controlPlane": self._control_plane_snapshot(),
            "state": STATE.snapshot(),
            "runtime": self.status(),
        }

    def backend_auth_delete_account(self) -> dict[str, Any]:
        self._invalidate_runtime_register_retry()
        if self._runtime_auth_ready():
            self._log_backend_result("runtime_disconnect", self.backend.disconnect_runtime())
        self._stop_runtime_websocket()
        result = self.backend.auth_delete_account()
        self._log_backend_result("auth_delete_account", result)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "runtime": self.status(),
        }

    def backend_auth_update_profile(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.auth_update_profile(
            str(payload.get("displayName", "") or payload.get("display_name", "") or ""),
        )
        self._log_backend_result("auth_update_profile", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_profile_update_failed", "Profil güncellenemedi."),
            }
        hydrated = self._hydrate_backend_truth()
        return {
            "ok": True,
            "hydrationOk": bool(hydrated.get("ok")),
            "result": result.to_dict(),
            "authMe": hydrated["authMe"],
            "mobileBootstrap": hydrated["mobileBootstrap"],
            "health": hydrated["health"],
            "brainProfile": hydrated["brainProfile"],
            "runtimeSession": hydrated["runtimeSession"],
            "controlPlane": hydrated["controlPlane"],
            "state": hydrated["state"],
            "runtime": self.status(),
        }

    def backend_auth_change_password(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.auth_change_password(
            str(payload.get("currentPassword", "") or payload.get("current_password", "") or ""),
            str(payload.get("nextPassword", "") or payload.get("next_password", "") or ""),
        )
        self._log_backend_result("auth_change_password", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_password_change_failed", "Şifre değiştirilemedi."),
            }
        return {
            "ok": True,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "runtime": self.status(),
        }

    def backend_auth_avatar_upload(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.auth_avatar_upload(
            str(payload.get("mimeType", "") or payload.get("mime_type", "") or ""),
            str(payload.get("dataBase64", "") or payload.get("data_base64", "") or ""),
        )
        self._log_backend_result("auth_avatar_upload", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_avatar_upload_failed", "Profil fotoğrafı güncellenemedi."),
            }
        hydrated = self._hydrate_backend_truth()
        return {
            "ok": True,
            "hydrationOk": bool(hydrated.get("ok")),
            "result": result.to_dict(),
            "authMe": hydrated["authMe"],
            "mobileBootstrap": hydrated["mobileBootstrap"],
            "health": hydrated["health"],
            "brainProfile": hydrated["brainProfile"],
            "runtimeSession": hydrated["runtimeSession"],
            "controlPlane": hydrated["controlPlane"],
            "state": hydrated["state"],
            "runtime": self.status(),
        }

    def backend_auth_avatar_get(self) -> dict[str, Any]:
        result = self.backend.auth_avatar_get()
        self._log_backend_result("auth_avatar_get", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_avatar_get_failed", "Profil fotoğrafı alınamadı."),
            }
        return {
            "ok": True,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
        }

    def backend_auth_avatar_delete(self) -> dict[str, Any]:
        result = self.backend.auth_avatar_delete()
        self._log_backend_result("auth_avatar_delete", result)
        if not result.ok:
            return {
                "ok": False,
                "result": result.to_dict(),
                "error": _safe_auth_error(result, "auth_avatar_delete_failed", "Profil fotoğrafı silinemedi."),
            }
        hydrated = self._hydrate_backend_truth()
        return {
            "ok": True,
            "hydrationOk": bool(hydrated.get("ok")),
            "result": result.to_dict(),
            "authMe": hydrated["authMe"],
            "mobileBootstrap": hydrated["mobileBootstrap"],
            "health": hydrated["health"],
            "brainProfile": hydrated["brainProfile"],
            "runtimeSession": hydrated["runtimeSession"],
            "controlPlane": hydrated["controlPlane"],
            "state": hydrated["state"],
            "runtime": self.status(),
        }

    def backend_brain_profile(self) -> dict[str, Any]:
        result = self._brain_profile_result()
        self._log_backend_result("brain_profile", result)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def backend_brain_retrieval_search(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.backend, "brain_retrieval_search"):
            result = BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=None,
                data=None,
                error="brain_retrieval_unavailable",
            )
            return {
                "ok": False,
                "result": result.to_dict(),
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }
        request_payload = {
            "query": str(payload.get("query", "") or "").strip(),
            "limit": int(payload.get("limit", 4) or 4),
        }
        conversation_id = str(
            payload.get("conversationId", "") or payload.get("conversation_id", "") or ""
        ).strip()
        if conversation_id:
            request_payload["conversationId"] = conversation_id
        result = self.backend.brain_retrieval_search(request_payload)
        self._log_backend_result("brain_retrieval_search", result)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def backend_brain_knowledge_document(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.backend, "brain_knowledge_document"):
            result = BackendResult(
                ok=False,
                request_id=_request_id(),
                status_code=None,
                data=None,
                error="brain_publish_unavailable",
            )
            return {
                "ok": False,
                "result": result.to_dict(),
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }
        content = _safe_brain_snippet(payload.get("content"), limit=4000)
        request_payload = {
            "title": _safe_brain_snippet(payload.get("title"), limit=120),
            "content": content,
            "contentType": str(payload.get("contentType", "") or "text/plain").strip() or "text/plain",
            "source": str(payload.get("source", "") or "desktop_manual").strip() or "desktop_manual",
        }
        summary = _safe_brain_snippet(payload.get("summary"), limit=240)
        if summary:
            request_payload["summary"] = summary
        if not request_payload["title"]:
            request_payload["title"] = "Desktop shared note"
        result = self.backend.brain_knowledge_document(request_payload)
        self._log_backend_result("brain_knowledge_document", result)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def backend_mobile_bootstrap(self) -> dict[str, Any]:
        result = self.backend.mobile_bootstrap()
        self._log_backend_result("mobile_bootstrap", result)
        if result.ok and isinstance(result.data, dict):
            self._sync_task_inbox_from_bootstrap_payload(result.data)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def backend_tasks_list(self, payload: dict[str, Any]) -> dict[str, Any]:
        limit = int(payload.get("limit", 20) or 20)
        target_device_id = str(
            payload.get("targetDeviceId", "") or payload.get("target_device_id", "") or ""
        ).strip()
        status = str(payload.get("status", "") or "").strip()
        hydrate_details = bool(payload.get("hydrateDetails", False))
        result = self.backend.tasks_list(
            limit=limit,
            target_device_id=target_device_id,
            status=status,
        )
        self._log_backend_result("tasks_list", result)
        if result.ok and isinstance(result.data, dict):
            tasks = result.data.get("tasks", [])
            if isinstance(tasks, list):
                items = [
                    self._normalized_task_inbox_item(task)
                    for task in tasks
                    if isinstance(task, dict) and str(task.get("id", "") or "").strip()
                ]
                STATE.sync_task_inbox(items, last_synced_at=_utc_now_iso())
                if hydrate_details:
                    for task in items[: min(len(items), 12)]:
                        task_id = str(task.get("id", "") or "").strip()
                        if not task_id:
                            continue
                        detail = self.backend.task_detail(task_id)
                        self._log_backend_result("task_detail", detail)
                        if detail.ok and isinstance(detail.data, dict):
                            self._sync_task_inbox_item_from_detail(detail.data)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def backend_task_detail(self, task_id: str) -> dict[str, Any]:
        result = self.backend.task_detail(task_id)
        self._log_backend_result("task_detail", result)
        if result.ok and isinstance(result.data, dict):
            self._sync_task_inbox_item_from_detail(result.data)
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def backend_task_approval(self, task_id: str, approved: bool, notes: str = "") -> dict[str, Any]:
        result = self.backend.task_approval(task_id, approved, notes or None)
        self._log_backend_result("task_approval", result)
        if result.ok and isinstance(result.data, dict):
            task = result.data.get("task", {})
            if isinstance(task, dict):
                STATE.upsert_task_inbox_item(
                    self._normalized_task_inbox_item(task),
                    last_synced_at=_utc_now_iso(),
                )
        return {
            "ok": result.ok,
            "result": result.to_dict(),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def _save_mcp_server_configs(self, servers: list[dict[str, Any]]) -> dict[str, Any]:
        state = STATE.snapshot()
        skills = state.setdefault("skills", {})
        if not isinstance(skills, dict):
            skills = {}
            state["skills"] = skills
        skills["mcpServers"] = servers
        return STATE.save_state(state)

    def mcp_server_upsert(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = STATE.snapshot()
        current = state.get("skills", {}).get("mcpServers", [])
        current = [dict(item) for item in current if isinstance(item, dict)]
        try:
            normalized = mcp_runtime.normalize_server_config(payload, existing_id=str(payload.get("id", "") or ""))
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "MCP_SERVER_INVALID")
            message = str(getattr(exc, "message", "") or "MCP sunucu yapılandırması geçerli değil.")
            return {
                "ok": False,
                "error": {"code": code, "message": message},
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }
        updated: list[dict[str, Any]] = []
        found = False
        for item in current:
            if str(item.get("id", "") or "").strip() == normalized["id"]:
                updated.append(normalized)
                found = True
            else:
                updated.append(item)
        if not found:
            updated.append(normalized)
        saved = self._save_mcp_server_configs(updated)
        mcp_status = mcp_runtime.refresh_mcp_runtime(saved)
        return {
            "ok": True,
            "server": normalized,
            "mcpStatus": mcp_status,
            "state": saved,
            "conversations": _conversation_entries(),
        }

    def mcp_server_remove(self, server_id: str) -> dict[str, Any]:
        target_server_id = str(server_id or "").strip()
        state = STATE.snapshot()
        current = state.get("skills", {}).get("mcpServers", [])
        current = [dict(item) for item in current if isinstance(item, dict)]
        updated = [item for item in current if str(item.get("id", "") or "").strip() != target_server_id]
        saved = self._save_mcp_server_configs(updated)
        mcp_status = mcp_runtime.refresh_mcp_runtime(saved)
        return {
            "ok": True,
            "removed": bool(len(updated) != len(current)),
            "serverId": target_server_id,
            "mcpStatus": mcp_status,
            "state": saved,
            "conversations": _conversation_entries(),
        }

    def mcp_refresh(self) -> dict[str, Any]:
        state = STATE.snapshot()
        mcp_status = mcp_runtime.refresh_mcp_runtime(state)
        return {
            "ok": True,
            "mcpStatus": mcp_status,
            "state": state,
            "conversations": _conversation_entries(),
        }

    def skill_refresh(self) -> dict[str, Any]:
        state = STATE.snapshot()
        skill_status = skill_runtime.refresh_skill_runtime(state)
        return {
            "ok": True,
            "skillStatus": skill_status,
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def skill_list(self, *, refresh: bool = False) -> dict[str, Any]:
        state = STATE.snapshot()
        skill_status = skill_runtime.list_skill_runtime(state, refresh=refresh)
        return {
            "ok": True,
            "skillStatus": skill_status,
            "skills": skill_status.get("skills", []),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def skill_set_enabled(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        skill_status = skill_runtime.set_skill_enabled(skill_id, enabled)
        return {
            "ok": True,
            "skillStatus": skill_status,
            "skillId": skill_id,
            "enabled": enabled,
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def skill_clone(self, skill_id: str) -> dict[str, Any]:
        cloned = skill_runtime.clone_skill(skill_id)
        return {
            "ok": True,
            "skillStatus": cloned.get("skillStatus", {}),
            "skill": cloned.get("skill", {}),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def skill_upsert_local(self, payload: dict[str, Any]) -> dict[str, Any]:
        saved = skill_runtime.upsert_local_skill(payload)
        return {
            "ok": True,
            "skillStatus": saved.get("skillStatus", {}),
            "skill": saved.get("skill", {}),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def skill_remove_local(self, skill_id: str) -> dict[str, Any]:
        removed = skill_runtime.remove_local_skill(skill_id)
        return {
            "ok": True,
            "skillStatus": removed.get("skillStatus", {}),
            "removed": bool(removed.get("removed", False)),
            "skillId": skill_id,
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def skill_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = STATE.snapshot()
        skill_id = str(payload.get("skillId", "") or payload.get("skill_id", "") or "").strip()
        skill_payload = payload.get("payload", {})
        skill_payload = dict(skill_payload) if isinstance(skill_payload, dict) else {}
        tool_result, events = _execute_capability_with_preprocessing(
            "run_skill",
            {
                "skillId": skill_id,
                "payload": skill_payload,
                "_confirmed": bool(payload.get("_confirmed", False)),
            },
            state,
            source="skill_runtime",
        )
        if tool_result.get("ok"):
            return {
                "ok": True,
                "result": tool_result,
                "events": events,
                "artifacts": tool_result.get("artifacts", []),
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }
        error = tool_result.get("error") if isinstance(tool_result.get("error"), dict) else {}
        return {
            "ok": False,
            "error": error or {
                "code": "TOOL_EXECUTION_FAILED",
                "message": "Skill guvenli sekilde tamamlanamadi.",
            },
            "events": events,
            "artifacts": tool_result.get("artifacts", []),
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def mcp_tools_list(self, *, refresh: bool = False) -> dict[str, Any]:
        state = STATE.snapshot()
        mcp_status = mcp_runtime.list_mcp_tools(state, refresh=refresh)
        return {
            "ok": True,
            "mcpStatus": mcp_status,
            "tools": mcp_status.get("tools", []),
            "state": state,
            "conversations": _conversation_entries(),
        }

    def mcp_tool_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        state = STATE.snapshot()
        server_id = str(payload.get("serverId", "") or payload.get("server_id", "") or "").strip()
        tool_name = str(payload.get("toolName", "") or payload.get("tool_name", "") or "").strip()
        arguments = payload.get("arguments", {})
        arguments = dict(arguments) if isinstance(arguments, dict) else {}
        metadata = mcp_runtime.mcp_tool_metadata(server_id, tool_name, state)
        tool_payload = {
            "serverId": server_id,
            "toolName": tool_name,
            "arguments": arguments,
            "_readOnlyHint": bool(metadata.get("readOnly", False)) if isinstance(metadata, dict) else False,
            "_confirmed": bool(payload.get("_confirmed", False)),
        }
        tool_result = run_capability("mcp_call_tool", tool_payload, state)
        event = safe_tool_event("mcp_call_tool", tool_result, source="mcp_runtime")
        if tool_result.get("ok"):
            structured = tool_result.get("result")
            return {
                "ok": True,
                "assistantMessage": str(tool_result.get("output", "") or "").strip(),
                "toolEvents": [event],
                "structuredResult": structured if isinstance(structured, dict) else {"kind": "mcp_call_tool"},
                "artifacts": tool_result.get("artifacts", []),
                "state": STATE.snapshot(),
                "conversations": _conversation_entries(),
            }
        return {
            "ok": False,
            "error": tool_result.get(
                "error",
                {"code": "TOOL_EXECUTION_FAILED", "message": "MCP aracı güvenli şekilde tamamlanamadı."},
            ),
            "toolEvents": [event],
            "state": STATE.snapshot(),
            "conversations": _conversation_entries(),
        }

    def pairing_create_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.pairing_create_session(payload)
        self._log_backend_result("pairing_create_session", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def pairing_claim_session(self, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.pairing_claim_session(session_id, payload)
        self._log_backend_result("pairing_claim_session", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def pairing_get_session(self, session_id: str) -> dict[str, Any]:
        result = self.backend.pairing_get_session(session_id)
        self._log_backend_result("pairing_get_session", result)
        registration: dict[str, Any] | None = None
        if result.ok and isinstance(result.data, dict) and str(result.data.get("status", "") or "") == "claimed":
            registration = self.ensure_runtime_registered()
            self._start_runtime_register_retry_if_needed()
        return {"ok": result.ok, "result": result.to_dict(), "registration": registration}

    def register_runtime(self, payload: dict[str, Any]) -> dict[str, Any]:
        identity_error = self._runtime_register_identity_error()
        if identity_error is not None:
            if identity_error.get("code") == "RUNTIME_REGISTER_INVALID_IDENTITY":
                self._repair_invalid_runtime_identity(identity_error)
            else:
                self._runtime_state_patch(
                    lifecycle_state="offline",
                    ready=False,
                    websocket_connected=False,
                    error_code=str(identity_error.get("code", "") or "").lower(),
                )
            return {"ok": False, "error": identity_error}

        register_payload = self._runtime_register_payload()
        if register_payload is None:
            error = {
                "code": "RUNTIME_AUTH_MISSING",
                "message": "Runtime eşleştirmesi tamamlanmamış.",
            }
            self._runtime_state_patch(
                lifecycle_state="offline",
                ready=False,
                websocket_connected=False,
                error_code="runtime_auth_missing",
            )
            return {"ok": False, "error": error}

        result = self.backend.register_runtime(register_payload)
        self._log_backend_result("runtime_register", result)
        if result.ok:
            self._apply_runtime_registration_result(result)
            self._mark_runtime_connecting(result.x_request_id or result.request_id)
            self._connect_runtime_transport()
            self._prime_runtime_task_delivery()
            return {"ok": True, "result": result.to_dict()}
        self._runtime_state_patch(
            lifecycle_state="offline",
            ready=False,
            websocket_connected=False,
            error_code=_safe_error_code(result.error or "runtime_register_failed"),
            x_request_id=result.x_request_id or result.request_id,
        )
        return {"ok": False, "result": result.to_dict()}

    def ensure_runtime_registered(self) -> dict[str, Any]:
        identity_error = self._runtime_register_identity_error()
        if identity_error is not None:
            if identity_error.get("code") == "RUNTIME_REGISTER_INVALID_IDENTITY":
                self._repair_invalid_runtime_identity(identity_error)
            else:
                self._runtime_state_patch(
                    lifecycle_state="offline",
                    ready=False,
                    websocket_connected=False,
                    error_code=str(identity_error.get("code", "") or "").lower(),
                )
            return {"ok": False, "error": identity_error}

        payload = self._runtime_register_payload()
        if payload is None:
            return {"ok": False, "error": {"code": "RUNTIME_AUTH_MISSING", "message": "Runtime eşleştirmesi tamamlanmamış."}}

        if self._runtime_ws_connected:
            return {
                "ok": True,
                "register": None,
                "heartbeat": None,
                "transport": {"mode": "websocket", "connected": True},
            }

        self._runtime_state_patch(
            lifecycle_state="claimed_registering",
            ready=False,
            websocket_connected=False,
            error_code="",
        )
        register = self.backend.register_runtime(payload)
        self._log_backend_result("runtime_register", register)
        if not register.ok:
            self._runtime_state_patch(
                lifecycle_state="offline",
                ready=False,
                websocket_connected=False,
                error_code=_safe_error_code(register.error or "runtime_register_failed"),
                x_request_id=register.x_request_id or register.request_id,
            )
            return {
                "ok": False,
                "register": register.to_dict(),
                "heartbeat": None,
                "transport": {"mode": "unavailable", "connected": False},
            }

        self._apply_runtime_registration_result(register)
        self._mark_runtime_connecting(register.x_request_id or register.request_id)
        connected, heartbeat = self._connect_runtime_transport()
        self._prime_runtime_task_delivery()
        return {
            "ok": bool(register.ok and (connected or (heartbeat.ok if heartbeat else False))),
            "register": register.to_dict(),
            "heartbeat": heartbeat.to_dict() if heartbeat else None,
            "transport": {
                "mode": "websocket" if connected else "heartbeat",
                "connected": connected,
            },
        }

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        heartbeat_payload = dict(payload)
        if not str(heartbeat_payload.get("status", "") or "").strip():
            heartbeat_payload["status"] = "online"
        if not heartbeat_payload.get("capabilities"):
            heartbeat_payload["capabilities"] = _runtime_advertised_capabilities()
        result = self.backend.heartbeat(heartbeat_payload)
        self._log_backend_result("runtime_heartbeat", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def runtime_session(self) -> dict[str, Any]:
        result = self.backend.runtime_session()
        self._log_backend_result("runtime_session", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def runtime_tasks_assigned(self) -> dict[str, Any]:
        result = self.backend.runtime_tasks_assigned()
        self._log_backend_result("runtime_tasks_assigned", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def runtime_task_status(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.runtime_task_status(task_id, payload)
        self._log_backend_result("runtime_task_status", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def runtime_task_artifacts(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        result = self.backend.runtime_task_artifacts(task_id, payload)
        self._log_backend_result("runtime_task_artifacts", result)
        return {"ok": result.ok, "result": result.to_dict()}

    def _report_runtime_task_status(self, task_id: str, payload: dict[str, Any]) -> BackendResult | None:
        terminal_status = str(payload.get("status", "") or "").strip().lower()
        if self._send_runtime_socket_message({"type": "task.update", "taskId": task_id, "body": payload}):
            self._sync_task_inbox_status(task_id, payload)
            if terminal_status in {"completed", "failed", "canceled"}:
                self._remember_terminal_assigned_task(task_id)
                self._resync_terminal_remote_task(task_id)
            return BackendResult(ok=True, request_id=_request_id(), status_code=200, data={"ok": True, "transport": "websocket"})
        result = self.backend.runtime_task_status(task_id, payload)
        if result.ok:
            self._sync_task_inbox_status(task_id, payload)
            if terminal_status in {"completed", "failed", "canceled"}:
                self._remember_terminal_assigned_task(task_id)
                self._resync_terminal_remote_task(task_id)
        return result

    def _report_runtime_task_artifacts(self, task_id: str, artifacts: list[dict[str, Any]]) -> BackendResult | None:
        if not artifacts:
            return None
        if self._send_runtime_socket_message({"type": "task.artifacts", "taskId": task_id, "artifacts": artifacts}):
            self._sync_task_inbox_artifacts(task_id, artifacts)
            return BackendResult(ok=True, request_id=_request_id(), status_code=200, data={"ok": True, "transport": "websocket"})
        result = self.backend.runtime_task_artifacts(task_id, {"artifacts": artifacts})
        if result.ok:
            self._sync_task_inbox_artifacts(task_id, artifacts)
        return result

    def _remove_remote_task_local_link(self, task_id: str) -> None:
        link = STATE.get_remote_task_link(task_id)
        if not isinstance(link, dict):
            return
        pending_plan_id = str(link.get("pendingPlanId", "") or "").strip()
        if pending_plan_id:
            STATE.remove_pending_plan(pending_plan_id)
        STATE.remove_remote_task_link(task_id)

    def _discard_remote_pending_task_locally(self, task_id: str, message: str = "İşlem iptal edildi.") -> None:
        link = STATE.get_remote_task_link(task_id)
        conversation_id = ""
        if isinstance(link, dict):
            conversation_id = str(link.get("conversationId", "") or "").strip()
            self._remove_remote_task_local_link(task_id)
        if conversation_id:
            STATE.append_message(
                conversation_id,
                "assistant",
                message,
                {"provider": "local_planner", "executionMode": "plan_cancelled"},
            )

    def _cancel_remote_pending_task(self, task_id: str) -> None:
        link = STATE.get_remote_task_link(task_id)
        if isinstance(link, dict):
            plan_id = str(link.get("pendingPlanId", "") or "").strip()
            conversation_id = str(link.get("conversationId", "") or "").strip()
            if plan_id:
                try:
                    self.confirm_conversation_plan(conversation_id, plan_id, False)
                except Exception:
                    pass
                STATE.remove_pending_plan(plan_id)
            STATE.remove_remote_task_link(task_id)
        STATE.upsert_task_inbox_item(
            {
                "id": task_id,
                "status": "canceled",
                "summary": "Görev iptal edildi.",
                "approvalRequest": {},
                "updatedAt": _utc_now_iso(),
            },
            last_synced_at=_utc_now_iso(),
        )

    def _resume_remote_task_after_approval(self, task_id: str, approved: bool) -> dict[str, Any]:
        if not approved:
            self._cancel_remote_pending_task(task_id)
            return {"taskId": task_id, "ok": True, "status": "canceled"}

        link = STATE.get_remote_task_link(task_id)
        if not isinstance(link, dict):
            self._runtime_diag("task_approval_missing_link", task_id=task_id)
            report = self._report_runtime_task_status(
                task_id,
                {
                    "status": "failed",
                    "message": "Onay bağlantısı bulunamadı. Görev güvenli şekilde durduruldu.",
                    "summary": "Onay bağlantısı bulunamadı.",
                    "approvalRequest": {},
                    "artifacts": [],
                    "error": "pending_link_missing",
                },
            )
            return {"taskId": task_id, "ok": False, "status": "failed", "report": report.to_dict() if report else None}

        pending_plan_id = str(link.get("pendingPlanId", "") or "").strip()
        conversation_id = str(link.get("conversationId", "") or "").strip()
        if not pending_plan_id:
            self._runtime_diag("task_approval_missing_plan", task_id=task_id)
            STATE.remove_remote_task_link(task_id)
            report = self._report_runtime_task_status(
                task_id,
                {
                    "status": "failed",
                    "message": "Onay bekleyen yerel plan bulunamadı. Görev güvenli şekilde durduruldu.",
                    "summary": "Onay bekleyen yerel plan bulunamadı.",
                    "approvalRequest": {},
                    "artifacts": [],
                    "error": "pending_plan_missing",
                },
            )
            return {"taskId": task_id, "ok": False, "status": "failed", "report": report.to_dict() if report else None}

        self._set_runtime_task_heartbeat(False, "busy", task_id)
        running = self._report_runtime_task_status(
            task_id,
            {
                "status": "running",
                "message": "Onay alındı, görev sürdürülüyor.",
                "approvalRequest": {},
                "artifacts": [],
            },
        )
        if running is None or not running.ok:
            self._set_runtime_task_heartbeat(False, "idle")
            return {"taskId": task_id, "ok": False, "status": "running_rejected", "report": running.to_dict() if running else None}

        local_result = self.confirm_conversation_plan(conversation_id, pending_plan_id, True)
        result = self._report_runtime_task_terminal_result(
            task_id,
            local_result,
            dispatched_via_websocket=False,
            separate_artifacts=True,
        )
        self._set_runtime_task_heartbeat(False, "idle")
        STATE.remove_remote_task_link(task_id)
        return result

    def _remote_task_route_decision(self, payload: dict[str, Any]) -> dict[str, Any]:
        route_decision = payload.get("routeDecision") or payload.get("routingDecision")
        if not isinstance(route_decision, dict):
            metadata = payload.get("metadata", {})
            metadata = metadata if isinstance(metadata, dict) else {}
            route_decision = metadata.get("routeDecision") or metadata.get("routingDecision")
        return dict(route_decision) if isinstance(route_decision, dict) else {}

    def _remote_task_capabilities(self, task: dict[str, Any], payload: dict[str, Any]) -> set[str]:
        route_decision = self._remote_task_route_decision(payload)
        raw = route_decision.get("capabilities")
        if not isinstance(raw, list) or not raw:
            raw = task.get("requestedCapabilities")
        if not isinstance(raw, list):
            raw = []
        return {_canonical_capability_name(item) for item in raw if str(item or "").strip()}

    def _remote_task_email_recipients(
        self,
        task: dict[str, Any],
        payload: dict[str, Any],
        prompt: str,
        route_decision: dict[str, Any],
    ) -> list[str]:
        recipients: list[str] = []
        sources: list[Any] = [
            route_decision.get("to"),
            route_decision.get("recipient"),
            route_decision.get("recipients"),
            payload.get("to"),
            payload.get("recipient"),
            payload.get("recipients"),
            task.get("to"),
            task.get("recipient"),
            task.get("recipients"),
        ]
        for source in sources:
            if isinstance(source, list):
                for item in self._string_list(source):
                    if item not in recipients:
                        recipients.append(item)
                continue
            text = str(source or "").strip()
            if not text:
                continue
            for address in _extract_email_addresses_from_text(text):
                if address not in recipients:
                    recipients.append(address)
        for address in _extract_email_addresses_from_text(prompt):
            if address not in recipients:
                recipients.append(address)
        return recipients

    def _remote_task_steps_from_route(
        self,
        task: dict[str, Any],
        prompt: str,
        capabilities: set[str],
        route_decision: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        decision = dict(route_decision or {})
        decision_route = str(decision.get("route", "") or "").strip()
        decision_reason = str(decision.get("reason", "") or "").strip()
        decision_privacy = str(decision.get("privacyClass", "") or "").strip()
        if decision_route == "desktop_runtime" and decision:
            quantum_requested = bool(capabilities.intersection(REMOTE_QUANTUM_CAPABILITIES))
            if quantum_requested:
                title = self._truncate_text(
                    task.get("title", "") or decision_reason or "Elyan Quantum Deney Raporu",
                    120,
                )
                steps = [
                    {
                        "capability": "quantum_model_problem",
                        "args": {"prompt": prompt, "problemClass": "optimization"},
                        "description": "Problem QUBO/Ising formuna dönüştürülecek.",
                    },
                    {
                        "capability": "quantum_run_experiment",
                        "args": {"prompt": prompt, "algorithm": "qaoa", "shots": 1024},
                        "description": "QAOA/VQE simulator demo deneyi yürütülecek.",
                    },
                    {
                        "capability": "quantum_compare_classical",
                        "args": {"prompt": prompt},
                        "description": "Klasik baseline ile karşılaştırmalı metrik üretilecek.",
                    },
                    {
                        "capability": "quantum_generate_report",
                        "args": {"prompt": prompt, "title": title},
                        "description": "Teknik quantum deney raporu hazırlanacak.",
                    },
                ]
                return steps, {
                    "summary": decision_reason
                    or "Backend routeDecision kararına göre quantum deney pipeline'ı desktop runtime üzerinde yürütülecek.",
                    "steps": steps,
                    "privacyClass": decision_privacy or "public_text",
                }

            topic = self._truncate_text(_research_topic_from_text(prompt), 120)
            recipients = self._remote_task_email_recipients(task, task.get("payload", {}), prompt, decision)
            subject = f"{topic[:80]} hakkında notlar"
            steps: list[dict[str, Any]] = []
            if "web_research" in capabilities:
                steps.append(
                    {
                        "capability": "web_research",
                        "args": {"query": topic},
                        "description": f"{topic} hakkında web araştırması yapılacak.",
                    }
                )
            if "email_draft" in capabilities:
                steps.append(
                    {
                        "capability": "email_draft",
                        "args": {
                            "to": recipients,
                            "subject": subject,
                            "topic": topic,
                            "prompt": prompt,
                        },
                        "description": f"{', '.join(recipients) if recipients else 'alıcı'} için e-posta taslağı hazırlanacak.",
                    }
                )
            if "email_send" in capabilities:
                steps.append(
                    {
                        "capability": "email_send",
                        "args": {"to": recipients, "subject": subject},
                        "description": f"{', '.join(recipients) if recipients else 'alıcı'} adresine e-posta gönderilecek.",
                    }
                )
            if steps:
                privacy_class = decision_privacy or ("side_effect" if "email_send" in capabilities else "public_text")
                return steps, {
                    "summary": decision_reason
                    or "Backend routeDecision kararına göre desktop görevi yürütülecek.",
                    "steps": steps,
                    "privacyClass": privacy_class,
                }

        routed = route_text_to_tool(prompt)
        routed_steps = _plan_steps_from_routed_task(routed) if routed is not None else []
        steps = [dict(step) for step in routed_steps if isinstance(step, dict)]
        routed_capabilities = {
            _canonical_capability_name(step.get("capability"))
            for step in steps
            if isinstance(step, dict)
        }
        email_requested = bool(capabilities.intersection({"email_draft", "email_send"}))
        quantum_requested = bool(capabilities.intersection(REMOTE_QUANTUM_CAPABILITIES))
        if quantum_requested:
            fallback_steps = [
                {
                    "capability": "quantum_model_problem",
                    "args": {"prompt": prompt, "problemClass": "optimization"},
                    "description": "Problem QUBO/Ising formuna dönüştürülecek.",
                },
                {
                    "capability": "quantum_run_experiment",
                    "args": {"prompt": prompt, "algorithm": "qaoa", "shots": 1024},
                    "description": "QAOA/VQE simulator demo deneyi yürütülecek.",
                },
                {
                    "capability": "quantum_compare_classical",
                    "args": {"prompt": prompt},
                    "description": "Klasik baseline ile karşılaştırmalı metrik üretilecek.",
                },
                {
                    "capability": "quantum_generate_report",
                    "args": {"prompt": prompt, "title": title if (title := str(task.get("title", "") or "").strip()) else "Elyan Quantum Deney Raporu"},
                    "description": "Teknik quantum deney raporu hazırlanacak.",
                },
            ]
            return fallback_steps, {
                "summary": "Backend routing kararına göre quantum deney pipeline'ı desktop runtime üzerinde yürütülecek.",
                "steps": fallback_steps,
                "privacyClass": "public_text",
            }
        if steps and (not email_requested or bool(routed_capabilities.intersection({"email_draft", "email_send"}))):
            return steps, dict(routed.plan_preview) if routed is not None and isinstance(routed.plan_preview, dict) else {}

        recipients = _extract_email_addresses_from_text(prompt)
        subject = f"{_research_topic_from_text(prompt)[:80]} hakkında notlar"
        fallback_steps: list[dict[str, Any]] = []
        if "web_research" in capabilities:
            topic = _research_topic_from_text(prompt)
            fallback_steps.append(
                {
                    "capability": "web_research",
                    "args": {"query": topic},
                    "description": f"{topic} hakkında web araştırması yapılacak.",
                }
            )
        if "email_draft" in capabilities and recipients:
            fallback_steps.append(
                {
                    "capability": "email_draft",
                    "args": {
                        "to": recipients,
                        "subject": subject,
                        "topic": _research_topic_from_text(prompt),
                        "prompt": prompt,
                    },
                    "description": f"{', '.join(recipients)} için e-posta taslağı hazırlanacak.",
                }
            )
        if "email_send" in capabilities and recipients:
            fallback_steps.append(
                {
                    "capability": "email_send",
                    "args": {"to": recipients, "subject": subject},
                    "description": f"{', '.join(recipients)} adresine e-posta gönderilecek.",
                }
            )
        return fallback_steps, {
            "summary": "Backend routing kararına göre desktop görevi yürütülecek.",
            "steps": fallback_steps,
            "privacyClass": "side_effect" if "email_send" in capabilities else "public_text",
        }

    def _email_send_step_from_draft(
        self,
        steps: list[dict[str, Any]],
        structured_result: dict[str, Any] | None,
    ) -> dict[str, Any]:
        draft = structured_result if isinstance(structured_result, dict) else {}
        original_send = next(
            (
                dict(step)
                for step in steps
                if isinstance(step, dict) and _canonical_capability_name(step.get("capability")) == "email_send"
            ),
            {},
        )
        original_args = original_send.get("args", {})
        original_args = dict(original_args) if isinstance(original_args, dict) else {}
        to = self._string_list(draft.get("to") if "to" in draft else original_args.get("to"))
        subject = self._truncate_text(draft.get("subject") or original_args.get("subject") or "E-posta", 180)
        body = str(draft.get("body", "") or original_args.get("body", "") or "").strip()
        args = {
            **original_args,
            "to": to,
            "subject": subject,
            "body": body,
        }
        return {
            "capability": "email_send",
            "args": args,
            "description": original_send.get("description") or f"{', '.join(to)} adresine e-posta gönderilecek.",
        }

    def _execute_deterministic_remote_task(
        self,
        task: dict[str, Any],
        prompt: str,
        title: str,
    ) -> dict[str, Any] | None:
        payload = task.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        route_decision = self._remote_task_route_decision(payload)
        if str(route_decision.get("route", "") or "").strip() != "desktop_runtime":
            return None

        capabilities = self._remote_task_capabilities(task, payload)
        if not capabilities.intersection({"web_research", "email_draft", "email_send", *REMOTE_QUANTUM_CAPABILITIES}):
            return None

        steps, plan_preview = self._remote_task_steps_from_route(task, prompt, capabilities, route_decision)
        if not steps:
            return None

        send_requested = any(_canonical_capability_name(step.get("capability")) == "email_send" for step in steps)
        pre_approval_steps = [
            step
            for step in steps
            if _canonical_capability_name(step.get("capability")) != "email_send"
        ] if send_requested else steps
        conversation = STATE.create_conversation(title or "Remote task")
        conversation_id = str(conversation.get("id", "") or "")
        ok, content, tool_events, error_code, structured_result, artifacts = self.executor_core.execute_plan_steps(
            steps=pre_approval_steps,
            state_factory=STATE.snapshot,
            execute_step=lambda capability, args, state, source: _execute_capability_with_preprocessing(
                capability,
                args,
                state,
                source=source,
            ),
            source="runtime_task",
            task_id=str(task.get("id", "") or ""),
            conversation_id=conversation_id,
        )
        if conversation_id:
            STATE.append_message(
                conversation_id,
                "user",
                prompt,
                {
                    "source": "remote_task",
                    "executionMode": "desktop_runtime",
                    "routeDecision": route_decision,
                },
            )

        if not ok:
            return {
                "ok": True,
                "chatOk": False,
                "assistantMessage": content,
                "provider": "remote_task_adapter",
                "toolEvents": tool_events,
                "conversationId": conversation_id,
                "needsConfirmation": False,
                "structuredResult": structured_result,
                "artifacts": artifacts,
                "error": {"code": _safe_error_code(error_code), "message": content},
            }

        if send_requested:
            send_step = self._email_send_step_from_draft(steps, structured_result)
            send_args = dict(send_step.get("args", {}) or {})
            approval_structured = {
                "kind": "email_send",
                "to": self._string_list(send_args.get("to")),
                "subject": str(send_args.get("subject", "") or ""),
                "body": str(send_args.get("body", "") or ""),
                "provider": str(send_args.get("provider", "") or "google"),
            }
            approval_preview = {
                "summary": str(plan_preview.get("summary", "") or content or "Mail gönderimi için onay gerekiyor."),
                "steps": [
                    {
                        "capability": str(step.get("capability", "") or ""),
                        "description": str(step.get("description", "") or step.get("capability", "") or ""),
                    }
                    for step in steps
                    if isinstance(step, dict)
                ],
                "privacyClass": "side_effect",
            }
            stored_plan = STATE.save_pending_plan(
                {
                    "conversationId": conversation_id,
                    "query": prompt,
                    "intent": "email_send",
                    "capability": "email_send",
                    "confidence": 0.93,
                    "privacyClass": "side_effect",
                    "steps": [send_step],
                    "planPreview": approval_preview,
                    "source": "remote_task_adapter",
                    "createdAt": _utc_now_iso(),
                }
            )
            return {
                "ok": True,
                "chatOk": True,
                "assistantMessage": content,
                "provider": "remote_task_adapter",
                "toolEvents": tool_events,
                "conversationId": conversation_id,
                "executionMode": "plan_preview",
                "needsConfirmation": True,
                "pendingPlanId": str(stored_plan.get("id", "") or ""),
                "planPreview": approval_preview,
                "structuredResult": approval_structured,
                "artifacts": artifacts,
            }

        return {
            "ok": True,
            "chatOk": True,
            "assistantMessage": content,
            "provider": "remote_task_adapter",
            "toolEvents": tool_events,
            "conversationId": conversation_id,
            "needsConfirmation": False,
            "structuredResult": structured_result,
            "artifacts": artifacts,
        }

    def _execute_runtime_task(self, task: dict[str, Any], dispatched_via_websocket: bool = False) -> dict[str, Any]:
        task_id = str(task.get("id", "") or "")
        payload = task.get("payload", {})
        payload = payload if isinstance(payload, dict) else {}
        title = str(task.get("title", "") or payload.get("title", "") or "Elyan görevi")
        prompt = str(payload.get("prompt", "") or payload.get("message", "") or title).strip()
        if not task_id:
            return {"taskId": "", "ok": False, "status": "missing_task_id"}

        preflight_error = self._runtime_task_preflight_error(task, payload)
        if preflight_error is not None:
            report = self._report_runtime_task_status(
                task_id,
                {
                    "status": "failed",
                    "message": preflight_error["message"],
                    "summary": preflight_error["message"],
                    "approvalRequest": {},
                    "artifacts": [],
                    "error": preflight_error["code"],
                },
            )
            return {
                "taskId": task_id,
                "ok": False,
                "status": "failed_closed",
                "report": report.to_dict() if report else None,
            }

        if not prompt:
            failed = self._report_runtime_task_status(
                task_id,
                {
                    "status": "failed",
                    "message": "Görev metni boş.",
                    "error": "task_prompt_missing",
                    "artifacts": [],
                },
            )
            return {"taskId": task_id, "ok": False, "status": "failed", "report": failed.to_dict() if failed else None}

        self._set_runtime_task_heartbeat(dispatched_via_websocket, "busy", task_id)

        running = self._report_runtime_task_status(
            task_id,
            {
                "status": "running",
                "message": "Desktop runtime görevi yürütüyor.",
                "artifacts": [],
            },
        )
        if running is None or not running.ok:
            self._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
            return {"taskId": task_id, "ok": False, "status": "running_rejected", "report": running.to_dict() if running else None}

        local_result = self._execute_deterministic_remote_task(task, prompt, title)
        if local_result is None:
            local_result = self.send_conversation("", prompt, title)
        chat_ok = local_result.get("chatOk", True) is not False
        assistant_message = str(local_result.get("assistantMessage", "") or "").strip()
        tool_events = local_result.get("toolEvents", [])
        provider = str(local_result.get("provider", "") or "")
        if local_result.get("needsConfirmation") is True and str(local_result.get("pendingPlanId", "") or "").strip():
            pending_plan_id = str(local_result.get("pendingPlanId", "") or "").strip()
            conversation_id = str(local_result.get("conversationId", "") or "").strip()
            permission_error = self._pending_plan_permission_error(pending_plan_id)
            if permission_error is not None:
                STATE.remove_pending_plan(pending_plan_id)
                failed_payload = {
                    "status": "failed",
                    "message": str(permission_error.get("message", "") or "Görev için açık izin gerekiyor."),
                    "summary": assistant_message[:1000],
                    "result": {
                        "assistantMessage": str(permission_error.get("message", "") or assistant_message),
                        "provider": provider,
                        "toolEvents": tool_events if isinstance(tool_events, list) else [],
                        "conversationId": conversation_id,
                    },
                    "artifacts": [],
                    "approvalRequest": {},
                    "error": str(permission_error.get("code", "") or "PERMISSION_REQUIRED"),
                }
                report = self._report_runtime_task_status(task_id, failed_payload)
                self._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
                return {
                    "taskId": task_id,
                    "ok": bool(report and report.ok),
                    "status": "failed",
                    "report": report.to_dict() if report else None,
                    "local": {
                        "conversationId": conversation_id,
                        "provider": provider,
                        "pendingPlanId": pending_plan_id,
                    },
                }
            approval_request = self._approval_request_payload(local_result)
            STATE.save_remote_task_link(
                task_id,
                pending_plan_id,
                conversation_id,
                title=title,
                status="waiting_approval",
            )
            waiting_payload = {
                "status": "waiting_approval",
                "message": "Yerel onay bekleniyor.",
                "summary": approval_request.get("summary", assistant_message) or assistant_message[:1000],
                "approvalRequest": approval_request,
                "result": {
                    "assistantMessage": assistant_message,
                    "provider": provider,
                    "toolEvents": tool_events if isinstance(tool_events, list) else [],
                    "conversationId": conversation_id,
                },
                "artifacts": [],
            }
            report = self._report_runtime_task_status(task_id, waiting_payload)
            self._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
            return {
                "taskId": task_id,
                "ok": bool(report and report.ok),
                "status": "waiting_approval",
                "report": report.to_dict() if report else None,
                "local": {
                    "conversationId": conversation_id,
                    "provider": provider,
                    "pendingPlanId": pending_plan_id,
                },
            }

        result = self._report_runtime_task_terminal_result(
            task_id,
            local_result,
            dispatched_via_websocket=dispatched_via_websocket,
        )
        self._set_runtime_task_heartbeat(dispatched_via_websocket, "idle")
        return result

    def _approval_resolution_state(self, approval_request: dict[str, Any]) -> str:
        request_payload = dict(approval_request) if isinstance(approval_request, dict) else {}
        resolution = request_payload.get("resolution", {})
        resolution = dict(resolution) if isinstance(resolution, dict) else {}
        if resolution.get("approved") is True:
            return "approved"
        status = str(resolution.get("status", "") or "").strip().lower()
        if status in {"approved", "accepted", "confirmed"}:
            return "approved"
        if resolution.get("rejected") is True:
            return "rejected"
        if "approved" in resolution and resolution.get("approved") is False:
            return "rejected"
        if status in {"rejected", "declined", "denied", "canceled", "cancelled"}:
            return "rejected"
        return "pending"

    def _runtime_delivery_capabilities(self) -> set[str]:
        runtime = _map_from(STATE.snapshot().get("runtime"))
        raw = runtime.get("capabilities")
        if not isinstance(raw, list) or not raw:
            raw = _runtime_advertised_capabilities()
        return {_canonical_capability_name(item) for item in raw if str(item or "").strip()}

    def _runtime_task_preflight_error(self, task: dict[str, Any], payload: dict[str, Any]) -> dict[str, str] | None:
        runtime = _map_from(STATE.snapshot().get("runtime"))
        runtime_device_id = str(runtime.get("deviceId", "") or "").strip()
        target_device_id = str(task.get("targetDeviceId", "") or "").strip()
        if runtime_device_id and target_device_id and runtime_device_id != target_device_id:
            return {
                "code": "runtime_target_mismatch",
                "message": "Görev başka bir masaüstüne atanmış görünüyor. Güvenli şekilde yürütme durduruldu.",
            }

        requested_capabilities = self._remote_task_capabilities(task, payload)
        if requested_capabilities:
            available_capabilities = self._runtime_delivery_capabilities()
            missing = sorted(capability for capability in requested_capabilities if capability not in available_capabilities)
            if missing:
                return {
                    "code": "runtime_capability_mismatch",
                    "message": f"Görev için gereken yetenekler bu masaüstünde hazır değil: {', '.join(missing)}.",
                }

        return None

    def execute_assigned_runtime_tasks(self, limit: int = 1) -> dict[str, Any]:
        self._assigned_task_fetch_requested.clear()
        self._last_assigned_task_fetch_at = time.monotonic()
        assigned = self.backend.runtime_tasks_assigned()
        if not assigned.ok:
            return {"ok": False, "error": {"code": "TASK_FETCH_FAILED", "message": "Atanmış görevler alınamadı."}, "result": assigned.to_dict()}

        data = assigned.data if isinstance(assigned.data, dict) else {}
        tasks = data.get("tasks", [])
        if not isinstance(tasks, list):
            tasks = []
        if tasks:
            items = [
                self._normalized_task_inbox_item(task)
                for task in tasks
                if isinstance(task, dict) and str(task.get("id", "") or "").strip()
            ]
            if items:
                for item in items:
                    STATE.upsert_task_inbox_item(item, last_synced_at=_utc_now_iso())
        self._reconcile_task_inbox_active_truth(
            {
                str(task.get("id", "") or "").strip()
                for task in tasks
                if isinstance(task, dict)
            }
        )

        executions: list[dict[str, Any]] = []
        for task in tasks[: max(1, limit)]:
            if not isinstance(task, dict):
                continue
            task_id = str(task.get("id", "") or "").strip()
            status = str(task.get("status", "") or "").strip().lower()
            if status == "canceled":
                self._discard_remote_pending_task_locally(task_id)
                STATE.upsert_task_inbox_item(
                    {
                        "id": task_id,
                        "status": "canceled",
                        "summary": "Görev iptal edildi.",
                        "approvalRequest": {},
                        "updatedAt": _utc_now_iso(),
                    },
                    last_synced_at=_utc_now_iso(),
                )
                self._remember_terminal_assigned_task(task_id)
                executions.append({"taskId": task_id, "ok": True, "status": "skipped_terminal"})
                continue
            if status in {"completed", "failed"}:
                self._remove_remote_task_local_link(task_id)
                self._remember_terminal_assigned_task(task_id)
                executions.append({"taskId": task_id, "ok": True, "status": "skipped_terminal"})
                continue
            execution_gate = self._begin_assigned_task_execution(task_id)
            if execution_gate != "accepted":
                executions.append({"taskId": task_id, "ok": True, "status": execution_gate})
                continue
            approval_request = task.get("approvalRequest", {})
            approval_request = approval_request if isinstance(approval_request, dict) else {}
            try:
                if status == "waiting_approval":
                    resolution_state = self._approval_resolution_state(approval_request)
                    if resolution_state == "approved":
                        executions.append(self._resume_remote_task_after_approval(task_id, True))
                    elif resolution_state == "rejected":
                        executions.append(self._resume_remote_task_after_approval(task_id, False))
                    else:
                        executions.append({"taskId": task_id, "ok": True, "status": "waiting_approval"})
                    continue
                executions.append(self._execute_runtime_task(task, False))
            finally:
                self._clear_assigned_task_inflight(task_id)

        return {"ok": True, "executions": executions, "fetched": len(tasks)}

    def _speech_capability_result(self, capability: str, payload: dict[str, Any]) -> dict[str, Any]:
        tool_result = run_capability(capability, payload, STATE.snapshot())
        event = safe_tool_event(capability, tool_result, source="speech_runtime")
        if tool_result.get("ok"):
            structured = tool_result.get("result")
            result = dict(structured) if isinstance(structured, dict) else {"kind": capability}
            result["events"] = [event]
            step_artifacts = tool_result.get("artifacts")
            if isinstance(step_artifacts, list):
                result["artifacts"] = [dict(item) for item in step_artifacts if isinstance(item, dict)]
            return result
        return {
            "ok": False,
            "error": tool_result.get(
                "error",
                {"code": "TOOL_EXECUTION_FAILED", "message": "Araç güvenli şekilde tamamlanamadı."},
            ),
            "events": [event],
        }

    def handle(self, request: dict[str, Any]) -> dict[str, Any]:
        start = time.perf_counter()
        self.context.request_count += 1
        request_id = str(request.get("id") or _request_id())
        task_id = str(request.get("taskId") or request.get("task_id") or f"task_{request_id[4:]}")
        capability = str(request.get("capability") or request.get("action") or request.get("command") or "").strip()
        payload = request.get("payload")
        if payload is None:
            payload = request.get("params")
        if payload is None:
            payload = request.get("data")
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            payload = {"value": payload}

        try:
            if capability in {"bootstrap", "runtime.bootstrap"}:
                result = self.bootstrap()
            elif capability in {"runtime.status", "status"}:
                result = self.status()
            elif capability in {"state.get", "settings.get"}:
                result = self.get_state()
            elif capability in {"state.update", "settings.update"}:
                result = self.update_state(payload)
            elif capability == "conversation.list":
                result = {"conversations": _conversation_entries(), "activeConversationId": str(STATE.snapshot().get("conversation", {}).get("activeId", "") or "")}
            elif capability == "conversation.create":
                result = self.create_conversation(str(payload.get("title", "") or ""))
            elif capability == "conversation.select":
                result = self.select_conversation(str(payload.get("conversationId", "") or payload.get("conversation_id", "") or ""))
            elif capability == "conversation.send":
                result = self.send_conversation(
                    str(payload.get("conversationId", "") or payload.get("conversation_id", "") or ""),
                    str(payload.get("text", "") or payload.get("message", "") or ""),
                    str(payload.get("title", "") or "") or None,
                    payload.get("selectedArtifacts") if isinstance(payload.get("selectedArtifacts"), list) else None,
                )
            elif capability == "conversation.confirm_plan":
                result = self.confirm_conversation_plan(
                    str(payload.get("conversationId", "") or payload.get("conversation_id", "") or ""),
                    str(payload.get("pendingPlanId", "") or payload.get("pending_plan_id", "") or ""),
                    bool(payload.get("approved", False)),
                )
            elif capability == "conversation.revise_plan":
                result = self.revise_conversation_plan(
                    str(payload.get("conversationId", "") or payload.get("conversation_id", "") or ""),
                    str(payload.get("pendingPlanId", "") or payload.get("pending_plan_id", "") or ""),
                    str(payload.get("revisionText", "") or payload.get("revision_text", "") or ""),
                )
            elif capability == "speech.capture":
                result = self._speech_capability_result(
                    "speech_capture",
                    {
                        "action": str(payload.get("action", "status") or "status"),
                        "_uiGesture": bool(payload.get("_uiGesture", False)),
                    },
                )
            elif capability == "speech.transcribe":
                result = self._speech_capability_result(
                    "speech_to_text",
                    {
                        "audioPath": str(payload.get("audioPath", "") or payload.get("audio_path", "") or ""),
                        "sessionId": str(payload.get("sessionId", "") or payload.get("session_id", "") or ""),
                        "languageHint": str(payload.get("languageHint", "") or payload.get("language_hint", "") or ""),
                        "taskId": task_id,
                    },
                )
            elif capability == "speech.speak":
                result = self._speech_capability_result(
                    "text_to_speech",
                    {
                        "text": str(payload.get("text", "") or ""),
                        "languageHint": str(payload.get("languageHint", "") or payload.get("language_hint", "") or ""),
                        "voice": str(payload.get("voice", "") or ""),
                        "interrupt": bool(payload.get("interrupt", False)),
                    },
                )
            elif capability == "local_models.status":
                result = self.local_models_status()
            elif capability == "local_models.list":
                result = self.local_models_list()
            elif capability == "local_models.download":
                result = self.local_models_download(str(payload.get("model", "") or ""))
            elif capability == "local_models.remove":
                result = self.local_models_remove(str(payload.get("model", "") or ""))
            elif capability == "local_models.set_default":
                result = self.local_models_set_default(str(payload.get("model", "") or ""))
            elif capability == "local_models.job":
                result = self.local_model_job(str(payload.get("jobId", "") or payload.get("job_id", "") or ""))
            elif capability == "local_models.cancel":
                result = self.local_model_cancel(str(payload.get("jobId", "") or payload.get("job_id", "") or ""))
            elif capability == "local_models.start":
                result = self.local_model_start(str(payload.get("providerId", "") or payload.get("provider_id", "") or ""))
            elif capability == "providers.catalog":
                result = self.providers_catalog()
            elif capability == "providers.update_config":
                result = self.providers_update_config(payload)
            elif capability == "providers.validate":
                result = self.providers_validate(payload)
            elif capability == "providers.secrets_sync":
                result = self.providers_secret_sync(payload)
            elif capability == "backend.auth_me":
                result = self.backend_auth_me()
            elif capability == "backend.auth_login":
                result = self.backend_auth_login(payload)
            elif capability == "backend.auth_register":
                result = self.backend_auth_register(payload)
            elif capability == "backend.auth_refresh":
                result = self.backend_auth_refresh()
            elif capability == "backend.auth_logout":
                result = self.backend_auth_logout()
            elif capability == "backend.auth_delete_account":
                result = self.backend_auth_delete_account()
            elif capability == "backend.auth_update_profile":
                result = self.backend_auth_update_profile(payload)
            elif capability == "backend.auth_change_password":
                result = self.backend_auth_change_password(payload)
            elif capability == "backend.auth_avatar_upload":
                result = self.backend_auth_avatar_upload(payload)
            elif capability == "backend.auth_avatar_get":
                result = self.backend_auth_avatar_get()
            elif capability == "backend.auth_avatar_delete":
                result = self.backend_auth_avatar_delete()
            elif capability == "backend.mobile_bootstrap":
                result = self.backend_mobile_bootstrap()
            elif capability == "backend.brain_profile":
                result = self.backend_brain_profile()
            elif capability == "backend.brain_retrieval_search":
                result = self.backend_brain_retrieval_search(payload)
            elif capability == "backend.brain_knowledge_document":
                result = self.backend_brain_knowledge_document(payload)
            elif capability == "backend.tasks.list":
                result = self.backend_tasks_list(payload)
            elif capability == "backend.tasks.detail":
                result = self.backend_task_detail(
                    str(payload.get("taskId", "") or payload.get("task_id", "") or "")
                )
            elif capability == "backend.tasks.approval":
                result = self.backend_task_approval(
                    str(payload.get("taskId", "") or payload.get("task_id", "") or ""),
                    bool(payload.get("approved", False)),
                    str(payload.get("notes", "") or ""),
                )
            elif capability == "mcp.server.upsert":
                result = self.mcp_server_upsert(payload)
            elif capability == "mcp.server.remove":
                result = self.mcp_server_remove(
                    str(payload.get("serverId", "") or payload.get("server_id", "") or "")
                )
            elif capability == "mcp.refresh":
                result = self.mcp_refresh()
            elif capability == "skill.refresh":
                result = self.skill_refresh()
            elif capability == "skill.list":
                result = self.skill_list(refresh=bool(payload.get("refresh", False)))
            elif capability == "skill.set_enabled":
                result = self.skill_set_enabled(
                    str(payload.get("skillId", "") or payload.get("skill_id", "") or ""),
                    bool(payload.get("enabled", False)),
                )
            elif capability == "skill.clone":
                result = self.skill_clone(
                    str(payload.get("skillId", "") or payload.get("skill_id", "") or "")
                )
            elif capability == "skill.upsert_local":
                result = self.skill_upsert_local(payload)
            elif capability == "skill.remove_local":
                result = self.skill_remove_local(
                    str(payload.get("skillId", "") or payload.get("skill_id", "") or "")
                )
            elif capability in {"skill.run", "run_skill"}:
                result = self.skill_run(payload)
            elif capability == "mcp.tools.list":
                result = self.mcp_tools_list(refresh=bool(payload.get("refresh", False)))
            elif capability == "mcp.tool.call":
                result = self.mcp_tool_call(payload)
            elif capability == "runtime.register":
                result = self.register_runtime(payload)
            elif capability == "runtime.ensure_registered":
                result = self.ensure_runtime_registered()
            elif capability == "runtime.heartbeat":
                result = self.heartbeat(payload)
            elif capability == "runtime.session":
                result = self.runtime_session()
            elif capability == "runtime.tasks.assigned":
                result = self.runtime_tasks_assigned()
            elif capability == "runtime.tasks.status":
                result = self.runtime_task_status(str(payload.get("taskId", "") or payload.get("task_id", "") or ""), payload)
            elif capability == "runtime.tasks.artifacts":
                result = self.runtime_task_artifacts(str(payload.get("taskId", "") or payload.get("task_id", "") or ""), payload)
            elif capability == "runtime.tasks.execute_assigned":
                result = self.execute_assigned_runtime_tasks(int(payload.get("limit", 1) or 1))
            elif capability == "pairing.create_session":
                result = self.pairing_create_session(payload)
            elif capability == "pairing.claim_session":
                result = self.pairing_claim_session(str(payload.get("sessionId", "") or payload.get("session_id", "") or ""), payload)
            elif capability == "pairing.get_session":
                result = self.pairing_get_session(str(payload.get("sessionId", "") or payload.get("session_id", "") or ""))
            elif capability in capability_names():
                tool_result = run_capability(capability, payload, STATE.snapshot())
                result = {
                    "ok": bool(tool_result.get("ok")),
                    "result": tool_result,
                    "error": tool_result.get("error"),
                    "events": [safe_tool_event(capability, tool_result, source="direct_capability")],
                }
            elif capability in {"bootstrap.workspace"}:
                result = {"projects": _workspace_projects()}
            else:
                result = {
                    "ok": False,
                    "error": {
                        "code": "UNKNOWN_CAPABILITY",
                        "message": f"Bilinmeyen capability: {capability}",
                    },
                }
        except Exception as exc:
            print(f"runtime error capability={capability} type={type(exc).__name__}", file=sys.stderr)
            result = {
                "ok": False,
                "error": {
                    "code": "UNHANDLED_ERROR",
                    "message": "Runtime isteği güvenli şekilde tamamlanamadı.",
                },
            }

        if isinstance(result, dict):
            result = _sanitize_transport_payload(result)

        ok = bool(result.get("ok", True))
        response = {
            "id": request_id,
            "taskId": task_id,
            "ok": ok,
            "capability": capability,
            "result": result if ok else None,
            "events": result.get("events", []) if isinstance(result, dict) else [],
            "artifacts": result.get("artifacts", []) if isinstance(result, dict) else [],
            "error": None if ok else result.get("error", {"code": "SAFE_ERROR", "message": "Beklenmeyen hata"}),
            "durationMs": int((time.perf_counter() - start) * 1000),
        }
        if isinstance(result, dict) and result.get("requestId"):
            response["requestId"] = result["requestId"]
        else:
            response["requestId"] = request_id
        return response


def main() -> int:
    bridge = RuntimeBridge()
    executor = ThreadPoolExecutor(max_workers=4)
    out_lock = threading.Lock()

    def emit(payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False)
        with out_lock:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()

    def handle_line(line: str) -> None:
        line = line.strip()
        if not line:
            return
        try:
            request = json.loads(line)
        except Exception:
            emit(
                {
                    "id": _request_id(),
                    "taskId": _request_id(),
                    "ok": False,
                    "capability": "",
                    "result": None,
                    "events": [],
                    "artifacts": [],
                    "error": {"code": "INVALID_JSON", "message": "Gecersiz JSON alindi."},
                    "durationMs": 0,
                    "requestId": _request_id(),
                }
            )
            return

        def _worker() -> None:
            response = bridge.handle(request if isinstance(request, dict) else {})
            emit(response)

        executor.submit(_worker)

    emit(
        {
            "id": _request_id(),
            "taskId": _request_id(),
            "ok": True,
            "capability": "bridge.ready",
            "result": {
                "ready": True,
                "startedAt": bridge.context.started_at,
                "pythonVersion": sys.version.split()[0],
            },
            "events": [],
            "artifacts": [],
            "error": None,
            "durationMs": 0,
            "requestId": _request_id(),
        }
    )
    native_file_indexer.warmup_in_background()

    try:
        for raw in sys.stdin:
            handle_line(raw)
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
