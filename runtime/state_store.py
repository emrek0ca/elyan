from __future__ import annotations

import copy
import difflib
import json
import os
import re
import threading
import sys
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent.parent
LEGACY_STATE_PATH = BASE_DIR / "config" / "elyan_state.json"


def _user_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Elyan"
    if os.name == "nt":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Elyan"
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home) / "Elyan"
    return Path.home() / ".config" / "Elyan"


CONFIG_DIR = _user_data_dir() / "state"
STATE_PATH = CONFIG_DIR / "elyan_state.json"


DEFAULT_STATE: dict[str, Any] = {
    "appearance": {
        "theme": "dark",
        "accent": "aqua",
        "textSize": "medium",
        "density": "compact",
        "sidebarBehavior": "expanded",
        "animations": True,
        "startupScreen": "conversation",
    },
    "locale": {
        "language": "tr",
        "timeFormat": "24h",
        "dateFormat": "dd/MM/yyyy",
        "region": "TR",
        "keyboardDetection": True,
    },
    "startup": {
        "startOnBoot": False,
        "backgroundWork": True,
        "menuBarIcon": True,
        "autoUpdate": False,
        "updateChannel": "stable",
        "crashReporting": False,
        "systemNotifications": True,
    },
    "privacy": {
        "localDataStaysLocal": True,
        "analytics": False,
        "redactCrashReports": True,
        "autoClearHistory": False,
        "clearLocalMemory": False,
        "permissionHistory": True,
    },
    "performance": {
        "lowPowerMode": False,
        "maxMemoryMb": 1024,
        "backgroundTaskLimit": 2,
        "concurrentTaskCount": 2,
        "modelToolStartupMode": "lazy",
        "logLevel": "info",
    },
    "billing": {
        "planCode": "offline",
        "status": "offline",
        "aiCreditsMonthly": 0,
        "taskLimitMonthly": 0,
        "periodEndsAt": "",
        "usage": {},
        "paymentMethod": "",
        "cards": [],
        "billingInfo": {},
        "taxInfo": {},
        "iyzicoStatus": "unavailable",
        "invoices": [],
        "limits": {},
        "limitBehavior": "fail_closed",
        "features": [],
    },
    "providers": {
        "active": "local",
        "routingPolicy": "local_first",
        "defaultLocalModel": "",
        "defaultLocalRuntime": "ollama",
        "fallbackToCloud": True,
        "openai": {
            "enabled": False,
            "baseUrl": "https://api.openai.com/v1",
            "defaultModel": "gpt-4.1-mini",
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "gemini": {
            "enabled": False,
            "baseUrl": "https://generativelanguage.googleapis.com",
            "defaultModel": "gemini-2.5-flash",
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "anthropic": {
            "enabled": False,
            "baseUrl": "https://api.anthropic.com",
            "defaultModel": "claude-3-5-sonnet-latest",
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "groq": {
            "enabled": False,
            "baseUrl": "https://api.groq.com/openai/v1",
            "defaultModel": "llama-3.1-70b-versatile",
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "ollama": {
            "enabled": True,
            "baseUrl": "http://127.0.0.1:11434",
            "defaultModel": "llama3.1:8b",
            "managed": True,
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "lmstudio": {
            "enabled": False,
            "baseUrl": "http://127.0.0.1:1234/v1",
            "defaultModel": "",
            "managed": False,
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "llamacpp": {
            "enabled": False,
            "baseUrl": "http://127.0.0.1:8080/v1",
            "defaultModel": "",
            "binaryPath": "",
            "modelPath": "",
            "autoStart": False,
            "managed": False,
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
        "local": {
            "enabled": True,
            "defaultModel": "",
            "runtimeFamily": "ollama",
            "devicePreference": "auto",
        },
        "custom": {
            "enabled": False,
            "baseUrl": "",
            "defaultModel": "",
            "validationStatus": "idle",
            "lastValidatedAt": "",
        },
    },
    "connections": {
        "google": False,
        "gmail": False,
        "drive": False,
        "calendar": False,
        "github": False,
        "notion": False,
        "slack": False,
        "microsoft": False,
        "dropbox": False,
        "linear": False,
        "jira": False,
    },
    "skills": {
        "activeSkills": [],
        "mcpServers": [],
        "toolPermissions": {},
        "defaultSkill": "",
        "toolSafety": "balanced",
        "usage": {
            "recentRuns": [],
            "skillStats": {},
            "lastSuccessfulSkillId": "",
            "lastSuccessfulAt": "",
            "lastFailedSkillId": "",
            "lastFailedAt": "",
        },
    },
    "localIndexing": {
        "approvedRoots": [],
        "status": {
            "available": False,
            "ready": False,
            "version": "",
            "stats": {
                "rootCount": 0,
                "indexedFileCount": 0,
                "lastScanAt": "",
            },
            "errorCode": "",
        },
    },
    "pairing": {
        "deviceName": "Elyan",
        "allowNewLinks": True,
        "externalDeviceId": "",
        "lastSessionId": "",
        "desktopDeviceId": "",
        "pairingToken": "",
        "pairingCode": "",
        "manualEntryCode": "",
        "qrText": "",
        "qrDataUrl": "",
        "expiresAt": "",
        "lastSessionStatus": "",
        "lastErrorCode": "",
        "realtimeReady": False,
        "connectedDevices": [],
        "lastClaimedAt": "",
        "lastHeartbeatAt": "",
    },
    "runtime": {
        "runtimeToken": "",
        "deviceId": "",
        "deviceSecret": "",
        "connectionId": "",
        "currentTaskId": "",
        "capabilities": [],
        "capabilityStates": {},
        "ready": False,
        "lifecycleState": "offline",
        "websocketConnected": False,
        "lastErrorCode": "",
        "lastXRequestId": "",
        "executor": {
            "available": True,
            "graphBackend": "sequential_fallback",
            "modelRouterBackend": "native_router",
            "langgraphAvailable": False,
            "liteLLMAvailable": False,
            "activeExecutionCount": 0,
            "currentExecutions": [],
            "lastExecutionAt": "",
            "lastExecutionDetail": "",
            "lastExecutionOk": False,
            "lastFallbackReason": "",
            "metrics": {
                "completed": 0,
                "failed": 0,
                "verificationRetries": 0,
                "fallbacks": 0,
            },
        },
    },
    "account": {
        "displayName": "Elyan",
        "email": "",
        "avatarUrl": "",
        "avatarPath": "",
        "hasAvatar": False,
        "avatarVersion": 0,
        "accessToken": "",
        "refreshToken": "",
        "onboardingCompleted": False,
        "securityLevel": "standard",
        "personalization": True,
        "dataManagement": "local_first",
        "dangerousAreaEnabled": False,
        "subscription": {
            "planCode": "offline",
            "status": "offline",
            "aiCreditsMonthly": 0,
            "taskLimitMonthly": 0,
            "periodEndsAt": "",
        },
    },
    "conversation": {
        "activeId": "",
        "items": [],
    },
    "composer": {
        "selectedArtifacts": [],
    },
    "scheduledTasks": [],
    "permissions": {
        "allow_browser_control": False,
        "allow_screen_analysis": False,
        "allow_computer_control": False,
        "allow_sensitive_operator_actions": False,
        "allow_file_indexing": False,
        "allow_system_inspection": False,
        "allow_personal_actions": False,
        "allow_shell": False,
        "allow_destructive_tools": False,
    },
    "speech": {
        "autoSpeakReplies": False,
    },
    "taskInbox": {
        "items": [],
        "pendingCount": 0,
        "activeCount": 0,
        "lastSyncedAt": "",
        "links": [],
    },
    "taskIntelligence": {
        "recentSuccessfulRoutes": [],
        "recentMisroutes": [],
        "recentClarifications": [],
        "confirmedPlanPatterns": [],
        "rejectedPlanPatterns": [],
        "corrections": [],
        "capabilityQuality": {},
        "clarificationCount": 0,
        "confidenceHints": {},
        "responseStyle": {
            "length": "short",
            "directness": "direct",
            "tone": "professional",
        },
        "pendingPlans": [],
        "lastUpdatedAt": "",
    },
    "operator": {
        "activeRunId": "",
        "status": "idle",
        "abortRequested": False,
        "abortReason": "",
        "currentStepIndex": 0,
        "lastObservationId": "",
        "lastStopReason": "",
        "lastCompletedAt": "",
        "operatorResolutionMode": "",
        "lastTargetSource": "",
        "lastVerificationSource": "",
        "lastTargetConfidence": 0.0,
        "operatorRuns": [],
        "operatorSteps": [],
        "screenObservations": [],
        "inputActions": [],
        "verificationResults": [],
        "lastUpdatedAt": "",
    },
    "updatedAt": "",
}

KNOWN_PROVIDER_IDS = {"local", "ollama", "lmstudio", "llamacpp", "openai", "gemini", "anthropic", "groq", "custom"}


_LOCK = threading.RLock()
_VOLATILE_PROVIDER_SECRETS: dict[str, str] = {}
_RECENT_ROUTE_LIMIT = 24
_CONFIRMED_PLAN_LIMIT = 16
_MISROUTE_LIMIT = 16
_CLARIFICATION_PATTERN_LIMIT = 16
_REJECTED_PLAN_LIMIT = 16
_CORRECTION_LIMIT = 16
_PENDING_PLAN_LIMIT = 12
_TASK_INBOX_LIMIT = 24
_TASK_LINK_LIMIT = 24
_ACTIVE_TASK_STATUSES = {"queued", "planning", "running", "waiting_approval"}
_MCP_SERVER_LIMIT = 12
_ARTIFACT_SELECTION_LIMIT = 3
_ACTIVE_OPERATOR_STATUSES = {"observing", "locating", "executing", "verifying", "waiting_approval", "running"}
_TERMINAL_OPERATOR_STATUSES = {"idle", "stopped", "failed", "completed"}


def _task_inbox_timestamp() -> str:
    import datetime as dt

    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _intelligence_timestamp() -> str:
    return _task_inbox_timestamp()


def _normalize_task_item(task: dict[str, Any]) -> dict[str, Any]:
    approval_request = task.get("approvalRequest")
    if isinstance(approval_request, dict):
        approval_request = copy.deepcopy(approval_request)
    else:
        approval_request = {}
    route_decision = task.get("routeDecision")
    if isinstance(route_decision, dict):
        route_decision = copy.deepcopy(route_decision)
    else:
        route_decision = {}
    plan_preview = task.get("planPreview")
    if isinstance(plan_preview, dict):
        plan_preview = copy.deepcopy(plan_preview)
    else:
        plan_preview = {}
    execution_trace = task.get("executionTrace")
    if isinstance(execution_trace, dict):
        execution_trace = copy.deepcopy(execution_trace)
    else:
        execution_trace = {}
    artifact_count = task.get("artifactCount")
    try:
        normalized_artifact_count = max(0, int(artifact_count or 0))
    except (TypeError, ValueError):
        normalized_artifact_count = 0
    return {
        "id": str(task.get("id", "") or "").strip(),
        "title": " ".join(str(task.get("title", "") or "").split())[:200],
        "status": str(task.get("status", "") or "").strip()[:64],
        "targetDeviceId": str(task.get("targetDeviceId", "") or "").strip()[:80],
        "queuePosition": int(task.get("queuePosition") or 0),
        "summary": str(task.get("summary", "") or "").strip()[:1000],
        "error": str(task.get("error", "") or "").strip()[:240],
        "approvalRequest": approval_request,
        "routeDecision": route_decision,
        "planPreview": plan_preview,
        "executionTrace": execution_trace,
        "deliveryState": str(task.get("deliveryState", "") or "").strip()[:32],
        "runtimeConnectionId": str(task.get("runtimeConnectionId", "") or "").strip()[:80],
        "dispatchLeaseId": str(task.get("dispatchLeaseId", "") or "").strip()[:120],
        "dispatchLeaseExpiresAt": str(task.get("dispatchLeaseExpiresAt", "") or "").strip()[:80],
        "dispatchAckAt": str(task.get("dispatchAckAt", "") or "").strip()[:80],
        "lastDispatchAttemptAt": str(task.get("lastDispatchAttemptAt", "") or "").strip()[:80],
        "createdAt": str(task.get("createdAt", "") or "").strip()[:80],
        "startedAt": str(task.get("startedAt", "") or "").strip()[:80],
        "completedAt": str(task.get("completedAt", "") or "").strip()[:80],
        "canceledAt": str(task.get("canceledAt", "") or "").strip()[:80],
        "updatedAt": str(task.get("updatedAt", "") or "").strip()[:80],
        "lastVerifiedAt": str(task.get("lastVerifiedAt", "") or "").strip()[:80],
        "lastRemoteStatus": str(task.get("lastRemoteStatus", "") or "").strip()[:64],
        "artifactCount": normalized_artifact_count,
        "origin": str(task.get("origin", "") or "mobile").strip()[:40] or "mobile",
    }


def _merge_task_item(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = _normalize_task_item(existing)
    update_payload = _normalize_task_item({**existing, **updates})
    for key, value in update_payload.items():
        if key in {"summary", "error"} and not str(value or "").strip():
            continue
        if key == "approvalRequest" and not value:
            merged[key] = {}
            continue
        merged[key] = value
    if str(updates.get("summary", "") or "").strip() == "":
        merged["summary"] = str(existing.get("summary", "") or "").strip()[:1000]
    if str(updates.get("error", "") or "").strip() == "":
        merged["error"] = str(existing.get("error", "") or "").strip()[:240]
    return merged


def _sort_task_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("updatedAt", "") or ""),
            str(item.get("createdAt", "") or ""),
            str(item.get("id", "") or ""),
        ),
        reverse=True,
    )


def _recount_task_inbox(items: list[dict[str, Any]]) -> tuple[int, int]:
    pending_count = 0
    active_count = 0
    for item in items:
        status = str(item.get("status", "") or "").strip()
        if status == "waiting_approval":
            pending_count += 1
        if status in _ACTIVE_TASK_STATUSES:
            active_count += 1
    return pending_count, active_count


def _normalize_route_query(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _quality_entry_payload(
    *,
    query: str,
    intent: str,
    capability: str,
    args: dict[str, Any] | None = None,
    conversation_id: str = "",
    question: str = "",
    corrected_to: str = "",
    outcome: str = "",
) -> dict[str, Any]:
    return {
        "query": " ".join(str(query or "").split())[:160],
        "intent": str(intent or "").strip()[:80],
        "capability": str(capability or "").strip()[:80],
        "args": copy.deepcopy(args) if isinstance(args, dict) else {},
        "conversationId": str(conversation_id or "").strip()[:80],
        "question": " ".join(str(question or "").split())[:200],
        "correctedTo": " ".join(str(corrected_to or "").split())[:160],
        "outcome": str(outcome or "").strip()[:32],
        "updatedAt": _intelligence_timestamp(),
    }


def _touch_task_intelligence(intelligence: dict[str, Any]) -> None:
    intelligence["lastUpdatedAt"] = _intelligence_timestamp()


def _update_capability_quality(
    intelligence: dict[str, Any],
    *,
    capability: str,
    outcome: str,
) -> None:
    normalized_capability = str(capability or "").strip()[:80]
    if not normalized_capability:
        return
    quality = intelligence.setdefault("capabilityQuality", {})
    if not isinstance(quality, dict):
        quality = {}
        intelligence["capabilityQuality"] = quality
    current = quality.get(normalized_capability, {})
    if not isinstance(current, dict):
        current = {}
    next_payload = {
        "successes": int(current.get("successes", 0) or 0),
        "clarifications": int(current.get("clarifications", 0) or 0),
        "revisions": int(current.get("revisions", 0) or 0),
        "rejections": int(current.get("rejections", 0) or 0),
        "misroutes": int(current.get("misroutes", 0) or 0),
        "lastSeenAt": _intelligence_timestamp(),
    }
    if outcome == "correct":
        next_payload["successes"] += 1
    elif outcome == "clarified":
        next_payload["clarifications"] += 1
    elif outcome == "revised":
        next_payload["revisions"] += 1
    elif outcome == "rejected":
        next_payload["rejections"] += 1
    elif outcome == "misrouted":
        next_payload["misroutes"] += 1
    quality[normalized_capability] = next_payload


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = copy.deepcopy(value)
    return base


def _generate_external_device_id() -> str:
    from uuid import uuid4

    return uuid4().hex


def _ensure_defaults(raw: dict[str, Any] | None) -> dict[str, Any]:
    state = copy.deepcopy(DEFAULT_STATE)
    if isinstance(raw, dict):
        _deep_merge(state, raw)
    appearance = state.get("appearance", {})
    if isinstance(appearance, dict) and str(appearance.get("accent", "") or "").strip().lower() == "neutral":
        appearance["accent"] = "aqua"
    pairing = state.get("pairing", {})
    if isinstance(pairing, dict):
        device_name = str(pairing.get("deviceName", "") or "").strip()
        if not device_name or device_name.lower().endswith("desktop"):
            pairing["deviceName"] = "Elyan"
        external_device_id = str(pairing.get("externalDeviceId", "") or "").strip()
        if not external_device_id:
            pairing["externalDeviceId"] = _generate_external_device_id()
    _normalise_provider_state(state)
    _normalise_mcp_server_state(state)
    _normalise_composer_state(state)
    _normalise_local_indexing_state(state)
    _normalise_task_intelligence_state(state)
    return state


def _normalise_task_intelligence_state(state: dict[str, Any]) -> None:
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        state["taskIntelligence"] = copy.deepcopy(DEFAULT_STATE["taskIntelligence"])
        return
    if not isinstance(intelligence.get("recentSuccessfulRoutes"), list):
        intelligence["recentSuccessfulRoutes"] = []
    if not isinstance(intelligence.get("recentMisroutes"), list):
        intelligence["recentMisroutes"] = []
    if not isinstance(intelligence.get("recentClarifications"), list):
        intelligence["recentClarifications"] = []
    if not isinstance(intelligence.get("confirmedPlanPatterns"), list):
        intelligence["confirmedPlanPatterns"] = []
    if not isinstance(intelligence.get("rejectedPlanPatterns"), list):
        intelligence["rejectedPlanPatterns"] = []
    if not isinstance(intelligence.get("corrections"), list):
        intelligence["corrections"] = []
    if not isinstance(intelligence.get("capabilityQuality"), dict):
        intelligence["capabilityQuality"] = {}
    response_style = intelligence.get("responseStyle", {})
    if not isinstance(response_style, dict):
        response_style = {}
    response_style = {
        "length": str(response_style.get("length", "short") or "short")[:24] or "short",
        "directness": str(response_style.get("directness", "direct") or "direct")[:24] or "direct",
        "tone": str(response_style.get("tone", "professional") or "professional")[:24] or "professional",
    }
    intelligence["responseStyle"] = response_style
    intelligence["lastUpdatedAt"] = str(intelligence.get("lastUpdatedAt", "") or "").strip()[:80]


def _normalise_provider_state(state: dict[str, Any]) -> None:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        state["providers"] = copy.deepcopy(DEFAULT_STATE["providers"])
        return
    provider_defaults = copy.deepcopy(DEFAULT_STATE.get("providers", {}))
    provider_defaults = provider_defaults if isinstance(provider_defaults, dict) else {}
    for provider_id, default_value in provider_defaults.items():
        if provider_id in {"active", "routingPolicy", "defaultLocalModel", "defaultLocalRuntime", "fallbackToCloud"}:
            if provider_id not in providers:
                providers[provider_id] = copy.deepcopy(default_value)
            continue
        if not isinstance(default_value, dict):
            continue
        current_value = providers.get(provider_id, {})
        if not isinstance(current_value, dict):
            current_value = {}
        merged_value = copy.deepcopy(default_value)
        _deep_merge(merged_value, current_value)
        providers[provider_id] = merged_value
    active = str(providers.get("active", "") or "").strip()
    if not active:
        providers["active"] = "local"
    elif active not in KNOWN_PROVIDER_IDS:
        # Older UI builds could store a concrete model name in providers.active.
        # Keep the user's selected model, but route it through the local/Ollama adapter.
        local_cfg = providers.setdefault("local", {})
        ollama_cfg = providers.setdefault("ollama", {})
        if not isinstance(local_cfg, dict):
            local_cfg = {}
            providers["local"] = local_cfg
        if not isinstance(ollama_cfg, dict):
            ollama_cfg = {}
            providers["ollama"] = ollama_cfg
        local_cfg["defaultModel"] = active
        local_cfg["runtimeFamily"] = "ollama"
        ollama_cfg["defaultModel"] = active
        providers["active"] = "ollama"

    default_local_runtime = str(providers.get("defaultLocalRuntime", "") or "").strip().lower()
    if default_local_runtime not in {"ollama", "lmstudio", "llamacpp"}:
        providers["defaultLocalRuntime"] = "ollama"
    local_cfg = providers.get("local", {})
    if not isinstance(local_cfg, dict):
        local_cfg = {}
        providers["local"] = local_cfg
    runtime_family = str(local_cfg.get("runtimeFamily", "") or "").strip().lower()
    if runtime_family not in {"ollama", "lmstudio", "llamacpp"}:
        local_cfg["runtimeFamily"] = str(providers.get("defaultLocalRuntime", "ollama") or "ollama")


def _strip_provider_secrets_in_place(state: dict[str, Any]) -> None:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return
    secret_keys = {"apiKey", "api_key", "accessToken", "access_token", "secret", "token"}
    for provider_value in providers.values():
        if not isinstance(provider_value, dict):
            continue
        for key in list(provider_value.keys()):
            if key in secret_keys:
                provider_value.pop(key, None)


def _strip_provider_endpoints_in_place(state: dict[str, Any]) -> None:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return
    endpoint_keys = {"baseUrl", "base_url"}
    for provider_value in providers.values():
        if not isinstance(provider_value, dict):
            continue
        for key in endpoint_keys:
            if key in provider_value:
                provider_value[key] = ""


def _capture_provider_secrets_in_place(state: dict[str, Any]) -> None:
    providers = state.get("providers", {})
    if not isinstance(providers, dict):
        return
    for provider_id, provider_value in providers.items():
        if not isinstance(provider_value, dict):
            continue
        secret = str(
            provider_value.get("apiKey", "")
            or provider_value.get("api_key", "")
            or provider_value.get("accessToken", "")
            or provider_value.get("access_token", "")
            or provider_value.get("secret", "")
            or provider_value.get("token", "")
            or ""
        ).strip()
        if secret:
            _VOLATILE_PROVIDER_SECRETS[str(provider_id).strip().lower()] = secret


def volatile_provider_secrets() -> dict[str, str]:
    with _LOCK:
        return dict(_VOLATILE_PROVIDER_SECRETS)


def _strip_transport_secrets_in_place(state: dict[str, Any]) -> None:
    account = state.get("account")
    if isinstance(account, dict):
        for key in ("accessToken", "refreshToken"):
            if key in account:
                account[key] = ""

    runtime = state.get("runtime")
    if isinstance(runtime, dict):
        for key in ("runtimeToken", "deviceSecret", "connectionId"):
            if key in runtime:
                runtime[key] = ""

    pairing = state.get("pairing")
    if isinstance(pairing, dict):
        for key in ("pairingToken", "lastSessionId"):
            if key in pairing:
                pairing[key] = ""


def _normalise_mcp_server_state(state: dict[str, Any]) -> None:
    skills = state.get("skills", {})
    if not isinstance(skills, dict):
        state["skills"] = copy.deepcopy(DEFAULT_STATE["skills"])
        return
    active_skills = skills.get("activeSkills", [])
    if not isinstance(active_skills, list):
        skills["activeSkills"] = []
    else:
        skills["activeSkills"] = [
            str(item).strip()[:160]
            for item in active_skills
            if str(item).strip()
        ]
    tool_permissions = skills.get("toolPermissions", {})
    if not isinstance(tool_permissions, dict):
        skills["toolPermissions"] = {}
    else:
        skills["toolPermissions"] = {
            str(key).strip()[:160]: bool(value)
            for key, value in tool_permissions.items()
            if str(key).strip()
        }
    skills["defaultSkill"] = str(skills.get("defaultSkill", "") or "").strip()[:120]
    skills["toolSafety"] = str(skills.get("toolSafety", "balanced") or "balanced").strip()[:32] or "balanced"
    servers = skills.get("mcpServers", [])
    if not isinstance(servers, list):
        skills["mcpServers"] = []
    else:
        normalized: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in servers:
            if not isinstance(item, dict):
                continue
            server_id = " ".join(str(item.get("id", "") or "").split()).strip()[:80]
            name = " ".join(str(item.get("name", "") or "").split()).strip()[:120]
            command = str(item.get("command", "") or "").strip()[:500]
            if not server_id and not command and not name:
                continue
            if not server_id:
                server_id = f"mcp_{len(normalized) + 1}"
            if server_id in seen_ids:
                continue
            seen_ids.add(server_id)
            try:
                startup_timeout = max(3, min(120, int(item.get("startupTimeoutSec", 15) or 15)))
            except (TypeError, ValueError):
                startup_timeout = 15
            try:
                call_timeout = max(5, min(180, int(item.get("callTimeoutSec", 45) or 45)))
            except (TypeError, ValueError):
                call_timeout = 45
            normalized.append(
                {
                    "id": server_id,
                    "name": name or command or server_id,
                    "transport": "stdio",
                    "command": command,
                    "args": [
                        str(arg).strip()[:500]
                        for arg in (item.get("args", []) if isinstance(item.get("args"), list) else [])
                        if str(arg).strip()
                    ],
                    "cwd": str(item.get("cwd", "") or "").strip()[:500],
                    "enabled": bool(item.get("enabled", True)),
                    "startupTimeoutSec": startup_timeout,
                    "callTimeoutSec": call_timeout,
                }
            )
            if len(normalized) >= _MCP_SERVER_LIMIT:
                break
        skills["mcpServers"] = normalized
    usage = skills.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}
    recent_runs = usage.get("recentRuns", [])
    if not isinstance(recent_runs, list):
        recent_runs = []
    normalized_runs: list[dict[str, Any]] = []
    for item in recent_runs[:40]:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skillId", "") or "").strip()[:160]
        if not skill_id:
            continue
        normalized_runs.append(
            {
                "skillId": skill_id,
                "success": bool(item.get("success", False)),
                "source": str(item.get("source", "") or "").strip()[:80],
                "durationMs": max(0, int(item.get("durationMs", 0) or 0)),
                "at": str(item.get("at", "") or "").strip()[:80],
            }
        )
    skill_stats = usage.get("skillStats", {})
    if not isinstance(skill_stats, dict):
        skill_stats = {}
    normalized_stats: dict[str, dict[str, Any]] = {}
    for skill_id, item in skill_stats.items():
        key = str(skill_id).strip()[:160]
        if not key or not isinstance(item, dict):
            continue
        normalized_stats[key] = {
            "successCount": max(0, int(item.get("successCount", 0) or 0)),
            "failureCount": max(0, int(item.get("failureCount", 0) or 0)),
            "lastOkAt": str(item.get("lastOkAt", "") or "").strip()[:80],
            "lastFailedAt": str(item.get("lastFailedAt", "") or "").strip()[:80],
            "lastDurationMs": max(0, int(item.get("lastDurationMs", 0) or 0)),
        }
    skills["usage"] = {
        "recentRuns": normalized_runs,
        "skillStats": normalized_stats,
        "lastSuccessfulSkillId": str(usage.get("lastSuccessfulSkillId", "") or "").strip()[:160],
        "lastSuccessfulAt": str(usage.get("lastSuccessfulAt", "") or "").strip()[:80],
        "lastFailedSkillId": str(usage.get("lastFailedSkillId", "") or "").strip()[:160],
        "lastFailedAt": str(usage.get("lastFailedAt", "") or "").strip()[:80],
    }


def _normalise_local_indexing_state(state: dict[str, Any]) -> None:
    local_indexing = state.get("localIndexing", {})
    if not isinstance(local_indexing, dict):
        state["localIndexing"] = copy.deepcopy(DEFAULT_STATE["localIndexing"])
        local_indexing = state["localIndexing"]

    approved_roots = local_indexing.get("approvedRoots", [])
    if not isinstance(approved_roots, list):
        approved_roots = []
    normalized_roots: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(approved_roots):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()[:1200]
        if not path:
            continue
        dedupe_key = path.lower()
        if dedupe_key in seen_paths:
            continue
        seen_paths.add(dedupe_key)
        normalized_roots.append(
            {
                "path": path,
                "label": " ".join(str(item.get("label", "") or "").split()).strip()[:120]
                or Path(path).name
                or f"root_{index + 1}",
                "addedAt": str(item.get("addedAt", "") or item.get("added_at", "") or "").strip()[:80],
            }
        )
    local_indexing["approvedRoots"] = normalized_roots

    status = local_indexing.get("status", {})
    status = status if isinstance(status, dict) else {}
    stats = status.get("stats", {})
    stats = stats if isinstance(stats, dict) else {}
    local_indexing["status"] = {
        "available": bool(status.get("available", False)),
        "ready": bool(status.get("ready", False)),
        "version": str(status.get("version", "") or "").strip()[:40],
        "stats": {
            "rootCount": max(0, int(stats.get("rootCount", 0) or 0)),
            "indexedFileCount": max(0, int(stats.get("indexedFileCount", 0) or 0)),
            "lastScanAt": str(stats.get("lastScanAt", "") or "").strip()[:80],
        },
        "errorCode": str(status.get("errorCode", "") or "").strip()[:120],
    }

    permissions = state.get("permissions", {})
    if not isinstance(permissions, dict):
        permissions = {}
        state["permissions"] = permissions
    permissions["allow_computer_control"] = bool(permissions.get("allow_computer_control", False))
    permissions["allow_sensitive_operator_actions"] = bool(permissions.get("allow_sensitive_operator_actions", False))
    permissions["allow_file_indexing"] = bool(permissions.get("allow_file_indexing", False))

    runtime = state.get("runtime", {})
    if not isinstance(runtime, dict):
        runtime = {}
        state["runtime"] = runtime
    capability_states = runtime.get("capabilityStates", {})
    runtime["capabilityStates"] = capability_states if isinstance(capability_states, dict) else {}

    operator = state.get("operator", {})
    if not isinstance(operator, dict):
        operator = copy.deepcopy(DEFAULT_STATE["operator"])
        state["operator"] = operator
    operator["activeRunId"] = str(operator.get("activeRunId", "") or "").strip()[:80]
    operator["status"] = str(operator.get("status", "idle") or "idle").strip()[:64] or "idle"
    operator["abortRequested"] = bool(operator.get("abortRequested", False))
    operator["abortReason"] = str(operator.get("abortReason", "") or "").strip()[:80]
    operator["currentStepIndex"] = max(0, int(operator.get("currentStepIndex", 0) or 0))
    operator["lastObservationId"] = str(operator.get("lastObservationId", "") or "").strip()[:120]
    operator["lastStopReason"] = str(operator.get("lastStopReason", "") or "").strip()[:80]
    operator["lastCompletedAt"] = str(operator.get("lastCompletedAt", "") or "").strip()[:80]
    operator["operatorResolutionMode"] = str(operator.get("operatorResolutionMode", "") or "").strip()[:80]
    operator["lastTargetSource"] = str(operator.get("lastTargetSource", "") or "").strip()[:80]
    operator["lastVerificationSource"] = str(operator.get("lastVerificationSource", "") or "").strip()[:80]
    operator["lastTargetConfidence"] = max(0.0, min(float(operator.get("lastTargetConfidence", 0.0) or 0.0), 1.0))
    for key in ("operatorRuns", "operatorSteps", "screenObservations", "inputActions", "verificationResults"):
        if not isinstance(operator.get(key), list):
            operator[key] = []
    operator["lastUpdatedAt"] = str(operator.get("lastUpdatedAt", "") or "").strip()[:80]


def _derive_artifact_kind(path: str, mime_type: str, current_kind: str = "") -> str:
    normalized_kind = str(current_kind or "").strip().lower()
    if normalized_kind in {"image", "document", "audio", "other"}:
        return normalized_kind
    normalized_mime = str(mime_type or "").strip().lower()
    suffix = Path(str(path or "")).suffix.lower()
    if normalized_mime.startswith("image/") or suffix in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".gif",
        ".tif",
        ".tiff",
    }:
        return "image"
    if normalized_mime.startswith("audio/") or suffix in {
        ".wav",
        ".mp3",
        ".m4a",
        ".aac",
        ".ogg",
        ".flac",
        ".mp4",
        ".mpeg",
        ".webm",
    }:
        return "audio"
    if normalized_mime.startswith("text/") or normalized_mime in {
        "application/pdf",
        "application/json",
        "text/csv",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    } or suffix in {
        ".pdf",
        ".docx",
        ".doc",
        ".txt",
        ".md",
        ".markdown",
        ".json",
        ".csv",
        ".rtf",
        ".html",
        ".htm",
    }:
        return "document"
    return "other"


def normalize_selected_artifacts(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        name = " ".join(str(item.get("name", "") or "").split()).strip()
        mime_type = str(item.get("mimeType", "") or item.get("mime_type", "") or "").strip()[:160]
        if not path:
            continue
        dedupe_key = path.lower()
        if dedupe_key in seen_paths:
            continue
        seen_paths.add(dedupe_key)
        try:
            size_bytes = max(0, int(item.get("sizeBytes") or item.get("size_bytes") or 0))
        except (TypeError, ValueError):
            size_bytes = 0
        normalized.append(
            {
                "id": " ".join(str(item.get("id", "") or "").split()).strip()[:80] or f"artifact_{index + 1}",
                "name": (name or Path(path).name or "artifact")[:240],
                "path": path[:1200],
                "mimeType": mime_type,
                "sizeBytes": size_bytes,
                "kind": _derive_artifact_kind(path, mime_type, str(item.get("kind", "") or "")),
            }
        )
        if len(normalized) >= _ARTIFACT_SELECTION_LIMIT:
            break
    return normalized


def _normalise_composer_state(state: dict[str, Any]) -> None:
    composer = state.get("composer", {})
    if not isinstance(composer, dict):
        state["composer"] = copy.deepcopy(DEFAULT_STATE["composer"])
        return
    composer["selectedArtifacts"] = normalize_selected_artifacts(composer.get("selectedArtifacts", []))


def load_state() -> dict[str, Any]:
    with _LOCK:
        try:
            if STATE_PATH.exists():
                raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
            elif LEGACY_STATE_PATH.exists():
                raw = json.loads(LEGACY_STATE_PATH.read_text(encoding="utf-8"))
                CONFIG_DIR.mkdir(parents=True, exist_ok=True)
                STATE_PATH.write_text(
                    json.dumps(raw, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            else:
                return copy.deepcopy(DEFAULT_STATE)
        except Exception:
            return copy.deepcopy(DEFAULT_STATE)
        if not isinstance(raw, dict):
            return copy.deepcopy(DEFAULT_STATE)
        payload = _ensure_defaults(raw)
        _capture_provider_secrets_in_place(payload)
        _strip_provider_secrets_in_place(payload)
        return payload


def save_state(state: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        payload = _ensure_defaults(state)
        _capture_provider_secrets_in_place(payload)
        _strip_provider_secrets_in_place(payload)
        STATE_PATH.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return payload


def update_state(patch: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        state = load_state()
        _deep_merge(state, patch or {})
        state["updatedAt"] = state.get("updatedAt") or ""
        return save_state(state)


def recover_operator_state_on_boot() -> dict[str, Any]:
    with _LOCK:
        state = load_state()
        operator = state.get("operator", {})
        operator = operator if isinstance(operator, dict) else {}
        active_run_id = str(operator.get("activeRunId", "") or "").strip()
        status = str(operator.get("status", "") or "").strip().lower()
        if not active_run_id or status not in _ACTIVE_OPERATOR_STATUSES:
            return state
        operator_patch = {
            "activeRunId": "",
            "status": "stopped",
            "abortRequested": False,
            "abortReason": "",
            "lastStopReason": "runtime_restarted",
            "lastCompletedAt": _task_inbox_timestamp(),
            "lastUpdatedAt": _task_inbox_timestamp(),
        }
        _deep_merge(state, {"operator": operator_patch})
        runs = state.get("operator", {}).get("operatorRuns", [])
        if isinstance(runs, list) and runs:
            for item in runs:
                if not isinstance(item, dict):
                    continue
                if str(item.get("id", "") or "").strip() != active_run_id:
                    continue
                item["status"] = "stopped"
                item["stopReason"] = "runtime_restarted"
                item["completedAt"] = operator_patch["lastCompletedAt"]
                break
        state["updatedAt"] = state.get("updatedAt") or ""
        return save_state(state)


def list_conversations() -> list[dict[str, Any]]:
    state = load_state()
    conversations = state.get("conversation", {}).get("items", [])
    if not isinstance(conversations, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in conversations:
        if not isinstance(item, dict):
            continue
        if item.get("archived") is True:
            continue
        messages = item.get("messages", [])
        preview = ""
        if isinstance(item.get("preview"), str):
            preview = str(item.get("preview", "") or "").strip()
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                preview = str(
                    last.get("text", "") or last.get("content", "") or preview
                ).strip()
        summaries.append(
            {
                "id": str(item.get("id", "") or ""),
                "title": str(item.get("title", "") or ""),
                "updatedAt": str(item.get("updatedAt", "") or ""),
                "messageCount": int(
                    item.get("messageCount", len(messages) if isinstance(messages, list) else 0)
                    or 0
                ),
                "preview": preview[:120],
            }
        )
    summaries.sort(key=lambda row: (row["updatedAt"], row["id"]), reverse=True)
    return summaries


def list_archived_conversations() -> list[dict[str, Any]]:
    state = load_state()
    conversations = state.get("conversation", {}).get("items", [])
    if not isinstance(conversations, list):
        return []
    summaries: list[dict[str, Any]] = []
    for item in conversations:
        if not isinstance(item, dict) or item.get("archived") is not True:
            continue
        messages = item.get("messages", [])
        preview = ""
        if isinstance(item.get("preview"), str):
            preview = str(item.get("preview", "") or "").strip()
        if isinstance(messages, list) and messages:
            last = messages[-1]
            if isinstance(last, dict):
                preview = str(
                    last.get("text", "") or last.get("content", "") or preview
                ).strip()
        summaries.append(
            {
                "id": str(item.get("id", "") or ""),
                "title": str(item.get("title", "") or ""),
                "updatedAt": str(item.get("updatedAt", "") or ""),
                "messageCount": int(
                    item.get("messageCount", len(messages) if isinstance(messages, list) else 0)
                    or 0
                ),
                "preview": preview[:120],
            }
        )
    summaries.sort(key=lambda row: (row["updatedAt"], row["id"]), reverse=True)
    return summaries


def _generate_id(prefix: str) -> str:
    import time
    from uuid import uuid4

    return f"{prefix}_{int(time.time() * 1000)}_{uuid4().hex[:8]}"


def _bounded_prepend(items: list[Any], entry: Any, limit: int) -> list[Any]:
    payload = [copy.deepcopy(entry)]
    for item in items:
        payload.append(copy.deepcopy(item))
        if len(payload) >= limit:
            break
    return payload[:limit]


def _is_generic_title(value: str) -> bool:
    normalized = " ".join(str(value or "").split()).strip().lower()
    return normalized in {
        "",
        "yeni sohbet",
        "yeni konuşma",
        "new chat",
        "new conversation",
        "draft",
    }


_TITLE_STOPWORDS = {
    "a",
    "an",
    "and",
    "ayrıca",
    "beni",
    "benim",
    "bu",
    "da",
    "de",
    "diye",
    "for",
    "gibi",
    "için",
    "ile",
    "in",
    "is",
    "it",
    "kim",
    "kimi",
    "kimin",
    "what",
    "where",
    "why",
    "how",
    "mi",
    "mu",
    "mü",
    "mı",
    "ne",
    "neden",
    "niçin",
    "not",
    "of",
    "on",
    "or",
    "sen",
    "seni",
    "sana",
    "the",
    "to",
    "ve",
    "var",
    "yani",
    "ya",
    "ya da",
    "bir",
    "şu",
    "şunu",
    "şunun",
    "this",
    "that",
}


def _normalize_title_words(text: str) -> list[str]:
    words: list[str] = []
    for raw_word in str(text or "").split():
        word = re.sub(r"^[^\wçğıöşüÇĞİÖŞÜ]+|[^\wçğıöşüÇĞİÖŞÜ]+$", "", raw_word).strip()
        if not word:
            continue
        words.append(word)
    return words


def _derive_conversation_title(text: str) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if not cleaned:
        return ""
    words = _normalize_title_words(cleaned)
    if len(words) <= 6 and len(cleaned) <= 42:
        return cleaned
    significant_words = [word for word in words if word.lower() not in _TITLE_STOPWORDS]
    candidate_words = significant_words[:7] if significant_words else words[:7]
    if len(candidate_words) <= 1 and len(words) > 2:
        candidate_words = words[:6]
    candidate = " ".join(candidate_words).strip().rstrip(".,;:!?")
    if not candidate:
        candidate = " ".join(words[:6]).strip().rstrip(".,;:!?")
    if len(candidate) >= len(cleaned):
        return candidate[:80]
    return f"{candidate[:77].rstrip()}…"


def _derive_conversation_title_from_messages(messages: list[dict[str, Any]]) -> str:
    meaningful_texts: list[str] = []
    for item in messages:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role", "") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        meaningful_texts.append(text)
        if len(meaningful_texts) >= 2:
            break
    if not meaningful_texts:
        return ""
    if len(meaningful_texts[0].split()) <= 2 and len(meaningful_texts) > 1:
        return _derive_conversation_title(" ".join(meaningful_texts[:2]))
    return _derive_conversation_title(meaningful_texts[0])


def create_conversation(title: str = "") -> dict[str, Any]:
    with _LOCK:
        state = load_state()
        conversations = state.setdefault("conversation", {}).setdefault("items", [])
        conv_id = _generate_id("conv")
        item = {
            "id": conv_id,
            "title": (title or "").strip()[:80],
            "archived": False,
            "createdAt": "",
            "updatedAt": "",
            "messages": [],
        }
        conversations.insert(0, item)
        state["conversation"]["activeId"] = conv_id
        save_state(state)
        return item


def get_active_conversation() -> dict[str, Any] | None:
    state = load_state()
    active_id = str(state.get("conversation", {}).get("activeId", "") or "")
    if not active_id:
        return None
    for item in state.get("conversation", {}).get("items", []):
        if isinstance(item, dict) and str(item.get("id", "")) == active_id:
            return item
    return None


def get_conversation(conversation_id: str) -> dict[str, Any] | None:
    target_id = str(conversation_id or "").strip()
    if not target_id:
        return None
    state = load_state()
    for item in state.get("conversation", {}).get("items", []):
        if isinstance(item, dict) and str(item.get("id", "")) == target_id:
            return copy.deepcopy(item)
    return None


def append_message(conversation_id: str, role: str, text: str, extra: dict[str, Any] | None = None) -> dict[str, Any]:
    with _LOCK:
        state = load_state()
        conv = None
        for item in state.get("conversation", {}).get("items", []):
            if isinstance(item, dict) and str(item.get("id", "")) == conversation_id:
                conv = item
                break
        if conv is None:
            conv = create_conversation()
            conversation_id = str(conv["id"])
            state = load_state()
            for item in state.get("conversation", {}).get("items", []):
                if isinstance(item, dict) and str(item.get("id", "")) == conversation_id:
                    conv = item
                    break
        messages = conv.setdefault("messages", [])
        normalized_text = str(text or "").strip()
        message = {
            "id": _generate_id("msg"),
            "sessionId": conversation_id,
            "role": role,
            "text": text,
            "content": normalized_text,
            "status": "completed",
            "createdAt": _task_inbox_timestamp(),
        }
        if extra:
            message.update(extra)
        message["sessionId"] = str(message.get("sessionId", "") or conversation_id)
        message["content"] = str(message.get("content", "") or message.get("text", "") or "")
        if not isinstance(message.get("blocks"), list):
            block_text = str(message.get("content", "") or "").strip()
            if block_text and role in {"assistant", "system", "tool"}:
                message["blocks"] = [{"type": "text", "markdown": block_text, "version": 1}]
        messages.append(message)
        conv["updatedAt"] = message["id"]
        current_title = str(conv.get("title", "") or "").strip()
        if _is_generic_title(current_title):
            summary_source = _derive_conversation_title_from_messages(messages)
            if summary_source:
                conv["title"] = summary_source
        state["conversation"]["activeId"] = conversation_id
        save_state(state)
        return message


def update_conversation_title(conversation_id: str, title: str) -> None:
    with _LOCK:
        state = load_state()
        for item in state.get("conversation", {}).get("items", []):
            if isinstance(item, dict) and str(item.get("id", "")) == conversation_id:
                item["title"] = (title or "").strip()[:80]
                save_state(state)
                return


def archive_conversation(conversation_id: str, archived: bool = True) -> dict[str, Any] | None:
    target_id = str(conversation_id or "").strip()
    if not target_id:
        return None
    with _LOCK:
        state = load_state()
        conversations = state.get("conversation", {}).get("items", [])
        if not isinstance(conversations, list):
            return None
        found: dict[str, Any] | None = None
        for item in conversations:
            if isinstance(item, dict) and str(item.get("id", "")) == target_id:
                item["archived"] = bool(archived)
                found = copy.deepcopy(item)
                break
        if found is None:
            return None
        if archived and str(state.get("conversation", {}).get("activeId", "") or "") == target_id:
            fallback = next(
                (
                    str(item.get("id", "") or "")
                    for item in conversations
                    if isinstance(item, dict) and item.get("archived") is not True and str(item.get("id", "") or "") != target_id
                ),
                "",
            )
            state.setdefault("conversation", {})["activeId"] = fallback
        elif not archived and not str(state.get("conversation", {}).get("activeId", "") or "").strip():
            state.setdefault("conversation", {})["activeId"] = target_id
        save_state(state)
        return found


def delete_conversation(conversation_id: str) -> dict[str, Any] | None:
    target_id = str(conversation_id or "").strip()
    if not target_id:
        return None
    with _LOCK:
        state = load_state()
        conversation_state = state.setdefault("conversation", {})
        conversations = conversation_state.get("items", [])
        if not isinstance(conversations, list):
            return None
        removed: dict[str, Any] | None = None
        updated: list[dict[str, Any]] = []
        for item in conversations:
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "") or "") == target_id:
                removed = copy.deepcopy(item)
                continue
            updated.append(item)
        if removed is None:
            return None
        conversation_state["items"] = updated
        active_id = str(conversation_state.get("activeId", "") or "").strip()
        if active_id == target_id:
            next_active = next(
                (
                    str(item.get("id", "") or "")
                    for item in updated
                    if isinstance(item, dict) and item.get("archived") is not True
                ),
                "",
            )
            if not next_active:
                next_active = next((str(item.get("id", "") or "") for item in updated), "")
            conversation_state["activeId"] = next_active
        save_state(state)
        return removed


def save_pending_plan(plan: dict[str, Any]) -> dict[str, Any]:
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        plans = intelligence.setdefault("pendingPlans", [])
        if not isinstance(plans, list):
            plans = []
            intelligence["pendingPlans"] = plans
        stored = copy.deepcopy(plan)
        if not str(stored.get("id", "") or "").strip():
            stored["id"] = _generate_id("plan")
        intelligence["pendingPlans"] = _bounded_prepend(plans, stored, _PENDING_PLAN_LIMIT)
        save_state(state)
        return stored


def get_pending_plan(plan_id: str) -> dict[str, Any] | None:
    state = load_state()
    plans = state.get("taskIntelligence", {}).get("pendingPlans", [])
    if not isinstance(plans, list):
        return None
    for item in plans:
        if isinstance(item, dict) and str(item.get("id", "") or "") == str(plan_id or ""):
            return copy.deepcopy(item)
    return None


def latest_pending_plan(conversation_id: str = "") -> dict[str, Any] | None:
    target_conversation_id = str(conversation_id or "").strip()
    state = load_state()
    plans = state.get("taskIntelligence", {}).get("pendingPlans", [])
    if not isinstance(plans, list):
        return None
    for item in plans:
        if not isinstance(item, dict):
            continue
        if target_conversation_id and str(item.get("conversationId", "") or "").strip() != target_conversation_id:
            continue
        return copy.deepcopy(item)
    return None


def remove_pending_plan(plan_id: str) -> None:
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        plans = intelligence.get("pendingPlans", [])
        if not isinstance(plans, list):
            intelligence["pendingPlans"] = []
            save_state(state)
            return
        intelligence["pendingPlans"] = [
            copy.deepcopy(item)
            for item in plans
            if not (isinstance(item, dict) and str(item.get("id", "") or "") == str(plan_id or ""))
        ]
        save_state(state)


def revise_pending_plan(plan_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(updates, dict):
        return None
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        plans = intelligence.get("pendingPlans", [])
        if not isinstance(plans, list):
            return None
        revised: dict[str, Any] | None = None
        for index, item in enumerate(plans):
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "") or "").strip() != str(plan_id or "").strip():
                continue
            revised = copy.deepcopy(item)
            _deep_merge(revised, copy.deepcopy(updates))
            plans[index] = revised
            break
        if revised is None:
            return None
        intelligence["pendingPlans"] = plans
        save_state(state)
        return revised


def sync_task_inbox(
    items: list[dict[str, Any]],
    *,
    pending_count: int | None = None,
    active_count: int | None = None,
    last_synced_at: str = "",
) -> dict[str, Any]:
    normalized_items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        normalized = _normalize_task_item(item)
        task_id = normalized["id"]
        if not task_id or task_id in seen_ids:
            continue
        seen_ids.add(task_id)
        normalized_items.append(normalized)
        if len(normalized_items) >= _TASK_INBOX_LIMIT:
            break
    normalized_items = _sort_task_items(normalized_items)[:_TASK_INBOX_LIMIT]
    counted_pending, counted_active = _recount_task_inbox(normalized_items)
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        links = inbox.get("links", [])
        if not isinstance(links, list):
            links = []
        inbox["items"] = normalized_items
        inbox["pendingCount"] = counted_pending if pending_count is None else max(0, int(pending_count))
        inbox["activeCount"] = counted_active if active_count is None else max(0, int(active_count))
        inbox["lastSyncedAt"] = str(last_synced_at or _task_inbox_timestamp())
        inbox["links"] = links[:_TASK_LINK_LIMIT]
        save_state(state)
        return copy.deepcopy(inbox)


def upsert_task_inbox_item(task: dict[str, Any], *, last_synced_at: str = "") -> dict[str, Any]:
    normalized = _normalize_task_item(task)
    task_id = normalized["id"]
    if not task_id:
        return {}
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        items = inbox.get("items", [])
        if not isinstance(items, list):
            items = []
        updated_items: list[dict[str, Any]] = []
        found = False
        for item in items:
            if not isinstance(item, dict):
                continue
            if str(item.get("id", "") or "") == task_id:
                updated_items.append(_merge_task_item(item, normalized))
                found = True
            else:
                updated_items.append(_normalize_task_item(item))
        if not found:
            updated_items.append(normalized)
        updated_items = _sort_task_items(updated_items)[:_TASK_INBOX_LIMIT]
        counted_pending, counted_active = _recount_task_inbox(updated_items)
        inbox["items"] = updated_items
        inbox["pendingCount"] = counted_pending
        inbox["activeCount"] = counted_active
        inbox["lastSyncedAt"] = str(last_synced_at or _task_inbox_timestamp())
        links = inbox.get("links", [])
        if not isinstance(links, list):
            links = []
        normalized_status = str(normalized.get("status", "") or "").strip()
        terminal_status = normalized_status in {"completed", "failed", "canceled"}
        removed_pending_plan_ids: set[str] = set()
        next_links: list[dict[str, Any]] = []
        for item in links:
            if not isinstance(item, dict):
                continue
            copied = copy.deepcopy(item)
            if str(copied.get("taskId", "") or "") == task_id:
                if terminal_status:
                    pending_plan_id = str(copied.get("pendingPlanId", "") or "").strip()
                    if pending_plan_id:
                        removed_pending_plan_ids.add(pending_plan_id)
                    continue
                copied["status"] = normalized_status or str(copied.get("status", "") or "")
                copied["updatedAt"] = _task_inbox_timestamp()
            next_links.append(copied)
        inbox["links"] = next_links[:_TASK_LINK_LIMIT]
        if removed_pending_plan_ids:
            intelligence = state.setdefault("taskIntelligence", {})
            plans = intelligence.get("pendingPlans", [])
            if isinstance(plans, list):
                intelligence["pendingPlans"] = [
                    copy.deepcopy(item)
                    for item in plans
                    if not (
                        isinstance(item, dict)
                        and str(item.get("id", "") or "").strip() in removed_pending_plan_ids
                    )
                ]
        save_state(state)
        return copy.deepcopy(
            next((item for item in updated_items if str(item.get("id", "") or "") == task_id), normalized)
        )


def reconcile_task_inbox(
    active_task_ids: set[str],
    *,
    last_synced_at: str = "",
) -> dict[str, Any]:
    normalized_active_ids = {
        str(task_id or "").strip()
        for task_id in active_task_ids
        if str(task_id or "").strip()
    }
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        items = inbox.get("items", [])
        if not isinstance(items, list):
            items = []
        links = inbox.get("links", [])
        link_by_task_id: dict[str, dict[str, Any]] = {}
        if isinstance(links, list):
            for item in links:
                if not isinstance(item, dict):
                    continue
                task_id = str(item.get("taskId", "") or "").strip()
                if task_id:
                    link_by_task_id[task_id] = copy.deepcopy(item)
        verified_at = str(last_synced_at or _task_inbox_timestamp())
        reconciled: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            normalized = _normalize_task_item(item)
            task_id = normalized["id"]
            status = normalized["status"]
            if task_id in normalized_active_ids:
                normalized["lastVerifiedAt"] = verified_at
                normalized["lastRemoteStatus"] = status
                reconciled.append(normalized)
                continue
            if status not in _ACTIVE_TASK_STATUSES:
                reconciled.append(normalized)
                continue
            link = link_by_task_id.get(task_id, {})
            link_status = str(link.get("status", "") or "").strip()
            if status == "waiting_approval" or link_status == "waiting_approval":
                normalized["status"] = "waiting_approval"
                normalized["lastVerifiedAt"] = verified_at
                normalized["lastRemoteStatus"] = "waiting_approval"
                reconciled.append(normalized)
                continue
            last_remote_status = str(normalized.get("lastRemoteStatus", "") or "").strip()
            if last_remote_status in {"completed", "failed", "canceled"}:
                normalized["status"] = last_remote_status
            else:
                normalized["status"] = "unknown"
            normalized["lastVerifiedAt"] = verified_at
            reconciled.append(normalized)
        reconciled = _sort_task_items(reconciled)[:_TASK_INBOX_LIMIT]
        counted_pending, counted_active = _recount_task_inbox(reconciled)
        inbox["items"] = reconciled
        inbox["pendingCount"] = counted_pending
        inbox["activeCount"] = counted_active
        inbox["lastSyncedAt"] = verified_at
        save_state(state)
        return copy.deepcopy(inbox)


def get_task_inbox_item(task_id: str) -> dict[str, Any] | None:
    target_task_id = str(task_id or "").strip()
    if not target_task_id:
        return None
    state = load_state()
    items = state.get("taskInbox", {}).get("items", [])
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and str(item.get("id", "") or "") == target_task_id:
            return copy.deepcopy(item)
    return None


def get_task_inbox() -> dict[str, Any]:
    state = load_state()
    inbox = state.get("taskInbox", {})
    return copy.deepcopy(inbox) if isinstance(inbox, dict) else copy.deepcopy(DEFAULT_STATE["taskInbox"])


def save_remote_task_link(
    task_id: str,
    pending_plan_id: str,
    conversation_id: str,
    *,
    title: str = "",
    status: str = "waiting_approval",
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    normalized_plan_id = str(pending_plan_id or "").strip()
    normalized_conversation_id = str(conversation_id or "").strip()
    if not normalized_task_id or not normalized_plan_id:
        return {}
    stored = {
        "taskId": normalized_task_id,
        "pendingPlanId": normalized_plan_id,
        "conversationId": normalized_conversation_id,
        "title": " ".join(str(title or "").split())[:200],
        "status": str(status or "waiting_approval").strip()[:64] or "waiting_approval",
        "updatedAt": _task_inbox_timestamp(),
    }
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        links = inbox.get("links", [])
        if not isinstance(links, list):
            links = []
        next_links: list[dict[str, Any]] = [stored]
        for item in links:
            if not isinstance(item, dict):
                continue
            if str(item.get("taskId", "") or "") == normalized_task_id:
                continue
            next_links.append(copy.deepcopy(item))
            if len(next_links) >= _TASK_LINK_LIMIT:
                break
        inbox["links"] = next_links[:_TASK_LINK_LIMIT]
        save_state(state)
        return stored


def save_runtime_dispatch_link(
    task_id: str,
    lease_id: str,
    *,
    title: str = "",
    status: str = "accepted",
    execution_state: str = "accepted",
    transport: str = "websocket",
    accepted_at: str = "",
) -> dict[str, Any]:
    normalized_task_id = str(task_id or "").strip()
    normalized_lease_id = str(lease_id or "").strip()
    if not normalized_task_id or not normalized_lease_id:
        return {}
    stored = {
        "taskId": normalized_task_id,
        "pendingPlanId": "",
        "conversationId": "",
        "title": " ".join(str(title or "").split())[:200],
        "status": str(status or "accepted").strip()[:64] or "accepted",
        "executionState": str(execution_state or "accepted").strip()[:64] or "accepted",
        "transport": str(transport or "websocket").strip()[:32] or "websocket",
        "leaseId": normalized_lease_id[:120],
        "acceptedAt": str(accepted_at or _task_inbox_timestamp()).strip()[:80],
        "dispatchAckAt": "",
        "updatedAt": _task_inbox_timestamp(),
    }
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        links = inbox.get("links", [])
        if not isinstance(links, list):
            links = []
        next_links: list[dict[str, Any]] = [stored]
        for item in links:
            if not isinstance(item, dict):
                continue
            if str(item.get("taskId", "") or "") == normalized_task_id:
                continue
            next_links.append(copy.deepcopy(item))
            if len(next_links) >= _TASK_LINK_LIMIT:
                break
        inbox["links"] = next_links[:_TASK_LINK_LIMIT]
        save_state(state)
        return copy.deepcopy(stored)


def get_remote_task_link(task_id: str) -> dict[str, Any] | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id:
        return None
    state = load_state()
    links = state.get("taskInbox", {}).get("links", [])
    if not isinstance(links, list):
        return None
    for item in links:
        if isinstance(item, dict) and str(item.get("taskId", "") or "") == normalized_task_id:
            return copy.deepcopy(item)
    return None


def get_runtime_dispatch_link(task_id: str) -> dict[str, Any] | None:
    link = get_remote_task_link(task_id)
    if not isinstance(link, dict):
        return None
    if not str(link.get("leaseId", "") or "").strip():
        return None
    return link


def update_remote_task_link(task_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    normalized_task_id = str(task_id or "").strip()
    if not normalized_task_id or not isinstance(updates, dict):
        return None
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        links = inbox.get("links", [])
        if not isinstance(links, list):
            return None
        updated: dict[str, Any] | None = None
        next_links: list[dict[str, Any]] = []
        for item in links:
            if not isinstance(item, dict):
                continue
            copied = copy.deepcopy(item)
            if str(copied.get("taskId", "") or "") == normalized_task_id:
                copied.update(copy.deepcopy(updates))
                copied["updatedAt"] = _task_inbox_timestamp()
                updated = copied
            next_links.append(copied)
        if updated is None:
            return None
        inbox["links"] = next_links[:_TASK_LINK_LIMIT]
        save_state(state)
        return updated


def mark_runtime_dispatch_acked(
    task_id: str,
    lease_id: str,
    *,
    acked_at: str = "",
    status: str = "acked",
) -> dict[str, Any] | None:
    normalized_task_id = str(task_id or "").strip()
    normalized_lease_id = str(lease_id or "").strip()
    if not normalized_task_id or not normalized_lease_id:
        return None
    current = get_runtime_dispatch_link(normalized_task_id)
    if not isinstance(current, dict):
        return None
    if str(current.get("leaseId", "") or "").strip() != normalized_lease_id:
        return None
    return update_remote_task_link(
        normalized_task_id,
        {
            "status": str(status or "acked").strip()[:64] or "acked",
            "executionState": "acked",
            "dispatchAckAt": str(acked_at or _task_inbox_timestamp()).strip()[:80],
            "leaseId": normalized_lease_id[:120],
        },
    )


def remove_remote_task_link(task_id: str) -> None:
    normalized_task_id = str(task_id or "").strip()
    with _LOCK:
        state = load_state()
        inbox = state.setdefault("taskInbox", {})
        links = inbox.get("links", [])
        if not isinstance(links, list):
            inbox["links"] = []
            save_state(state)
            return
        inbox["links"] = [
            copy.deepcopy(item)
            for item in links
            if not (isinstance(item, dict) and str(item.get("taskId", "") or "") == normalized_task_id)
        ][: _TASK_LINK_LIMIT]
        save_state(state)


def record_recent_route(
    *,
    query: str,
    intent: str,
    capability: str,
    confidence: float,
    args: dict[str, Any] | None = None,
    conversation_id: str = "",
    confirmed: bool = False,
    corrected_to: str = "",
) -> None:
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        routes = intelligence.setdefault("recentSuccessfulRoutes", [])
        if not isinstance(routes, list):
            routes = []
        entry = {
            "query": " ".join(str(query or "").split())[:160],
            "intent": str(intent or "").strip()[:80],
            "capability": str(capability or "").strip()[:80],
            "confidence": round(float(confidence or 0.0), 3),
            "args": copy.deepcopy(args) if isinstance(args, dict) else {},
            "conversationId": str(conversation_id or "").strip()[:80],
            "confirmed": bool(confirmed),
            "correctedTo": str(corrected_to or "").strip()[:80],
        }
        intelligence["recentSuccessfulRoutes"] = _bounded_prepend(routes, entry, _RECENT_ROUTE_LIMIT)
        _touch_task_intelligence(intelligence)
        save_state(state)


def record_confirmed_plan_pattern(*, query: str, intent: str, capability: str) -> None:
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        patterns = intelligence.setdefault("confirmedPlanPatterns", [])
        if not isinstance(patterns, list):
            patterns = []
        entry = {
            "query": " ".join(str(query or "").split())[:160],
            "intent": str(intent or "").strip()[:80],
            "capability": str(capability or "").strip()[:80],
        }
        intelligence["confirmedPlanPatterns"] = _bounded_prepend(patterns, entry, _CONFIRMED_PLAN_LIMIT)
        _touch_task_intelligence(intelligence)
        save_state(state)


def record_route_outcome(
    *,
    outcome: str,
    query: str,
    intent: str,
    capability: str,
    args: dict[str, Any] | None = None,
    conversation_id: str = "",
    question: str = "",
    corrected_to: str = "",
) -> None:
    normalized_outcome = str(outcome or "").strip().lower()
    if normalized_outcome not in {"correct", "clarified", "revised", "rejected", "misrouted"}:
        return
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        if not isinstance(intelligence, dict):
            intelligence = copy.deepcopy(DEFAULT_STATE["taskIntelligence"])
            state["taskIntelligence"] = intelligence
        entry = _quality_entry_payload(
            query=query,
            intent=intent,
            capability=capability,
            args=args,
            conversation_id=conversation_id,
            question=question,
            corrected_to=corrected_to,
            outcome=normalized_outcome,
        )
        if normalized_outcome == "clarified":
            items = intelligence.setdefault("recentClarifications", [])
            if not isinstance(items, list):
                items = []
            intelligence["recentClarifications"] = _bounded_prepend(
                items,
                entry,
                _CLARIFICATION_PATTERN_LIMIT,
            )
        elif normalized_outcome == "misrouted":
            items = intelligence.setdefault("recentMisroutes", [])
            if not isinstance(items, list):
                items = []
            intelligence["recentMisroutes"] = _bounded_prepend(items, entry, _MISROUTE_LIMIT)
        elif normalized_outcome == "rejected":
            items = intelligence.setdefault("rejectedPlanPatterns", [])
            if not isinstance(items, list):
                items = []
            intelligence["rejectedPlanPatterns"] = _bounded_prepend(
                items,
                entry,
                _REJECTED_PLAN_LIMIT,
            )
        elif normalized_outcome == "revised":
            items = intelligence.setdefault("corrections", [])
            if not isinstance(items, list):
                items = []
            intelligence["corrections"] = _bounded_prepend(items, entry, _CORRECTION_LIMIT)
        _update_capability_quality(
            intelligence,
            capability=capability,
            outcome=normalized_outcome,
        )
        _touch_task_intelligence(intelligence)
        save_state(state)


def increment_clarification_count() -> None:
    with _LOCK:
        state = load_state()
        intelligence = state.setdefault("taskIntelligence", {})
        current = intelligence.get("clarificationCount", 0)
        try:
            intelligence["clarificationCount"] = int(current or 0) + 1
        except (TypeError, ValueError):
            intelligence["clarificationCount"] = 1
        _touch_task_intelligence(intelligence)
        save_state(state)


def get_task_intelligence_status() -> dict[str, Any]:
    state = load_state()
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        intelligence = copy.deepcopy(DEFAULT_STATE["taskIntelligence"])
    quality = intelligence.get("capabilityQuality", {})
    quality = quality if isinstance(quality, dict) else {}
    return {
        "available": True,
        "recentSuccessCount": len(
            intelligence.get("recentSuccessfulRoutes", [])
            if isinstance(intelligence.get("recentSuccessfulRoutes", []), list)
            else []
        ),
        "recentMisrouteCount": len(
            intelligence.get("recentMisroutes", [])
            if isinstance(intelligence.get("recentMisroutes", []), list)
            else []
        ),
        "recentClarificationCount": len(
            intelligence.get("recentClarifications", [])
            if isinstance(intelligence.get("recentClarifications", []), list)
            else []
        ),
        "clarificationCount": int(intelligence.get("clarificationCount", 0) or 0),
        "trackedCapabilityCount": len(quality),
        "responseStyle": copy.deepcopy(intelligence.get("responseStyle", {})),
        "lastUpdatedAt": str(intelligence.get("lastUpdatedAt", "") or ""),
    }


def capability_quality_snapshot(capability: str) -> dict[str, Any]:
    normalized_capability = str(capability or "").strip()
    if not normalized_capability:
        return {
            "successes": 0,
            "clarifications": 0,
            "revisions": 0,
            "rejections": 0,
            "misroutes": 0,
            "lastSeenAt": "",
        }
    state = load_state()
    intelligence = state.get("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        return {
            "successes": 0,
            "clarifications": 0,
            "revisions": 0,
            "rejections": 0,
            "misroutes": 0,
            "lastSeenAt": "",
        }
    quality = intelligence.get("capabilityQuality", {})
    if not isinstance(quality, dict):
        return {
            "successes": 0,
            "clarifications": 0,
            "revisions": 0,
            "rejections": 0,
            "misroutes": 0,
            "lastSeenAt": "",
        }
    payload = quality.get(normalized_capability, {})
    if not isinstance(payload, dict):
        payload = {}
    return {
        "successes": int(payload.get("successes", 0) or 0),
        "clarifications": int(payload.get("clarifications", 0) or 0),
        "revisions": int(payload.get("revisions", 0) or 0),
        "rejections": int(payload.get("rejections", 0) or 0),
        "misroutes": int(payload.get("misroutes", 0) or 0),
        "lastSeenAt": str(payload.get("lastSeenAt", "") or ""),
    }


def recent_route_match(query: str) -> dict[str, Any] | None:
    normalized = _normalize_route_query(query)
    if not normalized:
        return None
    state = load_state()
    routes = state.get("taskIntelligence", {}).get("recentSuccessfulRoutes", [])
    if not isinstance(routes, list):
        return None
    best: dict[str, Any] | None = None
    best_score = 0.0
    for item in routes:
        if not isinstance(item, dict):
            continue
        candidate = _normalize_route_query(str(item.get("query", "") or ""))
        if not candidate:
            continue
        if candidate == normalized:
            return copy.deepcopy(item)
        score = difflib.SequenceMatcher(None, normalized, candidate).ratio()
        if normalized in candidate or candidate in normalized:
            score = max(score, 0.82)
        if score > best_score:
            best_score = score
            best = item
    if best_score >= 0.72 and isinstance(best, dict):
        return copy.deepcopy(best)
    return None


def latest_recent_route(conversation_id: str = "") -> dict[str, Any] | None:
    target_conversation_id = str(conversation_id or "").strip()
    state = load_state()
    routes = state.get("taskIntelligence", {}).get("recentSuccessfulRoutes", [])
    if not isinstance(routes, list):
        return None
    for item in routes:
        if not isinstance(item, dict):
            continue
        if target_conversation_id and str(item.get("conversationId", "") or "").strip() != target_conversation_id:
            continue
        return copy.deepcopy(item)
    return None


def get_selected_artifacts() -> list[dict[str, Any]]:
    state = load_state()
    composer = state.get("composer", {})
    if not isinstance(composer, dict):
        return []
    return normalize_selected_artifacts(composer.get("selectedArtifacts", []))


def artifact_selection_status() -> dict[str, Any]:
    selected = get_selected_artifacts()
    active_kinds = sorted(
        {
            str(item.get("kind", "") or "").strip()
            for item in selected
            if isinstance(item, dict) and str(item.get("kind", "") or "").strip()
        }
    )
    return {
        "selectedCount": len(selected),
        "activeKinds": active_kinds,
    }


def snapshot() -> dict[str, Any]:
    state = load_state()
    return state


def public_snapshot(state: dict[str, Any] | None = None) -> dict[str, Any]:
    payload = copy.deepcopy(state if isinstance(state, dict) else load_state())
    _strip_provider_secrets_in_place(payload)
    _strip_provider_endpoints_in_place(payload)
    _strip_transport_secrets_in_place(payload)
    return payload
