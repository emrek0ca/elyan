import asyncio
import importlib.util
import inspect
import time
import json
import os
import re
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlparse
from aiohttp import web, WSMsgType, WSCloseCode
from types import SimpleNamespace
from typing import Any, Optional, Set
from cli.onboard import _check_macos_permissions, is_setup_complete, mark_setup_complete
from .router import GatewayRouter
from .response import UnifiedResponse
from core.scheduler.cron_engine import get_cron_engine
from core.scheduler.heartbeat import HeartbeatManager
from core.scheduler.routine_engine import routine_engine
from core.skills.manager import skill_manager
from core.skills.registry import skill_registry
from core.subscription import subscription_manager
from core.quota import quota_manager
from core.task_brain import task_brain
from core.away_mode import away_task_registry
from core.proactive.intervention import get_intervention_manager
from core.model_catalog import default_model_for_provider
from core.tool_usage import get_tool_usage_snapshot
from core.runtime_policy import get_runtime_policy_resolver
from core.user_profile import get_user_profile_store
from core.ml import get_model_runtime
from core.personalization import get_personalization_manager
from core.reliability import get_outcome_store, get_regression_evaluator
from core.dependencies import get_dependency_runtime
from core.learning_control import get_learning_control_plane
from core.intake.task_extraction import compact_text as _shared_compact_text
from core.intake.task_extraction import extract_task_summary as _shared_extract_task_summary
from core.intake.task_extraction import normalize_intake_source as _shared_normalize_intake_source
from core.autopilot import get_autopilot
from core.runtime_control import get_runtime_control_plane
from core.operator_control_plane import get_operator_control_plane
from core.runtime import (
    EMRE_WORKFLOW_PRESETS,
    list_emre_workflow_reports,
    load_latest_benchmark_summary,
    run_emre_workflow_preset,
)
from core.project_packs import build_pack_overview, normalize_pack
from core.confidence import coerce_confidence
from core.mission_control import get_mission_runtime
from core.storage_paths import resolve_elyan_data_dir, resolve_runs_root
from core.persistence.runtime_db import get_runtime_database
from core.security.ingress_guard import blocked_ingress_text, inspect_ingress
from core.gateway.adapters.whatsapp_bridge import (
    BRIDGE_HOST,
    DEFAULT_BRIDGE_PORT,
    BridgeRuntimeError,
    bridge_health,
    build_bridge_url,
    default_session_dir,
    ensure_bridge_runtime,
    generate_bridge_token,
    start_bridge_process,
    wait_for_bridge,
)
from elyan.dashboard.routes.trace import render_trace_page
from elyan.verifier.evidence import build_trace_bundle, resolve_evidence_path
from core.text_artifacts import existing_text_path
from core.version import APP_VERSION, RUNTIME_PROTOCOL_VERSION
from core.compliance.audit_trail import audit_trail
from core.execution_guard import ExecutionCheck, get_execution_guard
from core.feature_flags import get_feature_flag_registry
from core.observability.logger import get_structured_logger
from core.observability.trace_context import (
    activate_trace_context,
    apply_trace_headers,
    build_trace_context,
    get_trace_context,
    reset_trace_context,
)
from config.elyan_config import elyan_config
from security.tool_policy import tool_policy
from security.keychain import KeychainManager
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("gateway_server")
slog = get_structured_logger("gateway_server")

# Global WebSocket client registry for dashboard push
_dashboard_ws_clients: Set[web.WebSocketResponse] = set()
_activity_log: list = []  # Rolling buffer of last 50 events
_tool_event_log: list = []  # Rolling buffer of last 200 tool events
_cowork_event_log: list = []  # Rolling buffer of last 200 cowork events
_start_time: float = time.time()
_AUTH_FAILURE_ATTEMPTS: dict[str, list[float]] = {}
_AUTH_RATE_LIMIT_WINDOW_SECONDS = 600.0
_AUTH_RATE_LIMIT_MAX_FAILURES = 10
_DASHBOARD_WS_AUTH_TIMEOUT_SECONDS = 5.0
_UPLOAD_MAX_BYTES = 25 * 1024 * 1024
_UPLOAD_ALLOWED_MIME_TYPES = {
    "application/json",
    "application/pdf",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "audio/mpeg",
    "audio/ogg",
    "audio/wav",
    "audio/webm",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/webp",
    "text/csv",
    "text/markdown",
    "text/plain",
}
_tool_health_cache: dict = {
    "ts": 0.0,
    "probe": False,
    "items": {},
    "summary": {},
}
_recent_runs_cache: dict[str, Any] = {
    "ts": 0.0,
    "signature": (),
    "limit": 0,
    "items": [],
}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}
_ADMIN_READ_PATHS = {
    "/api/config",
    "/api/logs",
    "/api/security/events",
    "/api/security/pending",
    "/api/v1/security/events",
    "/api/v1/security/summary",
    "/api/v1/learning/summary",
    "/api/v1/approvals/pending",
    "/api/v1/privacy/summary",
    "/api/v1/privacy/export",
    "/api/v1/privacy/learning/stats",
    "/api/v1/privacy/learning/global",
    "/api/v1/mobile-dispatch/sessions",
    "/api/privacy/export",
    "/api/privacy/delete",
    "/api/interventions",
    "/api/tool-requests",
    "/api/tool-requests/stats",
    "/api/tool-events",
    "/api/integrations/accounts",
    "/api/integrations/traces",
    "/api/integrations/summary",
    "/api/v1/cowork/home",
    "/api/v1/cowork/threads",
    "/api/v1/billing/workspace",
    "/api/v1/billing/usage",
    "/api/v1/billing/entitlements",
    "/api/v1/billing/plans",
    "/api/v1/billing/credits",
    "/api/v1/billing/ledger",
    "/api/v1/billing/events",
    "/api/v1/billing/profile",
    "/api/v1/billing/reconcile-usage",
    "/api/v1/connectors",
    "/api/v1/connectors/accounts",
    "/api/v1/connectors/traces",
    "/api/v1/connectors/health",
    "/api/v1/operator/preview",
    "/api/autopilot/status",
}
_LOCAL_DASHBOARD_WRITE_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/bootstrap-owner",
    "/api/missions",
    "/api/missions/approvals/resolve",
    "/api/missions/skills/save",
    "/api/v1/cowork/threads",
    "/api/channels/upsert",
    "/api/channels/toggle",
    "/api/channels/test",
    "/api/channels/sync",
    "/api/channels/pair/start",
    "/api/v1/billing/checkout-session",
    "/api/v1/billing/portal-session",
    "/api/v1/billing/webhooks/stripe",
    "/api/v1/billing/checkout/init",
    "/api/v1/billing/token-packs/purchase",
    "/api/v1/billing/reconcile-usage",
    "/api/v1/billing/webhooks/iyzico",
    "/api/v1/billing/callbacks/iyzico",
    "/api/v1/connectors/google_drive/connect",
    "/api/v1/connectors/gmail/connect",
    "/api/v1/connectors/google_calendar/connect",
    "/api/v1/connectors/notion/connect",
    "/api/v1/connectors/slack/connect",
    "/api/v1/connectors/github/connect",
    "/api/v1/connectors/apple_mail/connect",
    "/api/v1/connectors/apple_calendar/connect",
    "/api/v1/connectors/apple_reminders/connect",
    "/api/v1/connectors/apple_notes/connect",
    "/api/v1/connectors/apple_contacts/connect",
    "/api/v1/connectors/imessage/connect",
    "/api/v1/connectors/quick-action",
    "/api/v1/operator/preview",
    "/api/models",
    "/api/agent/profile",
    "/api/autopilot/start",
    "/api/autopilot/stop",
    "/api/autopilot/tick",
}
_LOCAL_DASHBOARD_WRITE_PREFIXES = (
    "/api/v1/cowork/threads/",
    "/api/v1/cowork/approvals/",
    "/api/v1/runs/",
    "/api/v1/connectors/accounts/",
)
_USER_SESSION_PATHS = {
    "/api/channels",
    "/api/channels/catalog",
    "/api/channels/upsert",
    "/api/channels/toggle",
    "/api/channels/test",
    "/api/channels/sync",
    "/api/channels/pair/status",
    "/api/channels/pair/start",
    "/api/v1/auth/logout",
    "/api/v1/auth/me",
    "/api/v1/privacy/summary",
    "/api/v1/privacy/export",
    "/api/v1/privacy/delete",
    "/api/v1/privacy/learning/stats",
    "/api/v1/mobile-dispatch/sessions",
    "/api/v1/workflows/start",
    "/api/v1/inbox/events",
    "/api/v1/tasks/extract",
    "/api/v1/cowork/home",
    "/api/v1/cowork/threads",
    "/api/v1/cowork/continuity",
    "/api/v1/workspace/intelligence",
    "/api/v1/billing/workspace",
    "/api/v1/billing/usage",
    "/api/v1/billing/entitlements",
    "/api/v1/billing/plans",
    "/api/v1/billing/credits",
    "/api/v1/billing/ledger",
    "/api/v1/billing/events",
    "/api/v1/billing/profile",
    "/api/v1/billing/reconcile-usage",
    "/api/v1/billing/checkout-session",
    "/api/v1/billing/portal-session",
    "/api/v1/billing/checkout/init",
    "/api/v1/billing/token-packs/purchase",
    "/api/v1/connectors",
    "/api/v1/connectors/accounts",
    "/api/v1/connectors/traces",
    "/api/v1/connectors/health",
    "/api/v1/operator/preview",
    "/api/v1/approvals/pending",
    "/api/v1/admin/workspaces",
}
_USER_SESSION_PREFIXES = (
    "/api/channels/",
    "/api/v1/admin/workspaces/",
    "/api/v1/cowork/threads/",
    "/api/v1/cowork/approvals/",
    "/api/v1/billing/checkouts/",
    "/api/v1/runs/",
    "/api/v1/connectors/",
    "/api/v1/approvals/",
)


def _is_local_dashboard_write_path(path: str, method: str) -> bool:
    if method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    if path in _LOCAL_DASHBOARD_WRITE_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _LOCAL_DASHBOARD_WRITE_PREFIXES)


def _is_user_session_path(path: str) -> bool:
    if path.startswith("/api/v1/billing/checkouts/") and path.endswith("/launch"):
        return False
    if path in _USER_SESSION_PATHS:
        return True
    return any(path.startswith(prefix) for prefix in _USER_SESSION_PREFIXES)


def _adapter_health_bucket(name: str, status: Any, health: dict[str, Any]) -> str:
    low_name = str(name or "").strip().lower()
    low_status = str(status or "").strip().lower()
    health_status = str((health or {}).get("status") or "").strip().lower()
    last_error = str((health or {}).get("last_error") or "").strip().lower()

    if low_status in {"connected", "online", "ok", "active", "healthy"} or health_status in {"connected", "healthy"}:
        return "healthy"
    if low_name == "webchat" and low_status.startswith("online"):
        return "healthy"
    if low_name == "telegram" and (
        low_status in {"unavailable", "conflict"}
        or health_status in {"unavailable", "conflict"}
        or "getupdates request" in last_error
    ):
        return "optional"
    if low_name == "whatsapp" and ("node.js bulunamadı" in last_error or "not configured" in last_error):
        return "optional"
    if health_status in {"disabled", "optional"}:
        return "optional"
    return "degraded"


def _ensure_admin_access_token() -> str:
    configured = str(
        os.getenv("ELYAN_ADMIN_TOKEN", "")
        or elyan_config.get("gateway.admin.token", "")
        or ""
    ).strip()
    if configured:
        return configured
    generated = secrets.token_urlsafe(24)
    try:
        elyan_config.set("gateway.admin.token", generated)
    except Exception as e:
        logger.warning(f"Failed to persist admin token: {e}. A new token will be generated on next startup.")
    return generated


def push_activity(event_type: str, channel: str, detail: str, success: bool = True):
    """Push an activity event to all connected dashboard WebSocket clients."""
    trace_context = get_trace_context()
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "type": event_type,
        "channel": channel,
        "detail": detail[:80],
        "ok": success,
    }
    if trace_context is not None:
        entry["trace_id"] = trace_context.trace_id
        entry["request_id"] = trace_context.request_id
    _activity_log.append(entry)
    if len(_activity_log) > 50:
        _activity_log.pop(0)
    _schedule_background(_broadcast_activity, entry)


def _json_ok(payload: dict[str, Any] | None = None, *, status: int = 200) -> web.Response:
    body = {"ok": True, "success": True}
    if payload:
        body.update(payload)
    return web.json_response(body, status=status)


def _json_error(error: str, *, status: int = 400, payload: dict[str, Any] | None = None) -> web.Response:
    body = {"ok": False, "success": False, "error": str(error or "request_failed")}
    if payload:
        body.update(payload)
    return web.json_response(body, status=status)


def _compact_text(value: str, *, limit: int = 280) -> str:
    return _shared_compact_text(value, limit=limit)


class _UploadValidationError(ValueError):
    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = int(status or 400)


def _normalize_upload_mime(raw_mime: str) -> str:
    return str(raw_mime or "").split(";", 1)[0].strip().lower()


def _is_allowed_upload_mime(raw_mime: str) -> bool:
    mime = _normalize_upload_mime(raw_mime)
    return bool(mime) and mime in _UPLOAD_ALLOWED_MIME_TYPES


def _sanitize_upload_filename(filename: str, *, fallback_prefix: str = "upload") -> str:
    decoded = unquote(str(filename or "").strip())
    candidate = Path(decoded).name
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate)
    candidate = candidate.lstrip(".")
    if not candidate:
        candidate = f"{fallback_prefix}_{int(time.time())}"
    if len(candidate) > 120:
        suffix = Path(candidate).suffix[:16]
        stem = Path(candidate).stem[: max(1, 120 - len(suffix))]
        candidate = f"{stem}{suffix}"
    return candidate


def _build_upload_path(upload_dir: Path, filename: str, *, fallback_prefix: str = "upload") -> tuple[str, Path]:
    upload_root = upload_dir.expanduser().resolve()
    upload_root.mkdir(parents=True, exist_ok=True)
    safe_name = _sanitize_upload_filename(filename, fallback_prefix=fallback_prefix)
    filepath = (upload_root / safe_name).resolve()
    if not filepath.is_relative_to(upload_root):
        raise _UploadValidationError("unsafe upload path", status=400)
    return safe_name, filepath


async def _save_upload_field(field: Any, filepath: Path, *, max_bytes: int) -> int:
    size = 0
    try:
        with filepath.open("wb") as handle:
            while True:
                chunk = await field.read_chunk()
                if not chunk:
                    break
                size += len(chunk)
                if size > max(1, int(max_bytes or 1)):
                    raise _UploadValidationError("file too large", status=413)
                handle.write(chunk)
    except Exception:
        filepath.unlink(missing_ok=True)
        raise
    return size


def _normalize_inbox_source(value: str) -> str:
    return _shared_normalize_intake_source(value)


def _extract_intake_action_items(content: str) -> list[str]:
    action_items: list[str] = []
    seen: set[str] = set()
    lines = [line.strip(" \t-•*0123456789.)") for line in str(content or "").splitlines() if line.strip()]
    verb_hint = re.compile(
        r"\b(prepare|draft|review|reply|send|plan|schedule|create|update|fix|ship|deploy|connect|sync|call|follow up|hazırla|incele|yanıtla|gönder|planla|oluştur|düzelt|bağla|ara|takip et)\b",
        re.IGNORECASE,
    )
    for line in lines:
        candidate = _compact_text(line, limit=120)
        lowered = candidate.lower()
        if len(candidate) < 8:
            continue
        if line[:1] in {"-", "*", "•"} or re.match(r"^\d+[.)]", line.strip()) or verb_hint.search(lowered):
            if lowered not in seen:
                action_items.append(candidate)
                seen.add(lowered)
        if len(action_items) >= 4:
            return action_items
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", str(content or "").strip()) if segment.strip()]
    for sentence in sentences:
        candidate = _compact_text(sentence, limit=120)
        lowered = candidate.lower()
        if len(candidate) < 12 or lowered in seen:
            continue
        action_items.append(candidate)
        seen.add(lowered)
        if len(action_items) >= 4:
            break
    return action_items[:4]


def _infer_intake_task_type(content: str) -> str:
    text = str(content or "").lower()
    if re.search(r"\b(slide|deck|presentation|sunum|ppt|pitch)\b", text):
        return "presentation"
    if re.search(r"\b(site|website|landing|web app|web|react|nextjs|frontend|vite|ui)\b", text):
        return "website"
    if re.search(r"\b(report|proposal|brief|document|doc|doküman|belge|teklif|rapor|sunuş metni)\b", text):
        return "document"
    return "cowork"


def _infer_intake_urgency(content: str) -> str:
    text = str(content or "").lower()
    if re.search(r"\b(acil|urgent|asap|today|bugün|hemen|critical|kritik|production|prod)\b", text):
        return "high"
    if re.search(r"\b(soon|this week|yakında|hafta|review|inceleme|follow up|takip)\b", text):
        return "medium"
    return "low"


def _intake_requires_approval(content: str) -> bool:
    return bool(
        re.search(
            r"\b(delete|remove|drop|reset|restart|deploy|publish|purchase|pay|refund|invoice|transfer|revoke|production|prod|sil|kaldır|yayınla|satın al|ödeme|iade|fatura|aktarım)\b",
            str(content or "").lower(),
        )
    )


def _extract_task_summary(content: str, *, source_type: str, title: str = "") -> dict[str, Any]:
    return _shared_extract_task_summary(content, source_type=source_type, title=title)


def _sanitize_stream_payload(value: Any, *, _depth: int = 0) -> Any:
    """Keep dashboard stream payload compact/safe (truncate + strip binary blobs)."""
    if _depth > 3:
        return "<truncated>"
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, str):
        text = value
        if len(text) > 500:
            text = text[:500] + f"...(+{len(value)-500})"
        # Hide probable base64-like image payloads in stream.
        if text.startswith("data:image/") or ("base64" in text[:80] and len(text) > 120):
            return "<image_payload>"
        return text
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            low = key.lower()
            if low in {"image", "image_data", "screenshot_data", "binary", "blob"}:
                out[key] = "<omitted>"
                continue
            out[key] = _sanitize_stream_payload(v, _depth=_depth + 1)
        return out
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:20]
        return [_sanitize_stream_payload(v, _depth=_depth + 1) for v in items]
    return value


def push_tool_event(
    stage: str,
    tool: str,
    *,
    step: str = "",
    request_id: str = "",
    success: Optional[bool] = None,
    latency_ms: Optional[int] = None,
    payload: Optional[dict] = None,
):
    """Push structured tool start/update/end event for dashboard stream."""
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "stage": str(stage or "").strip().lower(),
        "tool": str(tool or "").strip(),
        "step": str(step or "").strip(),
        "request_id": str(request_id or "").strip(),
        "success": success if isinstance(success, bool) else None,
        "latency_ms": int(latency_ms or 0) if latency_ms is not None else None,
        "payload": _sanitize_stream_payload(payload or {}),
    }
    _tool_event_log.append(entry)
    if len(_tool_event_log) > 200:
        _tool_event_log.pop(0)
    _schedule_background(_broadcast_event, "tool_event", entry)


def push_suggestion(title: str, description: str, action: str, params: dict, confidence: str = "MEDIUM"):
    """Push a proactive suggestion card to the dashboard."""
    payload = {
        "id": f"sug_{int(time.time()*1000)}",
        "title": title,
        "description": description,
        "action": action,
        "params": params,
        "confidence": confidence,
        "ts": time.strftime("%H:%M:%S")
    }
    _schedule_background(_broadcast_event, "suggestion", payload)


def push_hint(text: str, icon: str = "lightbulb", color: str = "yellow"):
    """Push a context-aware hint to the dashboard."""
    payload = {
        "id": f"hnt_{int(time.time()*1000)}",
        "text": text,
        "icon": icon,
        "color": color,
        "ts": time.strftime("%H:%M:%S")
    }
    _schedule_background(_broadcast_event, "hint", payload)


def push_cowork_event(event_type: str, payload: dict[str, Any]):
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "event_type": str(event_type or "cowork.delta").strip() or "cowork.delta",
        "payload": _sanitize_stream_payload(payload or {}),
    }
    _cowork_event_log.append(entry)
    if len(_cowork_event_log) > 200:
        _cowork_event_log.pop(0)
    _schedule_background(_broadcast_event, entry["event_type"], entry["payload"])


def _schedule_background(coro_func, *args):
    """Schedule best-effort dashboard events only when an event loop is active."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    try:
        loop.create_task(coro_func(*args))
    except Exception:
        return


async def _broadcast_event(event_type: str, data: dict):
    dead = set()
    for ws in list(_dashboard_ws_clients):
        try:
            await ws.send_json({"event": event_type, "data": data})
        except Exception:
            dead.add(ws)
    _dashboard_ws_clients.difference_update(dead)


async def _broadcast_activity(entry: dict):
    await _broadcast_event("activity", entry)


def _mask_sensitive_fields(data):
    """Mask secret-like keys before returning API responses."""
    sensitive_markers = ("token", "secret", "password", "api_key", "apikey", "key")
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if any(marker in str(k).lower() for marker in sensitive_markers):
                masked[k] = "***" if v not in (None, "") else ""
            else:
                masked[k] = _mask_sensitive_fields(v)
        return masked
    if isinstance(data, list):
        return [_mask_sensitive_fields(item) for item in data]
    return data


def _get_runtime_model_info() -> dict:
    """Resolve active (router) and configured (default) model/provider consistently."""
    configured_provider = elyan_config.get("models.default.provider", "—")
    configured_model = elyan_config.get("models.default.model", "—")
    active_provider = configured_provider
    active_model = configured_model
    source = "config"

    try:
        from core.neural_router import neural_router

        routed = neural_router.get_model_for_role("inference") or {}
        rp = routed.get("provider")
        rm = routed.get("model")
        if rp or rm:
            active_provider = rp or active_provider
            active_model = rm or active_model
            source = "router"
    except Exception:
        pass

    return {
        "active_provider": active_provider or "—",
        "active_model": active_model or "—",
        "configured_provider": configured_provider or "—",
        "configured_model": configured_model or "—",
        "model_source": source,
        "model_consistent": (
            str(active_provider or "").lower() == str(configured_provider or "").lower()
            and str(active_model or "").lower() == str(configured_model or "").lower()
        ),
    }


def _default_model_for_provider(provider: str) -> str:
    return default_model_for_provider(provider)


def _unique_clean(items, default):
    if not isinstance(items, list):
        items = list(default)
    out = []
    seen = set()
    for raw in items:
        item = str(raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _to_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return default


def _policy_default_deny_enabled() -> bool:
    default_deny = elyan_config.get("tools.default_deny", None)
    if default_deny is None:
        default_deny = elyan_config.get("security.toolPolicy.defaultDeny", True)
    return _to_bool(default_deny, True)


def _get_policy_lists() -> tuple[list[str], list[str], list[str]]:

    default_allow = [
        "group:fs",
        "group:web",
        "group:ui",
        "group:runtime",
        "group:messaging",
        "group:automation",
        "group:memory",
        "browser",
    ]
    allow_fallback = [] if _policy_default_deny_enabled() else default_allow
    allow = _unique_clean(elyan_config.get("tools.allow", None), allow_fallback)
    deny = _unique_clean(elyan_config.get("tools.deny", []), [])
    require = elyan_config.get("tools.requireApproval", None)
    if require is None:
        require = elyan_config.get("tools.require_approval", ["exec", "delete_file"])
    require = _unique_clean(require, ["exec", "delete_file"])
    return allow, deny, require


def _policy_state(tool_name: str) -> tuple[str, bool, bool, bool]:
    """Resolve group + policy state using the same engine as runtime execution."""
    group = tool_policy.infer_group(tool_name) or "other"
    denied = bool(tool_policy.is_denied(tool_name, group))
    allowed = bool(tool_policy.is_allowed(tool_name, group))
    needs_approval = bool(allowed and tool_policy.needs_approval(tool_name, group))
    return group, allowed, denied, needs_approval


def _request_remote_host(request) -> str:
    remote = str(getattr(request, "remote", "") or "").strip()
    if remote:
        return remote
    transport = getattr(request, "transport", None)
    if transport:
        try:
            peer = transport.get_extra_info("peername")
            if isinstance(peer, tuple) and peer:
                return str(peer[0] or "").strip()
        except Exception:
            pass
    forwarded = ""
    try:
        forwarded = str(request.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
    except Exception:
        forwarded = ""
    return forwarded


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    return normalized in _LOOPBACK_HOSTS


def _is_loopback_request(request) -> bool:
    host = _request_remote_host(request)
    if not host:
        return False
    return _is_loopback_host(host)


def _prune_auth_failures(ip: str) -> list[float]:
    normalized_ip = str(ip or "").strip()
    if not normalized_ip:
        return []
    now = time.time()
    attempts = [
        ts for ts in _AUTH_FAILURE_ATTEMPTS.get(normalized_ip, [])
        if now - ts < _AUTH_RATE_LIMIT_WINDOW_SECONDS
    ]
    if attempts:
        _AUTH_FAILURE_ATTEMPTS[normalized_ip] = attempts
    else:
        _AUTH_FAILURE_ATTEMPTS.pop(normalized_ip, None)
    return attempts


def _is_auth_rate_limited(ip: str) -> bool:
    normalized_ip = str(ip or "").strip()
    if not normalized_ip:
        return False
    return len(_prune_auth_failures(normalized_ip)) >= _AUTH_RATE_LIMIT_MAX_FAILURES


def _record_auth_failure(ip: str) -> None:
    normalized_ip = str(ip or "").strip()
    if not normalized_ip:
        return
    attempts = _prune_auth_failures(normalized_ip)
    attempts.append(time.time())
    _AUTH_FAILURE_ATTEMPTS[normalized_ip] = attempts


def _clear_auth_failures(ip: str) -> None:
    normalized_ip = str(ip or "").strip()
    if normalized_ip:
        _AUTH_FAILURE_ATTEMPTS.pop(normalized_ip, None)


def _build_admin_session_context() -> dict[str, Any]:
    return {
        "session_id": "admin",
        "workspace_id": "local-workspace",
        "user_id": "local-admin",
        "email": "",
        "display_name": "Admin",
        "role": "admin",
    }


def _resolve_dashboard_ws_token(token: str) -> tuple[bool, str, dict[str, Any]]:
    candidate = str(token or "").strip()
    if not candidate:
        return False, "authentication token required", {}
    session = get_runtime_database().auth_sessions.resolve_session(candidate)
    if session:
        return True, "", session
    if candidate == _ensure_admin_access_token():
        return True, "", _build_admin_session_context()
    return False, "invalid or expired session", {}


async def _await_dashboard_ws_auth(ws: web.WebSocketResponse) -> tuple[bool, str]:
    try:
        message = await asyncio.wait_for(ws.receive(), timeout=_DASHBOARD_WS_AUTH_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        return False, "authentication required"

    if message.type != WSMsgType.TEXT:
        return False, "authentication required"

    try:
        payload = json.loads(str(message.data or "{}"))
    except json.JSONDecodeError:
        return False, "invalid websocket auth payload"

    message_type = str(payload.get("type") or payload.get("event") or "").strip().lower()
    token = payload.get("token")
    if token is None and isinstance(payload.get("data"), dict):
        token = payload["data"].get("token")
    if message_type != "auth":
        return False, "authentication required"

    allowed, error, _auth_context = _resolve_dashboard_ws_token(str(token or ""))
    if not allowed:
        return False, error
    return True, ""


def _iter_memory_candidates(memory_obj: Any) -> list[Any]:
    candidates: list[Any] = []
    seen: set[int] = set()
    for obj in (
        memory_obj,
        getattr(memory_obj, "memory", None),
        getattr(memory_obj, "manager", None),
        getattr(memory_obj, "_memory", None),
        getattr(memory_obj, "backend", None),
    ):
        if obj is None:
            continue
        oid = id(obj)
        if oid in seen:
            continue
        seen.add(oid)
        candidates.append(obj)
    return candidates


async def _safe_optional_call(target: Any, method_name: str, **kwargs) -> Any:
    method = getattr(target, method_name, None)
    if not callable(method):
        return None
    try:
        result = method(**kwargs) if kwargs else method()
        if inspect.isawaitable(result):
            result = await result
        return result
    except Exception as e:
        logger.debug(f"{target.__class__.__name__}.{method_name} failed: {e}")
        return None


async def _fetch_memory_stats(memory_obj: Any) -> dict[str, Any]:
    for candidate in _iter_memory_candidates(memory_obj):
        fetched = await _safe_optional_call(candidate, "get_stats")
        if isinstance(fetched, dict):
            return fetched
    return {}


async def _fetch_memory_top_users(memory_obj: Any, *, limit: int) -> list[dict[str, Any]]:
    for candidate in _iter_memory_candidates(memory_obj):
        fetched = await _safe_optional_call(candidate, "get_top_users_storage", limit=limit)
        if isinstance(fetched, list):
            return fetched
    return []


_PROVIDER_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
}

_CHANNEL_SECRET_ENV_KEYS = {
    "telegram": {"token": "TELEGRAM_BOT_TOKEN"},
    "discord": {"token": "DISCORD_BOT_TOKEN"},
    "slack": {
        "token": "SLACK_BOT_TOKEN",
        "bot_token": "SLACK_BOT_TOKEN",
        "app_token": "SLACK_APP_TOKEN",
    },
    "whatsapp": {
        "token": "WHATSAPP_BOT_TOKEN",
        "bridge_token": "WHATSAPP_BRIDGE_TOKEN",
        "access_token": "WHATSAPP_ACCESS_TOKEN",
        "verify_token": "WHATSAPP_VERIFY_TOKEN",
    },
    "imessage": {"password": "IMESSAGE_PASSWORD"},
    "sms": {"auth_token": "TWILIO_AUTH_TOKEN", "token": "TWILIO_AUTH_TOKEN"},
    "signal": {"token": "SIGNAL_BOT_TOKEN"},
}


def _provider_env_key(provider: str) -> str:
    return _PROVIDER_ENV_KEYS.get(str(provider or "").strip().lower(), "")


def _provider_key_status(provider: str) -> dict:
    p = str(provider or "").strip().lower()
    env_key = _provider_env_key(p)
    cfg_key = elyan_config.get(f"models.providers.{p}.apiKey", "")
    if not isinstance(cfg_key, str):
        cfg_key = ""
    cfg_key = cfg_key.strip()
    cfg_uses_ref = bool(cfg_key.startswith("$"))
    cfg_has_value = bool(cfg_key)

    has_env = bool(env_key and os.getenv(env_key, "").strip())
    has_keychain = False
    if env_key:
        try:
            keychain_key = KeychainManager.key_for_env(env_key)
            if keychain_key:
                has_keychain = bool(KeychainManager.get_key(keychain_key))
        except Exception:
            has_keychain = False

    source = "none"
    available = False
    if has_keychain:
        source = "keychain"
        available = True
    elif has_env:
        source = "env"
        available = True
    elif cfg_has_value and not cfg_uses_ref:
        source = "config"
        available = True
    elif cfg_uses_ref:
        source = "config_ref"
        available = has_env or has_keychain

    return {
        "provider": p,
        "env_key": env_key,
        "configured": bool(available),
        "source": source,
        "config_ref": cfg_key if cfg_uses_ref else "",
        "available_in": {
            "keychain": bool(has_keychain),
            "env": bool(has_env),
            "config": bool(cfg_has_value and not cfg_uses_ref),
        },
    }


def _sanitize_roles_map(raw_roles: dict, default_provider: str, default_model: str) -> dict:
    if not isinstance(raw_roles, dict):
        return {}
    out: dict = {}
    allowed_roles = {
        "router",
        "reasoning",
        "inference",
        "creative",
        "code",
        "critic",
        "worker",
        "research_worker",
        "code_worker",
        "planning",
        "qa",
    }
    for role, cfg in raw_roles.items():
        role_name = str(role or "").strip().lower()
        if role_name not in allowed_roles or not isinstance(cfg, dict):
            continue
        provider = str(cfg.get("provider") or default_provider).strip().lower()
        model_raw = str(cfg.get("model") or "").strip()
        model = model_raw if model_raw else _default_model_for_provider(provider)
        if not model:
            model = _default_model_for_provider(provider)
        out[role_name] = {"provider": provider, "model": model}
    return out


def _sanitize_model_registry(raw_registry: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_registry, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_registry:
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or item.get("type") or "").strip().lower()
        if provider == "gemini":
            provider = "google"
        if provider not in {"openai", "anthropic", "google", "groq", "ollama"}:
            continue
        model = str(item.get("model") or "").strip()
        if not model:
            model = _default_model_for_provider(provider)
        alias = str(item.get("alias") or item.get("name") or "").strip()
        entry_id = str(item.get("id") or f"{provider}:{model}").strip()
        if not entry_id or entry_id in seen:
            continue
        seen.add(entry_id)
        roles = item.get("roles", [])
        if isinstance(roles, str):
            roles = [chunk.strip().lower() for chunk in roles.split(",")]
        if not isinstance(roles, list):
            roles = []
        normalized_roles = []
        for role in roles:
            role_name = str(role or "").strip().lower()
            if role_name and role_name not in normalized_roles:
                normalized_roles.append(role_name)
        try:
            priority = max(0, min(999, int(item.get("priority", 50) or 50)))
        except Exception:
            priority = 50
        out.append(
            {
                "id": entry_id,
                "provider": provider,
                "model": model,
                "alias": alias,
                "enabled": bool(item.get("enabled", True)),
                "roles": normalized_roles,
                "priority": priority,
            }
        )
    return out


def _sanitize_collaboration_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    try:
        max_models = int(raw.get("max_models", 3) or 3)
    except Exception:
        max_models = 3
    roles = raw.get("roles", [])
    if isinstance(roles, str):
        roles = [chunk.strip().lower() for chunk in roles.split(",")]
    if not isinstance(roles, list):
        roles = []
    normalized_roles = []
    for role in roles:
        role_name = str(role or "").strip().lower()
        if role_name and role_name not in normalized_roles:
            normalized_roles.append(role_name)
    return {
        "enabled": bool(raw.get("enabled", True)),
        "strategy": str(raw.get("strategy", "synthesize") or "synthesize").strip().lower(),
        "max_models": max(1, min(5, max_models)),
        "roles": normalized_roles,
    }


def _channel_id(ch: dict) -> str:
    if not isinstance(ch, dict):
        return ""
    cid = str(ch.get("id") or "").strip()
    ctype = str(ch.get("type") or "").strip().lower()
    return cid or ctype


def _normalize_channel_type(raw: str) -> str:
    return str(raw or "").strip().lower().replace("-", "_")


def _channel_secret_env(field: str, channel_type: str) -> str:
    ctype = _normalize_channel_type(channel_type)
    fmap = _CHANNEL_SECRET_ENV_KEYS.get(ctype, {})
    return str(fmap.get(str(field or "").strip(), "")).strip()


def _resolve_secret_runtime_value(value: Any) -> str:
    resolved = elyan_config._resolve_secret_ref(value)
    return str(resolved or "").strip()


def _resolve_channel_secret(field: str, channel_type: str, value: Any) -> tuple[str, bool]:
    resolved = _resolve_secret_runtime_value(value)
    is_ref = isinstance(value, str) and str(value).strip().startswith("$")
    unresolved = bool(is_ref and resolved == str(value).strip())
    return resolved, unresolved


class ElyanGatewayServer:
    """Main HTTP/WebSocket server for the Elyan Gateway."""

    def __init__(self, agent):
        self.agent = agent
        self.router = GatewayRouter(agent)
        self.mission_runtime = get_mission_runtime()
        self.mission_runtime.subscribe(self._on_mission_event)
        self.autopilot = get_autopilot()
        self.app = web.Application(middlewares=[self._cors_middleware, self._trace_middleware, self._api_security_middleware])
        self.webchat_adapter: Optional[object] = None
        self.cron = get_cron_engine(agent)
        self.heartbeat = HeartbeatManager(agent)
        self.cron.set_report_callback(self._on_cron_report)
        self.connected_nodes: Dict[str, web.WebSocketResponse] = {}
        
        from core.runtime.execution_hub import RemoteExecutionHub
        self.execution_hub = RemoteExecutionHub(self)
        
        from core.runtime.orchestrator import TaskOrchestrator
        self.orchestrator = TaskOrchestrator(self)

        from core.runtime.scheduler import MissionScheduler
        self.scheduler = MissionScheduler(self.orchestrator)
        
        self._setup_routes()
        self.runner: Optional[web.AppRunner] = None
        self._telemetry_task: Optional[asyncio.Task] = None
        self._runtime_sync_worker = None

    def _on_mission_event(self, payload: dict[str, Any]):
        mission_id = str(payload.get("mission_id") or "").strip()
        event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
        label = str(event.get("label") or payload.get("event_type") or "mission").strip()
        status = str(event.get("status") or payload.get("status") or "").strip()
        detail = f"{mission_id}: {label}"
        if status:
            detail += f" ({status})"
        push_activity("mission", "dashboard", detail[:80], status not in {"failed", "denied"})
        _schedule_background(_broadcast_event, "mission_event", _sanitize_stream_payload(payload))
        mission = self._mission_store().get_mission(mission_id) if mission_id else None
        metadata = mission.metadata if mission and isinstance(mission.metadata, dict) else {}
        thread_id = str(metadata.get("thread_id") or "").strip()
        if not thread_id:
            return
        workspace_id = str(metadata.get("workspace_id") or "").strip()
        raw_event_type = str(payload.get("event_type") or event.get("event_type") or "").strip().lower()
        cowork_event_type = "cowork.thread.updated"
        if raw_event_type == "approval.requested":
            cowork_event_type = "cowork.approval.requested"
        elif raw_event_type == "approval.resolved":
            cowork_event_type = "cowork.approval.resolved"
        elif raw_event_type == "mission.running":
            cowork_event_type = "cowork.turn.started"
        elif raw_event_type in {"mission.completed", "mission.failed"}:
            cowork_event_type = "cowork.turn.completed"
        push_cowork_event(
            cowork_event_type,
            {
                "thread_id": thread_id,
                "workspace_id": workspace_id,
                "mission_id": mission_id,
                "status": status or (mission.status if mission else ""),
                "label": label,
                "event_type": raw_event_type or "mission_event",
                "pending_approvals": len([item for item in mission.approvals if item.status == "pending"]) if mission else 0,
                "current_mode": str(metadata.get("current_mode") or "cowork"),
            },
        )

    def _mission_store(self):
        store = getattr(self, "mission_runtime", None)
        if store is None:
            store = get_mission_runtime()
            self.mission_runtime = store
        return store

    def _cowork_store(self):
        from core.cowork_threads import get_cowork_thread_store

        return get_cowork_thread_store()

    def _workspace_billing(self):
        from core.billing.workspace_billing import get_workspace_billing_store

        return get_workspace_billing_store()

    @staticmethod
    def _execution_guard():
        return get_execution_guard()

    def _usage_credit_decision(
        self,
        request,
        metric: str,
        *,
        payload: dict[str, Any] | None = None,
        amount: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._workspace_billing().authorize_usage(
            self._workspace_id(request, payload),
            metric,
            amount=amount,
            metadata=metadata,
        )

    @staticmethod
    def _credit_block_response(decision: dict[str, Any], *, action_label: str) -> web.Response:
        return _json_error(
            f"insufficient credits for {action_label}. Upgrade plan or purchase a token pack.",
            status=402,
            payload={"credits": decision},
        )

    def _record_provisional_usage(
        self,
        request,
        *,
        metric: str,
        payload: dict[str, Any] | None = None,
        amount: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._workspace_billing().record_usage(
            self._workspace_id(request, payload),
            metric,
            amount,
            metadata=metadata,
        )

    def _reconcile_failed_usage(
        self,
        workspace_id: str,
        *,
        usage_id: str,
        failure_class: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        normalized_workspace = str(workspace_id or "local-workspace").strip() or "local-workspace"
        normalized_usage_id = str(usage_id or "").strip()
        if not normalized_usage_id:
            return
        try:
            self._workspace_billing().reconcile_usage(
                normalized_workspace,
                usage_id=normalized_usage_id,
                actual_credits=0,
                metadata={
                    "dispatch_failed": True,
                    "failure_class": str(failure_class or "dispatch_failed").strip().lower(),
                    **dict(metadata or {}),
                },
            )
        except Exception as exc:
            slog.log_event(
                "billing_usage_reconcile_failed",
                {
                    "workspace_id": normalized_workspace,
                    "usage_id": normalized_usage_id,
                    "failure_class": str(failure_class or "dispatch_failed").strip().lower(),
                    "error": str(exc),
                    "metadata": dict(metadata or {}),
                },
                level="warning",
                workspace_id=normalized_workspace,
            )

    @staticmethod
    def _runtime_db():
        return get_runtime_database()

    def _workspace_admin_controller(self):
        controller = getattr(self, "_workspace_admin_instance", None)
        if controller is None:
            from core.gateway.controllers import WorkspaceAdminController

            controller = WorkspaceAdminController(self)
            self._workspace_admin_instance = controller
        return controller

    @staticmethod
    def _auth_context(request) -> dict[str, Any]:
        payload = request.get("elyan_auth") if hasattr(request, "get") else None
        return payload if isinstance(payload, dict) else {}

    @classmethod
    def _workspace_id(cls, request, payload: dict[str, Any] | None = None) -> str:
        # Security: auth context workspace takes absolute priority.
        # Query/body params are only used as hints when no session is active.
        auth_context = cls._auth_context(request)
        session_workspace = str(auth_context.get("workspace_id") or "").strip()
        if session_workspace:
            return session_workspace
        body_workspace = str((payload or {}).get("workspace_id") or "").strip()
        query_workspace = str(request.rel_url.query.get("workspace_id", "") or "").strip()
        return body_workspace or query_workspace or "local-workspace"

    def _require_workspace_access(
        self, request, workspace_id: str, *, allowed_roles: set[str] | None = None
    ) -> tuple[bool, str]:
        """Validate that the current user has access to the given workspace.
        Returns (allowed, error_message)."""
        auth_context = self._auth_context(request)
        role = str(auth_context.get("role") or "").strip().lower()

        # Breakglass admin can access any workspace
        if role == "admin" and str(auth_context.get("user_id") or "") == "local-admin":
            return True, ""

        # Session workspace must match requested workspace
        session_workspace = str(auth_context.get("workspace_id") or "").strip()
        if session_workspace and session_workspace != workspace_id:
            # Check if user has cross-workspace membership
            actor_id = self._actor_id(request)
            cross_role = self._runtime_db().access.get_actor_role(
                workspace_id=workspace_id, actor_id=actor_id,
            )
            if not cross_role:
                return False, "workspace_access_denied"
            role = cross_role

        if allowed_roles and role not in allowed_roles:
            return False, f"insufficient_role:{role}"
        return True, ""

    @classmethod
    def _actor_id(cls, request, payload: dict[str, Any] | None = None) -> str:
        auth_context = cls._auth_context(request)
        if str(auth_context.get("user_id") or "").strip():
            return str(auth_context.get("user_id") or "").strip()
        body_user = str((payload or {}).get("user_id") or "").strip()
        query_user = str(request.rel_url.query.get("user_id", "") or "").strip()
        return body_user or query_user or cls._workspace_id(request, payload)

    @classmethod
    def _session_id(cls, request, payload: dict[str, Any] | None = None, *, default: str = "") -> str:
        auth_context = cls._auth_context(request)
        if str(auth_context.get("session_id") or "").strip():
            return str(auth_context.get("session_id") or "").strip()
        body_session = str((payload or {}).get("session_id") or "").strip()
        query_session = str(request.rel_url.query.get("session_id", "") or "").strip()
        trace_context = request.get("elyan_trace") if hasattr(request, "get") else None
        if body_session:
            return body_session
        if query_session:
            return query_session
        if getattr(trace_context, "session_id", ""):
            return str(trace_context.session_id or "").strip()
        return str(default or "").strip()

    def _observe_execution_guard(
        self,
        request,
        *,
        action: str,
        phase: str,
        payload: dict[str, Any] | None = None,
        allowed: bool,
        reason: str = "",
        checks: list[ExecutionCheck] | None = None,
        metadata: dict[str, Any] | None = None,
        run_id: str = "",
        level: str = "info",
        default_session_id: str = "",
    ) -> None:
        self._execution_guard().observe_shadow(
            action=action,
            phase=phase,
            allowed=allowed,
            workspace_id=self._workspace_id(request, payload),
            actor_id=self._actor_id(request, payload),
            session_id=self._session_id(request, payload, default=default_session_id),
            run_id=run_id,
            reason=reason,
            checks=checks,
            metadata=metadata,
            level=level,
        )

    @staticmethod
    def _local_user_count(runtime_db=None) -> int:
        db = runtime_db or get_runtime_database()
        try:
            with db.local_engine.begin() as conn:
                row = conn.exec_driver_sql("select count(*) from local_users").first()
                return int((row[0] if row else 0) or 0)
        except Exception:
            return 0

    @staticmethod
    def _set_csrf_cookie(response: web.StreamResponse, token: str = "") -> str:
        csrf_token = str(token or secrets.token_urlsafe(24))
        response.headers["X-Elyan-CSRF"] = csrf_token
        response.set_cookie(
            "elyan_csrf_token",
            csrf_token,
            httponly=False,
            samesite="Strict",
            secure=False,
            path="/",
        )
        return csrf_token

    @staticmethod
    def _clear_csrf_cookie(response: web.StreamResponse) -> None:
        response.headers["X-Elyan-CSRF"] = ""
        response.del_cookie("elyan_csrf_token", path="/")

    def _workspace_role_for_request(self, request, payload: dict[str, Any] | None = None) -> str:
        auth_context = self._auth_context(request)
        if str(auth_context.get("role") or "") == "admin":
            return "admin"
        workspace_id = self._workspace_id(request, payload)
        actor_id = self._actor_id(request, payload)
        if str(auth_context.get("workspace_id") or "").strip() == workspace_id and str(auth_context.get("role") or "").strip():
            return str(auth_context.get("role") or "").strip().lower()
        return self._runtime_db().access.get_actor_role(workspace_id=workspace_id, actor_id=actor_id)

    def _require_execution_seat(self, request, payload: dict[str, Any] | None = None) -> tuple[bool, str]:
        role = self._workspace_role_for_request(request, payload)
        if role == "admin":
            return True, ""
        workspace_id = self._workspace_id(request, payload)
        actor_id = self._actor_id(request, payload)
        if role not in {"owner", "operator"}:
            return False, "owner or operator role required"
        if not self._runtime_db().access.has_active_seat(workspace_id=workspace_id, actor_id=actor_id):
            return False, "active seat required"
        return True, ""

    def _require_billing_write_role(self, request, payload: dict[str, Any] | None = None) -> tuple[bool, str]:
        role = self._workspace_role_for_request(request, payload)
        if role == "admin" or role in {"owner", "billing_admin"}:
            return True, ""
        return False, "owner or billing_admin role required"

    @staticmethod
    def _has_cookie_user_session(request) -> bool:
        return bool(str(request.cookies.get("elyan_user_session", "") or "").strip())

    def _request_requires_csrf(self, request) -> bool:
        method = str(getattr(request, "method", "GET") or "GET").upper()
        path = str(getattr(request, "path", "") or "")
        if method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return False
        if path in {"/api/v1/auth/login", "/api/v1/auth/bootstrap-owner"}:
            return False
        if path.startswith("/api/v1/billing/webhooks/"):
            return False
        return self._request_requires_user_session(request) and self._has_cookie_user_session(request)

    def _validate_csrf(self, request) -> tuple[bool, str]:
        if str(request.headers.get("X-Elyan-Session-Token", "") or "").strip():
            return True, ""
        csrf_cookie = str(request.cookies.get("elyan_csrf_token", "") or "").strip()
        csrf_header = str(request.headers.get("X-Elyan-CSRF", "") or "").strip()
        if not csrf_cookie or not csrf_header:
            return False, "csrf token required"
        if not secrets.compare_digest(csrf_cookie, csrf_header):
            return False, "csrf token mismatch"
        origin = str(request.headers.get("Origin", "") or "").strip()
        if origin and not self._is_allowed_cors_origin(origin):
            return False, "csrf origin forbidden"
        referer = str(request.headers.get("Referer", "") or "").strip()
        if referer:
            try:
                parsed = urlparse(referer)
                referer_origin = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" if parsed.scheme and parsed.netloc else ""
            except Exception:
                referer_origin = ""
            if referer_origin and not self._is_allowed_cors_origin(referer_origin):
                return False, "csrf referer forbidden"
        return True, ""

    @staticmethod
    def _connector_catalog() -> list[dict[str, Any]]:
        return [
            {
                "connector": "google_drive",
                "provider": "drive",
                "label": "Google Drive",
                "category": "work_suite",
                "integration_type": "api",
                "capabilities": ["search_files", "read_docs", "upload_file"],
                "scopes": ["https://www.googleapis.com/auth/drive.file"],
            },
            {
                "connector": "gmail",
                "provider": "gmail",
                "label": "Gmail",
                "category": "work_suite",
                "integration_type": "email",
                "capabilities": ["search_mail", "read_thread", "draft_reply"],
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            },
            {
                "connector": "google_calendar",
                "provider": "calendar",
                "label": "Google Calendar",
                "category": "work_suite",
                "integration_type": "api",
                "capabilities": ["list_events", "create_event", "check_availability"],
                "scopes": ["https://www.googleapis.com/auth/calendar"],
            },
            {
                "connector": "notion",
                "provider": "notion",
                "label": "Notion",
                "category": "workspace",
                "integration_type": "api",
                "capabilities": ["search_pages", "read_page", "update_page", "create_page"],
                "scopes": ["notion.read", "notion.write"],
            },
            {
                "connector": "apple_mail",
                "provider": "apple_mail",
                "label": "Apple Mail",
                "category": "apple_apps",
                "integration_type": "desktop",
                "capabilities": ["list_items", "read_item", "draft_message", "send_message"],
                "scopes": ["mail.read", "mail.write"],
            },
            {
                "connector": "apple_calendar",
                "provider": "apple_calendar",
                "label": "Apple Calendar",
                "category": "apple_apps",
                "integration_type": "desktop",
                "capabilities": ["list_items", "read_item", "create_item", "update_item"],
                "scopes": ["calendar.read", "calendar.write"],
            },
            {
                "connector": "apple_reminders",
                "provider": "apple_reminders",
                "label": "Apple Reminders",
                "category": "apple_apps",
                "integration_type": "desktop",
                "capabilities": ["list_items", "create_item", "update_item"],
                "scopes": ["reminders.read", "reminders.write"],
            },
            {
                "connector": "apple_notes",
                "provider": "apple_notes",
                "label": "Apple Notes",
                "category": "apple_apps",
                "integration_type": "desktop",
                "capabilities": ["search_items", "read_item", "create_item", "update_item"],
                "scopes": ["notes.read", "notes.write"],
            },
            {
                "connector": "apple_contacts",
                "provider": "apple_contacts",
                "label": "Apple Contacts",
                "category": "apple_apps",
                "integration_type": "desktop",
                "capabilities": ["search_items", "read_item", "create_item", "update_item"],
                "scopes": ["contacts.read", "contacts.write"],
            },
            {
                "connector": "imessage",
                "provider": "imessage",
                "label": "iMessage",
                "category": "messaging",
                "integration_type": "desktop",
                "capabilities": ["list_items", "read_item", "draft_message", "send_message"],
                "scopes": ["imessage.read", "imessage.write"],
            },
            {
                "connector": "slack",
                "provider": "slack",
                "label": "Slack",
                "category": "work_suite",
                "integration_type": "api",
                "capabilities": ["list_channels", "read_messages", "post_message"],
                "scopes": ["channels:read", "chat:write", "channels:history"],
            },
            {
                "connector": "github",
                "provider": "github",
                "label": "GitHub",
                "category": "work_suite",
                "integration_type": "api",
                "capabilities": ["read_repo", "issues", "pull_requests"],
                "scopes": ["repo", "read:user"],
            },
        ]

    @classmethod
    def _connector_lookup(cls, connector_name: str) -> dict[str, Any] | None:
        target = str(connector_name or "").strip().lower()
        for item in cls._connector_catalog():
            if str(item.get("connector") or "").strip().lower() == target:
                return dict(item)
        return None

    @staticmethod
    def _filter_workspace_accounts(accounts: list[dict[str, Any]], workspace_id: str) -> list[dict[str, Any]]:
        if not workspace_id:
            return accounts
        filtered: list[dict[str, Any]] = []
        for item in accounts:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if str(metadata.get("workspace_id") or "").strip() == workspace_id:
                filtered.append(item)
        return filtered

    @staticmethod
    def _filter_workspace_traces(traces: list[dict[str, Any]], workspace_id: str) -> list[dict[str, Any]]:
        if not workspace_id:
            return traces
        filtered: list[dict[str, Any]] = []
        for item in traces:
            metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            if str(metadata.get("workspace_id") or "").strip() == workspace_id:
                filtered.append(item)
        return filtered

    def _configured_cors_origins(self) -> set[str]:
        configured = elyan_config.get("gateway.cors.origins", []) or []
        if isinstance(configured, str):
            configured = [item.strip() for item in configured.split(",") if item.strip()]
        normalized: set[str] = set()
        normalized.update(
            {
                "tauri://localhost",
                "http://tauri.localhost",
                "https://tauri.localhost",
            }
        )
        for raw in configured:
            value = str(raw or "").strip()
            if not value:
                continue
            try:
                parsed = urlparse(value)
                if parsed.scheme and parsed.netloc:
                    normalized.add(f"{parsed.scheme.lower()}://{parsed.netloc.lower()}")
            except Exception:
                continue
        env_origins = str(os.getenv("ELYAN_CORS_ORIGINS", "") or "").strip()
        if env_origins:
            for part in env_origins.split(","):
                value = str(part or "").strip()
                if not value:
                    continue
                try:
                    parsed = urlparse(value)
                    if parsed.scheme and parsed.netloc:
                        normalized.add(f"{parsed.scheme.lower()}://{parsed.netloc.lower()}")
                except Exception:
                    continue
        return normalized

    def _is_allowed_cors_origin(self, origin: str) -> bool:
        raw_origin = str(origin or "").strip()
        if not raw_origin:
            return False
        try:
            parsed = urlparse(raw_origin)
        except Exception:
            return False
        hostname = str(parsed.hostname or "").strip().lower()
        if _is_loopback_host(hostname):
            return True
        normalized = f"{parsed.scheme.lower()}://{parsed.netloc.lower()}" if parsed.scheme and parsed.netloc else ""
        if not normalized:
            return False
        return normalized in self._configured_cors_origins()

    def _request_requires_admin(self, request) -> bool:
        path = str(getattr(request, "path", "") or "")
        method = str(getattr(request, "method", "GET") or "GET").upper()
        if not path.startswith("/api"):
            return False
        # Elyan chat API — loopback-only, no admin token needed (desktop-local)
        if path.startswith("/api/elyan/"):
            return False
        if _is_user_session_path(path):
            return False
        if _is_local_dashboard_write_path(path, method):
            return False
        if path == "/api/message":
            return True
        if path.startswith("/api/trace/") or path == "/api/evidence/file":
            return True
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return True
        if method == "GET" and path in _ADMIN_READ_PATHS:
            return True
        return False

    def _request_requires_user_session(self, request) -> bool:
        path = str(getattr(request, "path", "") or "")
        if not path.startswith("/api"):
            return False
        return _is_user_session_path(path)

    @web.middleware
    async def _cors_middleware(self, request, handler):
        origin = str(request.headers.get("Origin", "") or "").strip()
        allowed_origin = origin if origin and self._is_allowed_cors_origin(origin) else ""
        if origin and not allowed_origin:
            return web.json_response({"ok": False, "error": "CORS origin forbidden"}, status=403)
        if request.method == "OPTIONS":
            resp = web.Response(status=204)
            if allowed_origin:
                resp.headers["Access-Control-Allow-Origin"] = allowed_origin
                resp.headers["Access-Control-Allow-Credentials"] = "true"
                resp.headers["Access-Control-Expose-Headers"] = "X-Elyan-Session-Token, X-Elyan-Admin-Token, X-Elyan-Trace-Id, X-Elyan-Request-Id, X-Elyan-Workspace-Id"
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Elyan-Admin-Token, X-Elyan-Session-Token, X-Elyan-CSRF, X-Elyan-Trace-Id, X-Elyan-Request-Id, X-Elyan-Workspace-Id, X-Request-ID"
            resp.headers["Vary"] = "Origin"
            return resp
        resp = await handler(request)
        if allowed_origin:
            resp.headers["Access-Control-Allow-Origin"] = allowed_origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Access-Control-Expose-Headers"] = "X-Elyan-Session-Token, X-Elyan-Admin-Token, X-Elyan-Trace-Id, X-Elyan-Request-Id, X-Elyan-Workspace-Id"
            resp.headers["Vary"] = "Origin"
        return resp

    @web.middleware
    async def _trace_middleware(self, request, handler):
        flags = get_feature_flag_registry()
        if not flags.is_enabled(
            "gateway_request_tracing",
            default=True,
            context={"path": str(request.path), "method": str(request.method)},
        ):
            return await handler(request)

        trace_context = build_trace_context(
            method=str(request.method),
            path=str(request.path_qs),
            headers=request.headers,
            query=getattr(request, "query", {}) or {},
            cookies=request.cookies,
        )
        request["elyan_trace"] = trace_context.to_dict()
        token = activate_trace_context(trace_context)
        started_at = time.time()
        try:
            try:
                response = await handler(request)
            except web.HTTPException as exc:
                response = exc
            apply_trace_headers(response, trace_context)
            latency_ms = round((time.time() - started_at) * 1000.0, 2)
            slog.log_event(
                "gateway_request_completed",
                {
                    "method": str(request.method),
                    "path": str(request.path),
                    "path_qs": str(request.path_qs),
                    "status": int(getattr(response, "status", 200) or 200),
                    "latency_ms": latency_ms,
                },
                level="debug",
                session_id=trace_context.session_id or None,
                request_id=trace_context.request_id,
                trace_id=trace_context.trace_id,
                workspace_id=trace_context.workspace_id or None,
            )
            return response
        except Exception as exc:
            latency_ms = round((time.time() - started_at) * 1000.0, 2)
            slog.log_event(
                "gateway_request_failed",
                {
                    "method": str(request.method),
                    "path": str(request.path),
                    "path_qs": str(request.path_qs),
                    "error": str(exc),
                    "latency_ms": latency_ms,
                },
                level="error",
                session_id=trace_context.session_id or None,
                request_id=trace_context.request_id,
                trace_id=trace_context.trace_id,
                workspace_id=trace_context.workspace_id or None,
            )
            raise
        finally:
            reset_trace_context(token)

    @web.middleware
    async def _api_security_middleware(self, request, handler):
        if self._request_requires_user_session(request):
            allowed, error, auth_context = self._require_user_session(request, allow_cookie=True)
            if not allowed:
                return web.json_response({"ok": False, "error": error}, status=403)
            if self._request_requires_csrf(request):
                csrf_allowed, csrf_error = self._validate_csrf(request)
                if not csrf_allowed:
                    return web.json_response({"ok": False, "error": csrf_error}, status=403)
            request["elyan_auth"] = auth_context
        elif self._request_requires_admin(request):
            allowed, error = self._require_admin_access(request, allow_cookie=True)
            if not allowed:
                return web.json_response({"ok": False, "error": error}, status=403)
        return await handler(request)

    def _require_admin_access(self, request, *, allow_cookie: bool = True) -> tuple[bool, str]:
        if not _is_loopback_request(request):
            return False, "admin access is restricted to localhost"
        expected = _ensure_admin_access_token()
        candidate = str(
            request.headers.get("X-Elyan-Admin-Token", "")
            or (request.cookies.get("elyan_admin_session", "") if allow_cookie else "")
            or ""
        ).strip()
        if not candidate or candidate != expected:
            return False, "admin token required"
        return True, ""

    def _require_user_session(self, request, *, allow_cookie: bool = True) -> tuple[bool, str, dict[str, Any]]:
        if not _is_loopback_request(request):
            return False, "user session is restricted to localhost", {}
        candidate = str(
            request.headers.get("X-Elyan-Session-Token", "")
            or (request.cookies.get("elyan_user_session", "") if allow_cookie else "")
            or ""
        ).strip()
        session = get_runtime_database().auth_sessions.resolve_session(candidate)
        if session:
            session = self._ensure_conversation_session_context(session)
            return True, "", session
        if candidate:
            return False, "invalid or expired session", {}
        admin_allowed, _admin_error = self._require_admin_access(request, allow_cookie=allow_cookie)
        if admin_allowed:
            return True, "", _build_admin_session_context()
        return False, "user session required", {}

    @staticmethod
    def _ensure_conversation_session_context(session: dict[str, Any]) -> dict[str, Any]:
        payload = dict(session or {})
        if not payload:
            return payload
        try:
            from core.runtime.session_store import get_runtime_session_api

            return get_runtime_session_api().ensure_auth_session(payload)
        except Exception as exc:
            logger.debug(f"conversation session hydration skipped: {exc}")
            return payload

    def _setup_routes(self):
        # ── API V1 ────────────────────────────────────────────────────────────
        self.app.router.add_post('/api/message', self.handle_external_message)
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/channels', self.handle_list_channels)
        self.app.router.add_get('/api/channels/catalog', self.handle_channels_catalog)
        self.app.router.add_post('/api/channels/upsert', self.handle_channel_upsert)
        self.app.router.add_post('/api/channels/toggle', self.handle_channel_toggle)
        self.app.router.add_delete('/api/channels/{id}', self.handle_channel_delete)
        self.app.router.add_post('/api/channels/test', self.handle_channels_test)
        self.app.router.add_post('/api/channels/sync', self.handle_channels_sync)
        self.app.router.add_post('/api/channels/pair/start', self.handle_channel_pair_start)
        self.app.router.add_get('/api/channels/pair/status', self.handle_channel_pair_status)
        self.app.router.add_get('/api/config', self.handle_get_config)
        self.app.router.add_post('/api/config', self.handle_update_config)
        self.app.router.add_get('/api/agent/profile', self.handle_agent_profile_get)
        self.app.router.add_post('/api/agent/profile', self.handle_agent_profile_update)
        self.app.router.add_get('/api/models', self.handle_models_get)
        self.app.router.add_post('/api/models', self.handle_models_update)
        self.app.router.add_get('/api/models/ollama/list', self.handle_ollama_list)
        self.app.router.add_post('/api/models/ollama/pull', self.handle_ollama_pull)
        self.app.router.add_get('/api/logs', self.handle_get_logs)
        self.app.router.add_get('/api/canvas/{id}', self.handle_get_canvas)
        self.app.router.add_post('/api/upload', self.handle_file_upload)
        self.app.router.add_post('/api/voice', self.handle_voice_upload)
        self.app.router.add_get('/api/voice/file', self.handle_voice_file_get)
        self.app.router.add_get('/api/evidence/file', self.handle_evidence_file_get)
        self.app.router.add_get('/api/autopilot/status', self.handle_autopilot_status)
        self.app.router.add_post('/api/autopilot/tick', self.handle_autopilot_tick)
        self.app.router.add_post('/api/autopilot/start', self.handle_autopilot_start)
        self.app.router.add_post('/api/autopilot/stop', self.handle_autopilot_stop)

        # ── Dashboard API (new) ───────────────────────────────────────────────
        self.app.router.add_get('/api/analytics', self.handle_analytics)
        self.app.router.add_get('/api/subscription', self.handle_subscription_get)
        self.app.router.add_get('/api/quota', self.handle_quota_get)
        self.app.router.add_get('/api/admin/overview', self.handle_admin_overview)
        self.app.router.add_get('/api/admin/users', self.handle_admin_users)
        self.app.router.add_get('/api/admin/plans', self.handle_admin_plans)
        self.app.router.add_post('/api/admin/users/{user_id}/subscription', self.handle_admin_user_subscription)
        self.app.router.add_post('/api/admin/away-tasks/{task_id}/action', self.handle_admin_away_task_action)
        self.app.router.add_get('/api/tasks', self.handle_tasks)
        self.app.router.add_post('/api/tasks/suggest', self.handle_task_suggest)
        self.app.router.add_post('/api/tasks', self.handle_create_task)
        self.app.router.add_get('/api/missions/overview', self.handle_missions_overview)
        self.app.router.add_get('/api/missions/approvals', self.handle_missions_approvals)
        self.app.router.add_post('/api/missions/approvals/resolve', self.handle_missions_approval_resolve)
        self.app.router.add_get('/api/missions/skills', self.handle_missions_skills)
        self.app.router.add_post('/api/missions/skills/save', self.handle_missions_skill_save)
        self.app.router.add_get('/api/missions/memory', self.handle_missions_memory)
        self.app.router.add_get('/api/missions', self.handle_missions_list)
        self.app.router.add_post('/api/missions', self.handle_missions_create)
        self.app.router.add_get('/api/missions/{mission_id}', self.handle_mission_detail)
        self.app.router.add_get('/api/packs', self.handle_packs_overview)
        self.app.router.add_get('/api/packs/{pack}', self.handle_pack_detail)
        self.app.router.add_get('/api/trace/{task_id}', self.handle_trace_api)
        self.app.router.add_get('/api/memory/stats', self.handle_memory_stats)
        self.app.router.add_get('/api/memory/profile', self.handle_get_profile)
        self.app.router.add_get('/api/memory/recall', self.handle_memory_recall)
        self.app.router.add_get('/api/memory/history', self.handle_memory_history)
        self.app.router.add_get('/api/learning/drafts', self.handle_learning_drafts)
        self.app.router.add_get('/api/activity', self.handle_activity_log)
        self.app.router.add_get('/api/runs/recent', self.handle_recent_runs)
        self.app.router.add_get('/api/v1/runs', self.handle_v1_list_runs)
        self.app.router.add_get('/api/v1/runs/{run_id}', self.handle_v1_get_run)
        self.app.router.add_get('/api/v1/runs/{run_id}/timeline', self.handle_v1_get_run_timeline)
        self.app.router.add_post('/api/v1/runs/{run_id}/cancel', self.handle_v1_cancel_run)
        self.app.router.add_get('/api/v1/approvals/pending', self.handle_v1_pending_approvals)
        self.app.router.add_post('/api/v1/approvals/resolve', self.handle_v1_resolve_approval)
        self.app.router.add_post('/api/v1/approvals/bulk-resolve', self.handle_v1_bulk_resolve_approvals)
        self.app.router.add_get('/api/v1/metrics/tools', self.handle_v1_tool_metrics)
        self.app.router.add_get('/api/v1/metrics/multi-agent', self.handle_v1_multi_agent_metrics)
        self.app.router.add_get('/api/v1/system/backends', self.handle_v1_runtime_backends)
        self.app.router.add_get('/api/v1/system/overview', self.handle_v1_system_overview)
        self.app.router.add_get('/api/v1/system/platforms', self.handle_v1_system_platforms)
        self.app.router.add_get('/api/v1/security/summary', self.handle_v1_security_summary)
        self.app.router.add_get('/api/v1/security/events', self.handle_v1_security_events)
        self.app.router.add_get('/api/v1/learning/summary', self.handle_v1_learning_summary)
        self.app.router.add_get('/api/v1/inbox/events', self.handle_v1_inbox_events)
        self.app.router.add_post('/api/v1/inbox/events', self.handle_v1_inbox_events)
        self.app.router.add_post('/api/v1/tasks/extract', self.handle_v1_task_extract)
        self.app.router.add_post('/api/v1/workflows/start', self.handle_v1_start_workflow)
        self.app.router.add_post('/api/v1/auth/bootstrap-owner', self.handle_v1_auth_bootstrap_owner)
        self.app.router.add_post('/api/v1/auth/login', self.handle_v1_auth_login)
        self.app.router.add_post('/api/v1/auth/logout', self.handle_v1_auth_logout)
        self.app.router.add_get('/api/v1/auth/me', self.handle_v1_auth_me)
        self.app.router.add_get('/api/v1/admin/workspaces', self.handle_v1_admin_workspaces)
        self.app.router.add_post('/api/v1/admin/workspaces', self.handle_v1_admin_workspace_create)
        self.app.router.add_get('/api/v1/admin/workspaces/{workspace_id}', self.handle_v1_admin_workspace_detail)
        self.app.router.add_get('/api/v1/admin/workspaces/{workspace_id}/members', self.handle_v1_admin_workspace_members)
        self.app.router.add_get('/api/v1/admin/workspaces/{workspace_id}/invites', self.handle_v1_admin_workspace_invites_list)
        self.app.router.add_post('/api/v1/admin/workspaces/{workspace_id}/invites', self.handle_v1_admin_workspace_invites)
        self.app.router.add_post('/api/v1/admin/workspaces/{workspace_id}/invites/{invite_id}/accept', self.handle_v1_admin_workspace_invite_accept)
        self.app.router.add_post('/api/v1/admin/workspaces/{workspace_id}/members/{actor_id}/role', self.handle_v1_admin_workspace_member_role)
        self.app.router.add_post('/api/v1/admin/workspaces/{workspace_id}/seats/assign', self.handle_v1_admin_workspace_seat_assign)
        self.app.router.add_get('/api/v1/cowork/home', self.handle_v1_cowork_home)
        self.app.router.add_get('/api/v1/cowork/continuity', self.handle_v1_cowork_continuity)
        self.app.router.add_get('/api/v1/workspace/intelligence', self.handle_v1_workspace_intelligence)
        self.app.router.add_get('/api/v1/cowork/threads', self.handle_v1_cowork_threads)
        self.app.router.add_post('/api/v1/cowork/threads', self.handle_v1_cowork_threads)
        self.app.router.add_get('/api/v1/cowork/threads/{thread_id}', self.handle_v1_cowork_thread_detail)
        self.app.router.add_post('/api/v1/cowork/threads/{thread_id}/turns', self.handle_v1_cowork_thread_turn)
        self.app.router.add_post('/api/v1/cowork/threads/{thread_id}/actions', self.handle_v1_cowork_thread_action)
        self.app.router.add_post('/api/v1/cowork/approvals/{approval_id}/resolve', self.handle_v1_cowork_resolve_approval)
        self.app.router.add_get('/api/v1/billing/workspace', self.handle_v1_billing_workspace)
        self.app.router.add_get('/api/v1/billing/usage', self.handle_v1_billing_usage)
        self.app.router.add_get('/api/v1/billing/entitlements', self.handle_v1_billing_entitlements)
        self.app.router.add_get('/api/v1/billing/plans', self.handle_v1_billing_plans)
        self.app.router.add_get('/api/v1/billing/credits', self.handle_v1_billing_credits)
        self.app.router.add_get('/api/v1/billing/ledger', self.handle_v1_billing_ledger)
        self.app.router.add_get('/api/v1/billing/events', self.handle_v1_billing_events)
        self.app.router.add_get('/api/v1/billing/profile', self.handle_v1_billing_profile)
        self.app.router.add_put('/api/v1/billing/profile', self.handle_v1_billing_profile)
        self.app.router.add_get('/api/v1/billing/checkouts/{reference_id}', self.handle_v1_billing_checkout_detail)
        self.app.router.add_get('/api/v1/billing/checkouts/{reference_id}/launch', self.handle_v1_billing_checkout_launch)
        self.app.router.add_post('/api/v1/billing/reconcile-usage', self.handle_v1_billing_reconcile_usage)
        self.app.router.add_post('/api/v1/billing/checkout/init', self.handle_v1_billing_checkout_init)
        self.app.router.add_post('/api/v1/billing/token-packs/purchase', self.handle_v1_billing_token_pack_purchase)
        self.app.router.add_get('/api/v1/billing/callbacks/iyzico', self.handle_v1_billing_callback_iyzico)
        self.app.router.add_post('/api/v1/billing/callbacks/iyzico', self.handle_v1_billing_callback_iyzico)
        self.app.router.add_post('/api/v1/billing/webhooks/iyzico', self.handle_v1_billing_webhook_iyzico)
        self.app.router.add_post('/api/v1/billing/checkout-session', self.handle_v1_billing_checkout)
        self.app.router.add_post('/api/v1/billing/portal-session', self.handle_v1_billing_portal)
        self.app.router.add_post('/api/v1/billing/webhooks/stripe', self.handle_v1_billing_webhook)
        self.app.router.add_get('/api/v1/connectors', self.handle_v1_connectors)
        self.app.router.add_get('/api/v1/connectors/accounts', self.handle_v1_connector_accounts)
        self.app.router.add_post('/api/v1/connectors/{connector}/connect', self.handle_v1_connector_connect)
        self.app.router.add_post('/api/v1/connectors/{connector}/quick-action', self.handle_v1_connector_quick_action)
        self.app.router.add_post('/api/v1/operator/preview', self.handle_v1_operator_preview)
        self.app.router.add_post('/api/v1/connectors/accounts/{account_id}/refresh', self.handle_v1_connector_refresh)
        self.app.router.add_post('/api/v1/connectors/accounts/{account_id}/revoke', self.handle_v1_connector_revoke)
        self.app.router.add_get('/api/v1/connectors/traces', self.handle_v1_connector_traces)
        self.app.router.add_get('/api/v1/connectors/health', self.handle_v1_connector_health)
        self.app.router.add_get('/api/product/home', self.handle_product_home)
        self.app.router.add_get('/api/product/workflows', self.handle_product_workflows)
        self.app.router.add_get('/api/product/workflows/reports', self.handle_product_workflow_reports)
        self.app.router.add_post('/api/product/workflows/run', self.handle_product_workflow_run)
        self.app.router.add_get('/api/routines', self.handle_routines)
        self.app.router.add_get('/api/routines/templates', self.handle_routine_templates)
        self.app.router.add_post('/api/routines/suggest', self.handle_routine_suggest)
        self.app.router.add_post('/api/routines/from-text', self.handle_routine_from_text)
        self.app.router.add_post('/api/routines/from-draft', self.handle_routine_from_draft)
        self.app.router.add_post('/api/routines', self.handle_routine_create)
        self.app.router.add_post('/api/routines/from-template', self.handle_routine_from_template)
        self.app.router.add_post('/api/routines/toggle', self.handle_routine_toggle)
        self.app.router.add_post('/api/routines/run', self.handle_routine_run)
        self.app.router.add_get('/api/routines/history', self.handle_routine_history)
        self.app.router.add_delete('/api/routines/{id}', self.handle_routine_remove)
        self.app.router.add_get('/api/automations/modules', self.handle_module_automations)
        self.app.router.add_post('/api/automations/modules/action', self.handle_module_automations_action)
        self.app.router.add_post('/api/automations/modules/update', self.handle_module_automations_update)
        self.app.router.add_get('/api/tool-requests', self.handle_tool_requests)
        self.app.router.add_get('/api/tool-requests/stats', self.handle_tool_requests_stats)
        self.app.router.add_get('/api/tool-events', self.handle_tool_events)
        self.app.router.add_get('/api/tools', self.handle_tools)
        self.app.router.add_get('/api/tools/policy', self.handle_tools_policy_get)
        self.app.router.add_get('/api/tools/detail', self.handle_tool_detail)
        self.app.router.add_get('/api/tools/diagnostics', self.handle_tools_diagnostics)
        self.app.router.add_post('/api/tools/policy', self.handle_tools_policy)
        self.app.router.add_post('/api/tools/test', self.handle_tools_test)
        self.app.router.add_get('/api/skills', self.handle_skills)
        self.app.router.add_get('/api/skills/detail', self.handle_skill_detail)
        self.app.router.add_post('/api/skills/from-draft', self.handle_skill_from_draft)
        self.app.router.add_post('/api/skills/install', self.handle_skill_install)
        self.app.router.add_post('/api/skills/toggle', self.handle_skill_toggle)
        self.app.router.add_post('/api/skills/remove', self.handle_skill_remove)
        self.app.router.add_post('/api/skills/update', self.handle_skill_update)
        self.app.router.add_post('/api/skills/refresh', self.handle_skill_refresh)
        self.app.router.add_get('/api/skills/check', self.handle_skill_check)
        self.app.router.add_get('/api/skills/workflows', self.handle_skill_workflows)
        self.app.router.add_post('/api/skills/workflows/toggle', self.handle_skill_workflow_toggle)

        # ── Skill Marketplace API ─────────────────────────────────────────────
        self.app.router.add_get('/api/marketplace/browse', self.handle_marketplace_browse)
        self.app.router.add_get('/api/marketplace/search', self.handle_marketplace_search)
        self.app.router.add_get('/api/marketplace/categories', self.handle_marketplace_categories)
        self.app.router.add_post('/api/marketplace/install', self.handle_marketplace_install)
        self.app.router.add_post('/api/marketplace/review', self.handle_marketplace_review)
        self.app.router.add_post('/api/marketplace/export', self.handle_marketplace_export)
        self.app.router.add_get('/api/integrations/accounts', self.handle_integrations_accounts)
        self.app.router.add_post('/api/integrations/connect', self.handle_integrations_connect)
        self.app.router.add_post('/api/integrations/accounts/connect', self.handle_integrations_account_connect)
        self.app.router.add_post('/api/integrations/accounts/revoke', self.handle_integrations_account_revoke)
        self.app.router.add_get('/api/integrations/traces', self.handle_integration_traces)
        self.app.router.add_get('/api/integrations/summary', self.handle_integration_summary)

        # ── Multi-LLM Engine API ──────────────────────────────────────────────
        self.app.router.add_get('/api/llm/live', self.handle_llm_live_metrics)
        self.app.router.add_post('/api/llm/toggle', self.handle_llm_toggle_model)
        self.app.router.add_post('/api/llm/priority', self.handle_llm_set_priority)
        self.app.router.add_post('/api/llm/reset-circuit', self.handle_llm_reset_circuit)
        self.app.router.add_post('/api/llm/race', self.handle_llm_race)
        self.app.router.add_post('/api/llm/provider-key', self.handle_llm_provider_key)
        self.app.router.add_get('/api/llm/ollama-models', self.handle_llm_ollama_models)
        self.app.router.add_post('/api/llm/ollama-pull', self.handle_llm_ollama_pull)

        # ── LLM Setup Manager API ────────────────────────────────────────────
        self.app.router.add_get('/api/llm/setup/status', self.handle_llm_setup_status)
        self.app.router.add_get('/api/llm/setup/health', self.handle_llm_setup_health)
        self.app.router.add_post('/api/llm/setup/save-key', self.handle_llm_setup_save_key)
        self.app.router.add_post('/api/llm/setup/remove-key', self.handle_llm_setup_remove_key)
        self.app.router.add_get('/api/llm/setup/ollama', self.handle_llm_setup_ollama)
        self.app.router.add_post('/api/llm/setup/ollama-pull', self.handle_llm_setup_ollama_pull)
        self.app.router.add_post('/api/llm/setup/ollama-delete', self.handle_llm_setup_ollama_delete)
        self.app.router.add_get('/api/llm/setup/recommend', self.handle_llm_setup_recommend)

        # ── Dashboard & Web UI (deprecated: desktop-first) ───────────────────
        self.app.router.add_get('/', self.handle_dashboard_page)
        self.app.router.add_get('/dashboard', self.handle_dashboard_page)
        self.app.router.add_get('/trace/{task_id}', self.handle_trace_page)
        self.app.router.add_get('/assets/{filename}', self.handle_brand_asset)
        self.app.router.add_get('/healthz', self.handle_product_health)
        self.app.router.add_get('/ops', self.handle_ops_console_page)
        self.app.router.add_get('/ui/web/{filename}', self.handle_web_asset)
        self.app.router.add_get('/canvas', self.handle_canvas_page)
        self.app.router.add_get('/ws/chat', self.handle_webchat_ws)
        self.app.router.add_get('/ws/dashboard', self.handle_dashboard_ws)
        self.app.router.add_get('/ws/node', self.handle_node_ws)

        # ── Webhook ───────────────────────────────────────────────────────────
        self.app.router.add_post('/hook/{event}', self.handle_webhook)
        self.app.router.add_get('/whatsapp/webhook', self.handle_whatsapp_webhook_verify)
        self.app.router.add_post('/whatsapp/webhook', self.handle_whatsapp_webhook)
        self.app.router.add_post('/sms/webhook', self.handle_sms_webhook)

        # ── Security API ─────────────────────────────────────────────────────
        self.app.router.add_get('/api/security/events', self.handle_security_events)
        self.app.router.add_get('/api/security/pending', self.handle_pending_approvals)
        self.app.router.add_post('/api/security/approve', self.handle_approve_action)
        self.app.router.add_get('/api/v1/privacy/summary', self.handle_privacy_summary)
        self.app.router.add_get('/api/v1/privacy/export', self.handle_privacy_export)
        self.app.router.add_post('/api/v1/privacy/delete', self.handle_privacy_delete)
        self.app.router.add_get('/api/v1/privacy/consent/{user_id}', self.handle_privacy_consent_get)
        self.app.router.add_post('/api/v1/privacy/consent/{user_id}', self.handle_privacy_consent_set)
        self.app.router.add_delete('/api/v1/privacy/data/{user_id}', self.handle_privacy_data_delete)
        self.app.router.add_get('/api/v1/privacy/export/{user_id}', self.handle_privacy_export_user)
        self.app.router.add_get('/api/v1/privacy/learning/stats', self.handle_privacy_learning_stats)
        self.app.router.add_get('/api/v1/privacy/learning/global', self.handle_privacy_learning_global)
        self.app.router.add_post('/api/v1/privacy/learning/pause/{user_id}', self.handle_privacy_learning_pause)
        self.app.router.add_post('/api/v1/privacy/learning/resume/{user_id}', self.handle_privacy_learning_resume)
        self.app.router.add_post('/api/v1/privacy/learning/optout/{user_id}', self.handle_privacy_learning_optout)
        self.app.router.add_get('/api/v1/mobile-dispatch/sessions', self.handle_mobile_dispatch_sessions)
        self.app.router.add_get('/api/v1/operator/status', self.handle_operator_status)
        self.app.router.add_get('/api/privacy/export', self.handle_privacy_export)
        self.app.router.add_post('/api/privacy/delete', self.handle_privacy_delete)
        self.app.router.add_get('/api/interventions', self.handle_interventions_get)
        self.app.router.add_post('/api/interventions/resolve', self.handle_interventions_resolve)
        self.app.router.add_get('/api/health/telemetry', self.handle_health_telemetry)
        
        # ── V2 API ──────────────────────────────────────────────────────────
        self.app.router.add_get('/api/v2/nodes', self.handle_v2_list_nodes)
        self.app.router.add_get('/api/v2/runs', self.handle_v2_list_runs)
        self.app.router.add_get('/api/v2/sessions', self.handle_v2_list_sessions)
        self.app.router.add_get('/inspector', self.handle_inspector_page)

        # ── Elyan Chat API (no auth — desktop-local only) ────────────────────
        self.app.router.add_post('/api/elyan/chat', self.handle_elyan_chat)
        self.app.router.add_post('/api/elyan/chat/stream', self.handle_elyan_chat_stream)
        self.app.router.add_get('/api/elyan/status', self.handle_elyan_status)
        self.app.router.add_post('/api/elyan/voice/trigger', self.handle_elyan_voice_trigger)

    # ── Elyan Chat Handlers ───────────────────────────────────────────────────

    async def handle_elyan_chat(self, request):
        """POST /api/elyan/chat — single-shot Elyan response (no streaming)."""
        try:
            body = await request.json()
        except Exception:
            body = {}
        text = str(body.get("text") or body.get("message") or "").strip()
        user_id = str(body.get("user_id") or "desktop").strip()
        channel = str(body.get("channel") or "desktop").strip()
        if not text:
            return web.json_response({"ok": False, "error": "text required"}, status=400)
        try:
            from core.elyan.elyan_core import get_elyan_core
            core = get_elyan_core()
            resp = await core.handle(text, channel, user_id)
            return web.json_response({
                "ok": True,
                "response": resp.text,
                "intent": resp.metadata.get("intent", ""),
                "requires_approval": resp.metadata.get("requires_approval", False),
                "duration_s": resp.duration_s,
            })
        except Exception as exc:
            logger.error(f"elyan_chat error: {exc}")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_elyan_chat_stream(self, request):
        """POST /api/elyan/chat/stream — SSE streaming Elyan response."""
        import asyncio, json as _json
        try:
            body = await request.json()
        except Exception:
            body = {}
        text = str(body.get("text") or body.get("message") or "").strip()
        user_id = str(body.get("user_id") or "desktop").strip()
        channel = str(body.get("channel") or "desktop").strip()
        if not text:
            return web.Response(text='data: {"error":"text required"}\n\ndata: [DONE]\n\n',
                                content_type="text/event-stream")

        queue: asyncio.Queue = asyncio.Queue()

        async def on_chunk(chunk: str):
            await queue.put(chunk)

        async def generate():
            try:
                from core.elyan.elyan_core import get_elyan_core, ElyanCore
                from core.elyan.elyan_core import IntentCategory
                core = get_elyan_core()

                # Classify first — if executable intent, run fully then stream result
                intent = core.classify_intent(text)
                if intent.category != IntentCategory.CONVERSATION:
                    resp = await core.handle(text, channel, user_id)
                    chunk_data = _json.dumps({"chunk": resp.text}, ensure_ascii=False)
                    yield f"data: {chunk_data}\n\n"
                    yield "data: [DONE]\n\n"
                    return

                # Conversation — stream via Ollama
                from core.elyan.elyan_core import _ollama_stream
                full = ""
                async def _cb(chunk):
                    nonlocal full
                    full += chunk
                    await queue.put(chunk)

                stream_task = asyncio.ensure_future(_ollama_stream(text, _cb))
                while True:
                    try:
                        chunk = await asyncio.wait_for(queue.get(), timeout=0.05)
                        yield f"data: {_json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        if stream_task.done():
                            # Drain remaining
                            while not queue.empty():
                                chunk = queue.get_nowait()
                                yield f"data: {_json.dumps({'chunk': chunk}, ensure_ascii=False)}\n\n"
                            break
                yield "data: [DONE]\n\n"
            except Exception as exc:
                logger.error(f"elyan_stream error: {exc}")
                yield f"data: {_json.dumps({'chunk': f'Hata: {exc}'})}\n\n"
                yield "data: [DONE]\n\n"

        return web.Response(
            body=self._sse_body(generate()),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Access-Control-Allow-Origin": "*",
            },
        )

    def _sse_body(self, gen):
        """Helper: collect async generator into bytes for aiohttp streaming."""
        # For aiohttp, use StreamResponse pattern via middleware approach
        # We return a simple async generator wrapper
        import asyncio

        async def _collect():
            chunks = []
            async for chunk in gen:
                chunks.append(chunk.encode("utf-8"))
            return b"".join(chunks)

        loop = asyncio.get_event_loop()
        return loop.run_until_complete(_collect())

    async def handle_elyan_status(self, request):
        """GET /api/elyan/status — Elyan core status."""
        try:
            from core.elyan.elyan_core import get_elyan_core
            from core.elyan.elyan_startup import _broadcast
            core = get_elyan_core()
            return web.json_response({
                "ok": True,
                "status": "ready",
                "broadcast_active": _broadcast is not None,
            })
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_elyan_voice_trigger(self, request):
        """POST /api/elyan/voice/trigger — Wake voice pipeline."""
        try:
            from core.voice.voice_pipeline import get_voice_pipeline
            pipeline = get_voice_pipeline()
            await pipeline.trigger()
            return web.json_response({"ok": True, "message": "Ses pipeline tetiklendi"})
        except Exception as exc:
            logger.warning(f"voice trigger: {exc}")
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_v2_list_nodes(self, request):
        from core.runtime.node_manager import node_manager
        nodes = node_manager.list_nodes()
        return web.json_response({"ok": True, "nodes": [n.model_dump() for n in nodes]})

    async def handle_v2_list_runs(self, request):
        from core.runtime.lifecycle import run_lifecycle_manager
        runs = list(run_lifecycle_manager._active_runs.values())
        return web.json_response({"ok": True, "runs": [r.model_dump() for n, r in run_lifecycle_manager._active_runs.items()]})

    async def handle_v2_list_sessions(self, request):
        from core.session_engine import session_manager
        sessions = []
        for sid, lane in session_manager._lanes.items():
            sessions.append({
                "session_id": sid,
                "is_locked": lane.is_locked,
                "pending_events": len(lane.get_pending_events()),
                "last_activity": lane._last_activity
            })
        return web.json_response({"ok": True, "sessions": sessions})

    def _dashboard_api(self):
        from api.dashboard_api import get_dashboard_api

        return get_dashboard_api()

    @staticmethod
    def _run_belongs_to_workspace(run_data: dict, workspace_id: str) -> bool:
        """Check if a run dict belongs to the given workspace.

        Legacy runs without workspace_id are allowed through so existing
        data remains accessible after the field is introduced.
        """
        run_ws = str(
            run_data.get("workspace_id")
            or (run_data.get("metadata") or {}).get("workspace_id")
            or ""
        ).strip()
        if not run_ws:
            return True  # legacy run — no workspace tag yet
        return run_ws == workspace_id

    async def handle_v1_list_runs(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        try:
            limit = int(request.rel_url.query.get("limit", 20))
        except Exception:
            limit = 20
        status = str(request.rel_url.query.get("status", "") or "").strip() or None
        result = await self._dashboard_api().list_runs(limit=limit, status=status)
        if result.get("success") and isinstance(result.get("runs"), list):
            filtered = [r for r in result["runs"] if self._run_belongs_to_workspace(r, workspace_id)]
            result["runs"] = filtered
            result["count"] = len(filtered)
        return web.json_response(result)

    async def handle_v1_get_run(self, request):
        run_id = str(request.match_info.get("run_id") or "").strip()
        if not run_id:
            return _json_error("run_id required", status=400)
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        result = await self._dashboard_api().get_run(run_id)
        if result.get("success") and isinstance(result.get("run"), dict):
            if not self._run_belongs_to_workspace(result["run"], workspace_id):
                return _json_error("workspace_access_denied", status=403)
        return web.json_response(result)

    async def handle_v1_get_run_timeline(self, request):
        run_id = str(request.match_info.get("run_id") or "").strip()
        if not run_id:
            return _json_error("run_id required", status=400)
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        run_result = await self._dashboard_api().get_run(run_id)
        if run_result.get("success") and isinstance(run_result.get("run"), dict):
            if not self._run_belongs_to_workspace(run_result["run"], workspace_id):
                return _json_error("workspace_access_denied", status=403)
        return web.json_response(await self._dashboard_api().get_step_timeline(run_id))

    async def handle_v1_cancel_run(self, request):
        run_id = str(request.match_info.get("run_id") or "").strip()
        if not run_id:
            return _json_error("run_id required", status=400)
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        run_result = await self._dashboard_api().get_run(run_id)
        if run_result.get("success") and isinstance(run_result.get("run"), dict):
            if not self._run_belongs_to_workspace(run_result["run"], workspace_id):
                return _json_error("workspace_access_denied", status=403)
        return web.json_response(await self._dashboard_api().cancel_run(run_id))

    async def handle_v1_pending_approvals(self, request):
        return web.json_response(self._dashboard_api().get_pending_approvals())

    async def handle_v1_resolve_approval(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "invalid json"}, status=400)
        request_id = str(data.get("request_id") or data.get("id") or "").strip()
        if not request_id:
            return web.json_response({"success": False, "error": "request_id required"}, status=400)
        approved = bool(data.get("approved", False))
        resolver_id = str(data.get("resolver_id") or "desktop_operator").strip()
        return web.json_response(self._dashboard_api().resolve_approval(request_id, approved, resolver_id))

    async def handle_v1_bulk_resolve_approvals(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "invalid json"}, status=400)
        request_ids = [str(item).strip() for item in (data.get("request_ids") or []) if str(item).strip()]
        if not request_ids:
            return web.json_response({"success": False, "error": "request_ids required"}, status=400)
        approved = bool(data.get("approved", False))
        resolver_id = str(data.get("resolver_id") or "desktop_operator").strip()
        return web.json_response(self._dashboard_api().bulk_resolve_approvals(request_ids, approved, resolver_id))

    async def handle_v1_tool_metrics(self, request):
        return web.json_response(await self._dashboard_api().get_tool_metrics())

    async def handle_v1_multi_agent_metrics(self, request):
        return web.json_response(await self._dashboard_api().get_multi_agent_metrics())

    async def handle_v1_runtime_backends(self, request):
        return web.json_response(await self._dashboard_api().get_runtime_backends())

    async def handle_v1_system_overview(self, request):
        from core.platforms_overview import build_platforms_payload
        from core.skills_overview import build_skills_summary
        from core.llm_setup import get_llm_setup

        home = await self._build_product_home_payload()
        readiness = dict(home.get("readiness") or {})
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []
        status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
        live_channels = []
        for item in channels:
            if not isinstance(item, dict):
                continue
            channel_type = str(item.get("type") or "").strip().lower()
            if not channel_type:
                continue
            live_channels.append(
                {
                    "type": channel_type,
                    "status": str(status_map.get(channel_type) or ""),
                    "detail": str(item.get("mode") or item.get("id") or ""),
                }
            )

        platforms = build_platforms_payload(
            config={"channels": channels},
            gateway={"running": True, "pid": None},
            live_channels=live_channels,
        )
        skills = build_skills_summary()

        setup = get_llm_setup()
        provider_rows = await setup.get_all_provider_status()
        ollama_status = await setup.ollama_status()
        provider_summary = {
            "available": sum(
                1 for provider in provider_rows if str(provider.get("status") or "").strip().lower() in {"connected", "available", "ready"}
            ),
            "auth_required": sum(
                1
                for provider in provider_rows
                if "key" in str(provider.get("status") or "").strip().lower()
                or "auth" in str(provider.get("status") or "").strip().lower()
            ),
            "degraded": sum(
                1 for provider in provider_rows if str(provider.get("status") or "").strip().lower() in {"degraded", "error", "unreachable"}
            ),
        }

        return _json_ok(
            {
                "readiness": readiness,
                "platforms": platforms,
                "skills": skills.get("summary", {}),
                "providers": {
                    "summary": provider_summary,
                    "rows": provider_rows,
                },
                "ollama": {
                    "ready": bool(ollama_status.get("running")),
                    "status": ollama_status,
                },
            }
        )

    async def handle_v1_security_summary(self, request):
        return web.json_response(await self._dashboard_api().get_security_summary())

    async def handle_v1_learning_summary(self, request):
        user_id = self._actor_id(request)
        return web.json_response(
            {
                "success": True,
                "summary": get_learning_control_plane().get_learning_summary(user_id),
            }
        )

    async def handle_v1_security_events(self, request):
        try:
            limit = int(request.rel_url.query.get("limit", 40))
        except Exception:
            limit = 40
        return web.json_response(await self._dashboard_api().get_security_events(limit=limit))

    async def handle_v1_inbox_events(self, request):
        workspace_id = self._workspace_id(request)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        runtime_db = self._runtime_db()
        if request.method == "GET":
            try:
                limit = int(request.rel_url.query.get("limit", 12))
            except Exception:
                limit = 12
            source_type = str(request.rel_url.query.get("source_type", "") or "").strip()
            return _json_ok(
                {
                    "workspace_id": workspace_id,
                    "events": runtime_db.inbox.list_events(
                        workspace_id,
                        limit=max(1, min(limit, 50)),
                        source_type=source_type,
                    ),
                }
            )

        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        execution_allowed, execution_error = self._require_execution_seat(request, data)
        if not execution_allowed:
            return _json_error(execution_error, status=403)
        content = str(data.get("content") or "").strip()
        if not content:
            return _json_error("content required", status=400)
        source_type = _normalize_inbox_source(str(data.get("source_type") or "manual"))
        summary = _extract_task_summary(
            content,
            source_type=source_type,
            title=str(data.get("title") or "").strip(),
        ) if bool(data.get("analyze", True)) else None
        event = runtime_db.inbox.create_event(
            workspace_id=workspace_id,
            source_type=source_type,
            source_id=str(data.get("source_id") or "").strip(),
            title=str(data.get("title") or "").strip(),
            content=content,
            summary=summary,
            status="triaged" if summary else "received",
            metadata={
                "captured_via": "desktop",
                "actor_id": self._actor_id(request, data),
                **(dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {}),
            },
        )
        billing_warning = ""
        try:
            self._workspace_billing().record_usage(
                workspace_id,
                "inbox_events",
                1,
                metadata={"event_id": event.get("event_id"), "source_type": source_type},
            )
            if summary is not None:
                self._workspace_billing().record_usage(
                    workspace_id,
                    "task_extractions",
                    1,
                    metadata={
                        "event_id": event.get("event_id"),
                        "source_type": source_type,
                        "task_type": str(summary.get("task_type") or "cowork"),
                        "estimated_credits": 1,
                    },
                )
        except RuntimeError as exc:
            billing_warning = str(exc)
        push_activity("inbox_event", "desktop", f"{source_type} intake captured", True)
        payload = {"workspace_id": workspace_id, "event": event, "extraction": summary}
        if billing_warning:
            payload["billing_warning"] = billing_warning
        return _json_ok(payload, status=201)

    async def handle_v1_task_extract(self, request):
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        execution_allowed, execution_error = self._require_execution_seat(request, data)
        self._observe_execution_guard(
            request,
            action="task_extract",
            phase="seat_gate",
            payload=data,
            allowed=execution_allowed,
            reason=execution_error,
            checks=[
                ExecutionCheck(
                    name="execution_seat",
                    allowed=execution_allowed,
                    reason=execution_error,
                    metadata={"required_roles": ["owner", "operator", "admin"]},
                )
            ],
            metadata={"source": "task_extract", "event_id": str(data.get("event_id") or "").strip()},
        )
        if not execution_allowed:
            return _json_error(execution_error, status=403)
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        runtime_db = self._runtime_db()
        event = None
        event_id = str(data.get("event_id") or "").strip()
        if event_id:
            event = runtime_db.inbox.get_event(event_id)
            if event is None:
                return _json_error("event not found", status=404)
            if str(event.get("workspace_id") or "") != workspace_id:
                return _json_error("workspace mismatch", status=403)
        source_type = _normalize_inbox_source(
            str(data.get("source_type") or (event or {}).get("source_type") or "manual")
        )
        content = str(data.get("content") or (event or {}).get("content") or "").strip()
        if not content:
            return _json_error("content required", status=400)
        summary = _extract_task_summary(
            content,
            source_type=source_type,
            title=str(data.get("title") or (event or {}).get("title") or "").strip(),
        )
        updated_event = runtime_db.inbox.update_summary(event_id, summary=summary, status="triaged") if event_id else None
        billing_warning = ""
        task_usage = None
        try:
            task_usage = self._workspace_billing().record_usage(
                workspace_id,
                "task_extractions",
                1,
                metadata={
                    "event_id": event_id,
                    "source_type": source_type,
                    "task_type": str(summary.get("task_type") or "cowork"),
                    "estimated_credits": 1,
                },
            )
        except RuntimeError as exc:
            billing_warning = str(exc)
        push_activity("task_extract", "desktop", f"{source_type} task extracted", True)
        payload = {"workspace_id": workspace_id, "summary": summary}
        if updated_event is not None:
            payload["event"] = updated_event
        if isinstance(task_usage, dict):
            payload["billing_usage_id"] = str(task_usage.get("usage_id") or "")
        if billing_warning:
            payload["billing_warning"] = billing_warning
        self._observe_execution_guard(
            request,
            action="task_extract",
            phase="completed",
            payload=data,
            allowed=True,
            checks=[
                ExecutionCheck(
                    name="summary_generated",
                    allowed=True,
                    metadata={
                        "task_type": str(summary.get("task_type") or "cowork"),
                        "needs_approval": bool(summary.get("needs_approval", False)),
                    },
                )
            ],
            metadata={
                "source_type": source_type,
                "event_id": event_id,
                "billing_warning": billing_warning,
            },
        )
        return _json_ok(payload)

    async def handle_v1_start_workflow(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"success": False, "error": "invalid json"}, status=400)

        task_type = str(data.get("task_type") or data.get("workflow") or "").strip().lower()
        brief = str(data.get("brief") or data.get("prompt") or "").strip()
        if not task_type:
            return web.json_response({"success": False, "error": "task_type required"}, status=400)
        if not brief:
            return web.json_response({"success": False, "error": "brief required"}, status=400)
        execution_allowed, execution_error = self._require_execution_seat(request, data)
        self._observe_execution_guard(
            request,
            action="workflow_run",
            phase="seat_gate",
            payload=data,
            allowed=execution_allowed,
            reason=execution_error,
            checks=[
                ExecutionCheck(
                    name="execution_seat",
                    allowed=execution_allowed,
                    reason=execution_error,
                    metadata={"required_roles": ["owner", "operator", "admin"]},
                )
            ],
            metadata={"task_type": task_type, "prompt_length": len(brief)},
            default_session_id="desktop",
        )
        if not execution_allowed:
            return _json_error(execution_error, status=403)
        credit_decision = self._usage_credit_decision(
            request,
            "workflow_runs",
            payload=data,
            metadata={
                "task_type": task_type,
                "prompt_length": len(brief),
                "routing_profile": str(data.get("routing_profile") or "balanced").strip() or "balanced",
                "review_strictness": str(data.get("review_strictness") or "balanced").strip() or "balanced",
            },
        )
        credit_allowed = bool(credit_decision.get("allowed", True))
        self._observe_execution_guard(
            request,
            action="workflow_run",
            phase="credit_gate",
            payload=data,
            allowed=credit_allowed,
            reason=str(credit_decision.get("reason") or ""),
            checks=[
                ExecutionCheck(
                    name="credit_authorization",
                    allowed=credit_allowed,
                    reason=str(credit_decision.get("reason") or ""),
                    metadata=credit_decision,
                )
            ],
            metadata={"metric": "workflow_runs", "task_type": task_type},
            default_session_id="desktop",
        )
        if not credit_decision.get("allowed", True):
            return self._credit_block_response(credit_decision, action_label="workflow run")
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        workflow_usage = None
        try:
            workflow_usage = self._record_provisional_usage(
                request,
                metric="workflow_runs",
                payload=data,
                metadata={
                    "task_type": task_type,
                    "routing_profile": str(data.get("routing_profile") or "balanced").strip() or "balanced",
                    "review_strictness": str(data.get("review_strictness") or "balanced").strip() or "balanced",
                    "estimated_credits": int(credit_decision.get("estimated_credits") or 0),
                    "prompt_length": len(brief),
                },
            )
        except Exception as exc:
            self._observe_execution_guard(
                request,
                action="workflow_run",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"task_type": task_type, "failure_class": "billing_reservation_failed"},
                level="error",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": "billing reservation failed"}, status=500)

        from core.workflow.vertical_runner import get_vertical_workflow_runner

        try:
            record = await get_vertical_workflow_runner().start_workflow(
                task_type=task_type,
                brief=brief,
                session_id=str(data.get("session_id") or "desktop").strip() or "desktop",
                title=str(data.get("title") or data.get("project_name") or "").strip(),
                audience=str(data.get("audience") or "executive").strip() or "executive",
                language=str(data.get("language") or "tr").strip() or "tr",
                theme=str(data.get("theme") or "premium").strip() or "premium",
                stack=str(data.get("stack") or "react").strip() or "react",
                preferred_formats=data.get("preferred_formats"),
                project_template_id=str(data.get("project_template_id") or "").strip(),
                project_name=str(data.get("project_name") or data.get("title") or "").strip(),
                routing_profile=str(data.get("routing_profile") or "balanced").strip() or "balanced",
                review_strictness=str(data.get("review_strictness") or "balanced").strip() or "balanced",
                output_dir=str(data.get("output_dir") or "").strip(),
                thread_id=str(data.get("thread_id") or "").strip(),
                workspace_id=workspace_id,
                actor_id=self._actor_id(request, data),
                billing_usage_id=str((workflow_usage or {}).get("usage_id") or ""),
                background=True,
            )
        except ValueError as exc:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((workflow_usage or {}).get("usage_id") or ""),
                failure_class="validation_error",
                metadata={"task_type": task_type, "reason": str(exc)},
            )
            self._observe_execution_guard(
                request,
                action="workflow_run",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"task_type": task_type, "failure_class": "validation_error"},
                level="warning",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": str(exc)}, status=400)
        except Exception as exc:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((workflow_usage or {}).get("usage_id") or ""),
                failure_class="runtime_error",
                metadata={"task_type": task_type, "reason": str(exc)},
            )
            self._observe_execution_guard(
                request,
                action="workflow_run",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"task_type": task_type, "failure_class": "runtime_error"},
                level="error",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": str(exc)}, status=500)
        self._observe_execution_guard(
            request,
            action="workflow_run",
            phase="dispatched",
            payload=data,
            allowed=True,
            checks=[
                ExecutionCheck(
                    name="workflow_dispatched",
                    allowed=True,
                    metadata={
                        "workflow_state": str(getattr(record, "workflow_state", "") or ""),
                        "task_type": task_type,
                    },
                )
            ],
            metadata={"estimated_credits": int(credit_decision.get("estimated_credits") or 0)},
            run_id=str(getattr(record, "run_id", "") or ""),
            default_session_id="desktop",
        )
        push_activity("workflow_run", "desktop", f"{task_type} flow started", True)
        return _json_ok(
            {
                "accepted": True,
                "run_id": record.run_id,
                "billing_usage_id": str((workflow_usage or {}).get("usage_id") or ""),
                "task_type": record.task_type,
                "workflow_state": record.workflow_state,
                "run": record.to_dict(),
            }
        )

    async def handle_v1_auth_bootstrap_owner(self, request):
        if not _is_loopback_request(request):
            return _json_error("owner bootstrap is restricted to localhost", status=403)
        remote_ip = _request_remote_host(request)
        if _is_auth_rate_limited(remote_ip):
            return _json_error("too many failed authentication attempts, try again later", status=429)
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        email = str(data.get("email") or "").strip().lower()
        password = str(data.get("password") or "")
        workspace_id = str(data.get("workspace_id") or "local-workspace").strip() or "local-workspace"
        if not email:
            _record_auth_failure(remote_ip)
            return _json_error("email required", status=400)
        if not password:
            _record_auth_failure(remote_ip)
            return _json_error("password required", status=400)
        runtime_db = get_runtime_database()
        if self._local_user_count(runtime_db) > 0:
            return _json_error("owner bootstrap already completed", status=409)
        try:
            user = runtime_db.auth.bootstrap_owner(
                email=email,
                password=password,
                display_name=str(data.get("display_name") or email.split("@", 1)[0]),
                workspace_id=workspace_id,
                metadata={"bootstrap_source": "gateway_setup"},
            )
        except ValueError as exc:
            _record_auth_failure(remote_ip)
            return _json_error(str(exc), status=400)
        session, session_token = runtime_db.auth_sessions.create_session(
            user=user,
            metadata={
                "client": "desktop",
                "login_source": "bootstrap_owner",
            },
        )
        session = self._ensure_conversation_session_context(session)
        # Mark the initial setup complete so subsequent health checks reflect this
        try:
            mark_setup_complete({"bootstrap_source": "gateway_bootstrap_owner"})
        except Exception as _mk_exc:
            logger.warning(f"mark_setup_complete failed (non-fatal): {_mk_exc}")
        response = _json_ok(
            {
                "workspace_id": str(user.get("workspace_id") or workspace_id),
                "session_token": session_token,
                "csrf_token": "",
                "user": {
                    "user_id": str(user.get("user_id") or ""),
                    "email": str(user.get("email") or email),
                    "display_name": str(user.get("display_name") or ""),
                    "status": str(user.get("status") or "active"),
                    "role": "owner",
                },
                "session": {
                    "session_id": str(session.get("session_id") or ""),
                    "conversation_session_id": str(session.get("conversation_session_id") or ""),
                    "expires_at": float(session.get("expires_at") or 0.0),
                },
            }
        )
        _clear_auth_failures(remote_ip)
        response.headers["X-Elyan-Session-Token"] = session_token
        response.set_cookie(
            "elyan_user_session",
            session_token,
            httponly=True,
            samesite="Strict",
            secure=False,
            path="/",
        )
        csrf_token = self._set_csrf_cookie(response)
        response.text = json.dumps({**json.loads(response.text), "csrf_token": csrf_token})
        return response

    async def handle_v1_auth_login(self, request):
        if not _is_loopback_request(request):
            return _json_error("local login is restricted to localhost", status=403)
        remote_ip = _request_remote_host(request)
        if _is_auth_rate_limited(remote_ip):
            return _json_error("too many failed authentication attempts, try again later", status=429)
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        email = str(data.get("email") or "").strip().lower()
        password = str(data.get("password") or "")
        workspace_id = str(data.get("workspace_id") or "").strip()
        if not email:
            _record_auth_failure(remote_ip)
            return _json_error("email required", status=400)
        if not password:
            _record_auth_failure(remote_ip)
            return _json_error("password required", status=400)
        runtime_db = get_runtime_database()
        user = runtime_db.auth.authenticate_user(
            email=email,
            password=password,
            workspace_id=workspace_id,
        )
        if not user:
            if self._local_user_count(runtime_db) == 0:
                return _json_error("owner bootstrap required before login", status=409, payload={"bootstrap_required": True})
            _record_auth_failure(remote_ip)
            return _json_error("invalid credentials", status=401)
        session, session_token = runtime_db.auth_sessions.create_session(
            user=user,
            metadata={
                "client": "desktop",
                "login_source": "local_login",
            },
        )
        session = self._ensure_conversation_session_context(session)
        response = _json_ok(
            {
                "workspace_id": str(user.get("workspace_id") or workspace_id),
                "session_token": session_token,
                "csrf_token": "",
                "user": {
                    "user_id": str(user.get("user_id") or ""),
                    "email": str(user.get("email") or email),
                    "display_name": str(user.get("display_name") or ""),
                    "status": str(user.get("status") or "active"),
                    "role": str(user.get("role") or session.get("role") or runtime_db.access.get_actor_role(
                        workspace_id=str(user.get("workspace_id") or workspace_id or "local-workspace"),
                        actor_id=str(user.get("user_id") or ""),
                    )),
                },
                "session": {
                    "session_id": str(session.get("session_id") or ""),
                    "conversation_session_id": str(session.get("conversation_session_id") or ""),
                    "expires_at": float(session.get("expires_at") or 0.0),
                },
            }
        )
        _clear_auth_failures(remote_ip)
        response.headers["X-Elyan-Session-Token"] = session_token
        response.set_cookie(
            "elyan_user_session",
            session_token,
            httponly=True,
            samesite="Strict",
            secure=False,
            path="/",
        )
        csrf_token = self._set_csrf_cookie(response)
        response.text = json.dumps({**json.loads(response.text), "csrf_token": csrf_token})
        return response

    async def handle_v1_auth_logout(self, request):
        session_token = str(
            request.headers.get("X-Elyan-Session-Token", "")
            or request.cookies.get("elyan_user_session", "")
            or ""
        ).strip()
        if session_token:
            get_runtime_database().auth_sessions.revoke_session(session_token)
        response = _json_ok()
        response.del_cookie("elyan_user_session", path="/")
        self._clear_csrf_cookie(response)
        return response

    async def handle_v1_auth_me(self, request):
        allowed, error, session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return _json_error(error, status=403)
        response = _json_ok(
            {
                "workspace_id": str(session.get("workspace_id") or "local-workspace"),
                "csrf_token": str(request.cookies.get("elyan_csrf_token", "") or ""),
                "user": {
                    "user_id": str(session.get("user_id") or ""),
                    "email": str(session.get("email") or ""),
                    "display_name": str(session.get("display_name") or ""),
                    "status": str(session.get("status") or "active"),
                    "role": str(session.get("role") or "member"),
                },
                "session": {
                    "session_id": str(session.get("session_id") or ""),
                    "conversation_session_id": str(session.get("conversation_session_id") or ""),
                    "expires_at": float(session.get("expires_at") or 0.0),
                },
            }
        )
        return response

    async def handle_v1_admin_workspaces(self, request):
        return await self._workspace_admin_controller().handle_list_workspaces(request)

    async def handle_v1_admin_workspace_create(self, request):
        return await self._workspace_admin_controller().handle_create_workspace(request)

    async def handle_v1_admin_workspace_detail(self, request):
        return await self._workspace_admin_controller().handle_get_workspace(request)

    async def handle_v1_admin_workspace_members(self, request):
        return await self._workspace_admin_controller().handle_list_members(request)

    async def handle_v1_admin_workspace_invites(self, request):
        return await self._workspace_admin_controller().handle_create_invite(request)

    async def handle_v1_admin_workspace_invites_list(self, request):
        return await self._workspace_admin_controller().handle_list_invites(request)

    async def handle_v1_admin_workspace_invite_accept(self, request):
        return await self._workspace_admin_controller().handle_accept_invite(request)

    async def handle_v1_admin_workspace_member_role(self, request):
        return await self._workspace_admin_controller().handle_update_role(request)

    async def handle_v1_admin_workspace_seat_assign(self, request):
        return await self._workspace_admin_controller().handle_assign_seat(request)

    async def handle_v1_cowork_home(self, request):
        workspace_id = self._workspace_id(request)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        user_id = self._actor_id(request)
        home = await self._cowork_store().home_snapshot(workspace_id=workspace_id, limit=8)
        approvals = self._mission_store().pending_approvals(owner=workspace_id)
        billing = self._workspace_billing().get_workspace_summary(workspace_id)
        try:
            autopilot_status = get_autopilot().get_status()
        except Exception as exc:
            autopilot_status = {
                "enabled": False,
                "running": False,
                "error": str(exc),
            }
        try:
            background_tasks = [
                self._normalize_background_task(record)
                for record in away_task_registry.list_for_user(user_id, limit=6)
            ]
        except Exception:
            background_tasks = []
        # ── Continuity surface (yarım kalan görevler) ────────────────────
        continuity = {}
        try:
            from core.task_continuity import get_task_continuity_manager
            continuity = get_task_continuity_manager().get_continuity_surface(
                workspace_id, user_id, max_results=3
            )
        except Exception:
            continuity = {}

        # ── Workspace intelligence summary ───────────────────────────────
        workspace_intel = {}
        try:
            from core.workspace.intelligence import get_workspace_intelligence
            profile_ws = get_workspace_intelligence().get_profile(workspace_id)
            workspace_intel = profile_ws.to_dict()
        except Exception:
            workspace_intel = {}

        return _json_ok(
            {
                "workspace_id": workspace_id,
                "recent_threads": home.get("recent_threads", []),
                "last_thread": home.get("last_thread"),
                "active_count": home.get("active_count", 0),
                "pending_approvals": approvals[:12],
                "background_tasks": background_tasks,
                "autopilot": {
                    "enabled": bool(autopilot_status.get("enabled", False)),
                    "running": bool(autopilot_status.get("running", False)),
                    "last_tick_at": float(autopilot_status.get("last_tick_at") or 0.0),
                    "last_tick_reason": str(autopilot_status.get("last_tick_reason") or ""),
                    "last_briefing": dict(autopilot_status.get("last_briefing") or {}),
                    "last_suggestions": list(autopilot_status.get("last_suggestions") or [])[:6],
                    "last_task_review": list(autopilot_status.get("last_task_review") or [])[:6],
                    "last_interventions": list(autopilot_status.get("last_interventions") or [])[:4],
                },
                "billing": billing,
                "continuity": continuity,
                "workspace_intelligence": workspace_intel,
            }
        )

    async def handle_v1_cowork_continuity(self, request):
        """GET /api/v1/cowork/continuity — Session start continuity surface."""
        workspace_id = self._workspace_id(request)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        user_id = self._actor_id(request)
        try:
            from core.task_continuity import get_task_continuity_manager
            surface = get_task_continuity_manager().get_continuity_surface(
                workspace_id, user_id, max_results=5
            )
            return _json_ok({"continuity": surface, "workspace_id": workspace_id})
        except Exception as exc:
            return _json_ok({"continuity": {"has_open_tasks": False, "count": 0, "candidates": []}, "error": str(exc)})

    async def handle_v1_workspace_intelligence(self, request):
        """GET /api/v1/workspace/intelligence — Workspace intelligence profile."""
        workspace_id = self._workspace_id(request)
        force = request.rel_url.query.get("force", "").lower() in {"1", "true", "yes"}
        try:
            from core.workspace.intelligence import get_workspace_intelligence
            profile = get_workspace_intelligence().get_profile(workspace_id, force_refresh=force)
            return _json_ok({"intelligence": profile.to_dict(), "workspace_id": workspace_id})
        except Exception as exc:
            return _json_error(f"workspace intelligence unavailable: {exc}", status=500)

    async def handle_v1_cowork_threads(self, request):
        workspace_id = self._workspace_id(request)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        if request.method == "GET":
            try:
                limit = int(request.rel_url.query.get("limit", 20))
            except Exception:
                limit = 20
            threads = await self._cowork_store().list_threads(workspace_id=workspace_id, limit=limit)
            return _json_ok({"threads": threads, "workspace_id": workspace_id})

        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        prompt = str(data.get("prompt") or data.get("brief") or "").strip()
        if not prompt:
            return _json_error("prompt required", status=400)
        execution_allowed, execution_error = self._require_execution_seat(request, data)
        self._observe_execution_guard(
            request,
            action="cowork_thread_create",
            phase="seat_gate",
            payload=data,
            allowed=execution_allowed,
            reason=execution_error,
            checks=[
                ExecutionCheck(
                    name="execution_seat",
                    allowed=execution_allowed,
                    reason=execution_error,
                    metadata={"required_roles": ["owner", "operator", "admin"]},
                )
            ],
            metadata={"mode": str(data.get("current_mode") or data.get("mode") or "").strip().lower() or "cowork"},
            default_session_id="desktop",
        )
        if not execution_allowed:
            return _json_error(execution_error, status=403)
        requested_mode = str(data.get("current_mode") or data.get("mode") or "").strip().lower() or "cowork"
        credit_decision = self._usage_credit_decision(
            request,
            "cowork_threads",
            payload=data,
            metadata={
                "mode": requested_mode,
                "prompt_length": len(prompt),
                "routing_profile": str(data.get("routing_profile") or "balanced").strip() or "balanced",
                "review_strictness": str(data.get("review_strictness") or "balanced").strip() or "balanced",
            },
        )
        credit_allowed = bool(credit_decision.get("allowed", True))
        self._observe_execution_guard(
            request,
            action="cowork_thread_create",
            phase="credit_gate",
            payload=data,
            allowed=credit_allowed,
            reason=str(credit_decision.get("reason") or ""),
            checks=[
                ExecutionCheck(
                    name="credit_authorization",
                    allowed=credit_allowed,
                    reason=str(credit_decision.get("reason") or ""),
                    metadata=credit_decision,
                )
            ],
            metadata={"metric": "cowork_threads", "mode": requested_mode},
            default_session_id="desktop",
        )
        if not credit_decision.get("allowed", True):
            return self._credit_block_response(credit_decision, action_label="cowork thread")
        limit_state = self._workspace_billing().enforce_limit(
            workspace_id,
            metric="max_threads",
            current_value=await self._cowork_store().count_threads(workspace_id=workspace_id),
        )
        limit_allowed = bool(limit_state.get("allowed", True))
        self._observe_execution_guard(
            request,
            action="cowork_thread_create",
            phase="limit_gate",
            payload=data,
            allowed=limit_allowed,
            reason=str(limit_state.get("reason") or ""),
            checks=[
                ExecutionCheck(
                    name="thread_limit",
                    allowed=limit_allowed,
                    reason=str(limit_state.get("reason") or ""),
                    metadata=limit_state,
                )
            ],
            metadata={"metric": "max_threads", "mode": requested_mode},
            default_session_id="desktop",
        )
        if not limit_state.get("allowed", True):
            return _json_error(str(limit_state.get("reason") or "thread limit reached"), status=402, payload={"limit": limit_state})
        try:
            thread_usage = self._record_provisional_usage(
                request,
                metric="cowork_threads",
                payload=data,
                metadata={
                    "mode": requested_mode,
                    "routing_profile": str(data.get("routing_profile") or "balanced").strip() or "balanced",
                    "review_strictness": str(data.get("review_strictness") or "balanced").strip() or "balanced",
                    "estimated_credits": int(credit_decision.get("estimated_credits") or 0),
                    "prompt_length": len(prompt),
                },
            )
        except Exception as exc:
            self._observe_execution_guard(
                request,
                action="cowork_thread_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"failure_class": "billing_reservation_failed", "mode": requested_mode},
                level="error",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": "billing reservation failed"}, status=500)
        try:
            detail = await self._cowork_store().create_thread(
                prompt=prompt,
                workspace_id=workspace_id,
                session_id=str(data.get("session_id") or "desktop").strip() or "desktop",
                preferred_mode=str(data.get("current_mode") or data.get("mode") or "").strip(),
                project_template_id=str(data.get("project_template_id") or "").strip(),
                routing_profile=str(data.get("routing_profile") or "balanced").strip() or "balanced",
                review_strictness=str(data.get("review_strictness") or "balanced").strip() or "balanced",
                user_id=self._actor_id(request, data),
                agent=self.agent,
                metadata={
                    "project_template_id": str(data.get("project_template_id") or "").strip(),
                    "project_name": str(data.get("project_name") or "").strip(),
                },
                billing_usage_id=str((thread_usage or {}).get("usage_id") or ""),
                billing_metric="cowork_threads",
            )
        except KeyError:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((thread_usage or {}).get("usage_id") or ""),
                failure_class="thread_missing",
                metadata={"mode": requested_mode},
            )
            self._observe_execution_guard(
                request,
                action="cowork_thread_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason="thread not found",
                metadata={"failure_class": "thread_missing", "mode": requested_mode},
                level="warning",
                default_session_id="desktop",
            )
            return _json_error("thread not found", status=404)
        except ValueError as exc:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((thread_usage or {}).get("usage_id") or ""),
                failure_class="validation_error",
                metadata={"mode": requested_mode, "reason": str(exc)},
            )
            self._observe_execution_guard(
                request,
                action="cowork_thread_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"failure_class": "validation_error", "mode": requested_mode},
                level="warning",
                default_session_id="desktop",
            )
            return _json_error(str(exc), status=400)
        except Exception as exc:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((thread_usage or {}).get("usage_id") or ""),
                failure_class="runtime_error",
                metadata={"mode": requested_mode, "reason": str(exc)},
            )
            self._observe_execution_guard(
                request,
                action="cowork_thread_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"failure_class": "runtime_error", "mode": requested_mode},
                level="error",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": str(exc)}, status=500)
        self._observe_execution_guard(
            request,
            action="cowork_thread_create",
            phase="dispatched",
            payload=data,
            allowed=True,
            checks=[
                ExecutionCheck(
                    name="thread_created",
                    allowed=True,
                    metadata={
                        "thread_id": str(detail.get("thread_id") or ""),
                        "mode": str(detail.get("current_mode") or requested_mode),
                    },
                )
            ],
            metadata={"estimated_credits": int(credit_decision.get("estimated_credits") or 0)},
            default_session_id="desktop",
        )
        push_cowork_event("cowork.thread.updated", detail)
        return _json_ok(
            {
                "thread": detail,
                "workspace_id": workspace_id,
                "billing_usage_id": str((thread_usage or {}).get("usage_id") or ""),
            }
        )

    async def handle_v1_cowork_thread_detail(self, request):
        thread_id = str(request.match_info.get("thread_id") or "").strip()
        if not thread_id:
            return _json_error("thread_id required", status=400)
        workspace_id = self._workspace_id(request)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        try:
            detail = await self._cowork_store().get_thread_detail(thread_id)
        except KeyError:
            return _json_error("thread not found", status=404)
        if str(detail.get("workspace_id") or "").strip() != workspace_id:
            return _json_error("workspace_access_denied", status=403)
        return _json_ok({"thread": detail})

    async def handle_v1_cowork_thread_turn(self, request):
        thread_id = str(request.match_info.get("thread_id") or "").strip()
        if not thread_id:
            return _json_error("thread_id required", status=400)
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        prompt = str(data.get("prompt") or "").strip()
        if not prompt:
            return _json_error("prompt required", status=400)
        execution_allowed, execution_error = self._require_execution_seat(request, data)
        self._observe_execution_guard(
            request,
            action="cowork_turn_create",
            phase="seat_gate",
            payload=data,
            allowed=execution_allowed,
            reason=execution_error,
            checks=[
                ExecutionCheck(
                    name="execution_seat",
                    allowed=execution_allowed,
                    reason=execution_error,
                    metadata={"required_roles": ["owner", "operator", "admin"]},
                )
            ],
            metadata={"thread_id": thread_id},
            default_session_id="desktop",
        )
        if not execution_allowed:
            return _json_error(execution_error, status=403)
        requested_mode = str(data.get("current_mode") or data.get("mode") or "").strip().lower() or "cowork"
        credit_decision = self._usage_credit_decision(
            request,
            "cowork_turns",
            payload=data,
            metadata={
                "mode": requested_mode,
                "prompt_length": len(prompt),
                "routing_profile": str(data.get("routing_profile") or "balanced").strip() or "balanced",
                "review_strictness": str(data.get("review_strictness") or "balanced").strip() or "balanced",
            },
        )
        credit_allowed = bool(credit_decision.get("allowed", True))
        self._observe_execution_guard(
            request,
            action="cowork_turn_create",
            phase="credit_gate",
            payload=data,
            allowed=credit_allowed,
            reason=str(credit_decision.get("reason") or ""),
            checks=[
                ExecutionCheck(
                    name="credit_authorization",
                    allowed=credit_allowed,
                    reason=str(credit_decision.get("reason") or ""),
                    metadata=credit_decision,
                )
            ],
            metadata={"metric": "cowork_turns", "thread_id": thread_id, "mode": requested_mode},
            default_session_id="desktop",
        )
        if not credit_decision.get("allowed", True):
            return self._credit_block_response(credit_decision, action_label="cowork turn")
        try:
            turn_usage = self._record_provisional_usage(
                request,
                metric="cowork_turns",
                payload=data,
                metadata={
                    "thread_id": thread_id,
                    "mode": requested_mode,
                    "routing_profile": str(data.get("routing_profile") or "balanced").strip() or "balanced",
                    "review_strictness": str(data.get("review_strictness") or "balanced").strip() or "balanced",
                    "estimated_credits": int(credit_decision.get("estimated_credits") or 0),
                    "prompt_length": len(prompt),
                },
            )
        except Exception as exc:
            self._observe_execution_guard(
                request,
                action="cowork_turn_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"thread_id": thread_id, "failure_class": "billing_reservation_failed"},
                level="error",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": "billing reservation failed"}, status=500)
        try:
            detail = await self._cowork_store().add_turn(
                thread_id,
                prompt=prompt,
                preferred_mode=str(data.get("current_mode") or data.get("mode") or "").strip(),
                project_template_id=str(data.get("project_template_id") or "").strip(),
                routing_profile=str(data.get("routing_profile") or "balanced").strip() or "balanced",
                review_strictness=str(data.get("review_strictness") or "balanced").strip() or "balanced",
                user_id=self._actor_id(request, data),
                agent=self.agent,
                billing_usage_id=str((turn_usage or {}).get("usage_id") or ""),
                billing_metric="cowork_turns",
            )
        except KeyError:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((turn_usage or {}).get("usage_id") or ""),
                failure_class="thread_missing",
                metadata={"thread_id": thread_id},
            )
            self._observe_execution_guard(
                request,
                action="cowork_turn_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason="thread not found",
                metadata={"thread_id": thread_id, "failure_class": "thread_missing"},
                level="warning",
                default_session_id="desktop",
            )
            return _json_error("thread not found", status=404)
        except ValueError as exc:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((turn_usage or {}).get("usage_id") or ""),
                failure_class="validation_error",
                metadata={"thread_id": thread_id, "reason": str(exc)},
            )
            self._observe_execution_guard(
                request,
                action="cowork_turn_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"thread_id": thread_id, "failure_class": "validation_error"},
                level="warning",
                default_session_id="desktop",
            )
            return _json_error(str(exc), status=400)
        except Exception as exc:
            self._reconcile_failed_usage(
                workspace_id,
                usage_id=str((turn_usage or {}).get("usage_id") or ""),
                failure_class="runtime_error",
                metadata={"thread_id": thread_id, "reason": str(exc)},
            )
            self._observe_execution_guard(
                request,
                action="cowork_turn_create",
                phase="dispatch_failed",
                payload=data,
                allowed=False,
                reason=str(exc),
                metadata={"thread_id": thread_id, "failure_class": "runtime_error"},
                level="error",
                default_session_id="desktop",
            )
            return web.json_response({"success": False, "error": str(exc)}, status=500)
        self._observe_execution_guard(
            request,
            action="cowork_turn_create",
            phase="dispatched",
            payload=data,
            allowed=True,
            checks=[
                ExecutionCheck(
                    name="turn_created",
                    allowed=True,
                    metadata={
                        "thread_id": str(detail.get("thread_id") or thread_id),
                        "mode": str(detail.get("current_mode") or requested_mode),
                    },
                )
            ],
            metadata={"estimated_credits": int(credit_decision.get("estimated_credits") or 0)},
            default_session_id="desktop",
        )
        push_cowork_event("cowork.thread.updated", detail)
        return _json_ok({"thread": detail, "billing_usage_id": str((turn_usage or {}).get("usage_id") or "")})

    async def handle_v1_cowork_thread_action(self, request):
        thread_id = str(request.match_info.get("thread_id") or "").strip()
        if not thread_id:
            return _json_error("thread_id required", status=400)
        try:
            data = await request.json()
        except Exception:
            data = {}
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        action = str(data.get("action") or "").strip().lower()
        if action not in {"stop", "resume"}:
            return _json_error("unsupported action", status=400)
        try:
            detail = await self._cowork_store().get_thread_detail(thread_id)
        except KeyError:
            return _json_error("thread not found", status=404)
        if str(detail.get("workspace_id") or "").strip() != workspace_id:
            return _json_error("workspace_access_denied", status=403)
        try:
            detail = await self._cowork_store().control_thread(
                thread_id,
                action=action,
                note=str(data.get("note") or "").strip(),
                agent=self.agent,
            )
        except KeyError:
            return _json_error("thread not found", status=404)
        except ValueError as exc:
            return _json_error(str(exc), status=400)
        push_cowork_event("cowork.thread.updated", detail)
        return _json_ok({"thread": detail})

    async def handle_v1_cowork_resolve_approval(self, request):
        approval_id = str(request.match_info.get("approval_id") or "").strip()
        if not approval_id:
            return _json_error("approval_id required", status=400)
        try:
            data = await request.json()
        except Exception:
            data = {}
        workspace_id = self._workspace_id(request, data)
        workspace_allowed, workspace_error = self._require_workspace_access(request, workspace_id)
        if not workspace_allowed:
            return _json_error(workspace_error, status=403)
        mission = await self._mission_store().resolve_approval(
            approval_id,
            bool(data.get("approved", False)),
            note=str(data.get("note") or "").strip(),
            agent=self.agent,
        )
        if mission is None:
            return _json_error("approval not found", status=404)
        thread_id = str((mission.metadata or {}).get("thread_id") or "").strip()
        detail = await self._cowork_store().get_thread_detail(thread_id) if thread_id else None
        if detail is not None and str(detail.get("workspace_id") or "").strip() != workspace_id:
            return _json_error("workspace_access_denied", status=403)
        if detail is not None:
            push_cowork_event("cowork.approval.resolved", detail)
        return _json_ok({"mission": mission.to_dict(), "thread": detail})

    async def handle_v1_billing_workspace(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        return _json_ok({"workspace": self._workspace_billing().get_workspace_summary(workspace_id)})

    async def handle_v1_billing_plans(self, request):
        store = self._workspace_billing()
        return _json_ok({"plans": store.list_plans(), "token_packs": store.list_token_packs()})

    async def handle_v1_billing_usage(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        try:
            limit = int(request.rel_url.query.get("limit", 100))
        except Exception:
            limit = 100
        return _json_ok({"usage": self._workspace_billing().get_usage(workspace_id, limit=limit)})

    async def handle_v1_billing_entitlements(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        return _json_ok({"entitlements": self._workspace_billing().get_entitlements(workspace_id)})

    async def handle_v1_billing_credits(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        return _json_ok({"credits": self._workspace_billing().get_credit_balance(workspace_id)})

    async def handle_v1_billing_ledger(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        try:
            limit = int(request.rel_url.query.get("limit", 100))
        except Exception:
            limit = 100
        return _json_ok({"ledger": self._workspace_billing().get_credit_ledger(workspace_id, limit=limit)})

    async def handle_v1_billing_events(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        try:
            limit = int(request.rel_url.query.get("limit", 100))
        except Exception:
            limit = 100
        return _json_ok({"events": self._workspace_billing().get_billing_events(workspace_id, limit=limit)})

    async def handle_v1_billing_profile(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        store = self._workspace_billing()
        if request.method == "GET":
            return _json_ok({"profile": store.get_billing_profile(workspace_id)})
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        allowed, error = self._require_billing_write_role(request, data)
        if not allowed:
            return _json_error(error, status=403)
        payload = {
            "full_name": str(data.get("full_name") or "").strip(),
            "email": str(data.get("email") or self._auth_context(request).get("email") or "").strip(),
            "phone": str(data.get("phone") or "").strip(),
            "identity_number": str(data.get("identity_number") or "").strip(),
            "address_line1": str(data.get("address_line1") or "").strip(),
            "city": str(data.get("city") or "").strip(),
            "zip_code": str(data.get("zip_code") or "").strip(),
            "country": str(data.get("country") or "").strip(),
        }
        return _json_ok({"profile": store.update_billing_profile(workspace_id, payload)})

    async def handle_v1_billing_checkout_detail(self, request):
        workspace_id = self._workspace_id(request)
        ws_ok, ws_err = self._require_workspace_access(request, workspace_id)
        if not ws_ok:
            return _json_error(ws_err, status=403)
        reference_id = str(request.match_info.get("reference_id") or "").strip()
        if not reference_id:
            return _json_error("reference_id required", status=400)
        payload = self._workspace_billing().get_checkout_session(workspace_id, reference_id, refresh=True)
        if payload is None:
            return _json_error("checkout not found", status=404)
        return _json_ok({"checkout": payload})

    async def handle_v1_billing_reconcile_usage(self, request):
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        allowed, error = self._require_billing_write_role(request, data)
        if not allowed:
            return _json_error(error, status=403)
        usage_id = str(data.get("usage_id") or "").strip()
        if not usage_id:
            return _json_error("usage_id required", status=400)
        if data.get("actual_credits") is None:
            return _json_error("actual_credits required", status=400)
        try:
            actual_credits = int(data.get("actual_credits") or 0)
        except Exception:
            return _json_error("actual_credits must be an integer", status=400)
        try:
            actual_cost_usd = float(data.get("actual_cost_usd") or 0.0)
            total_tokens = int(data.get("total_tokens") or 0)
        except Exception:
            return _json_error("actual_cost_usd or total_tokens invalid", status=400)
        workspace_id = self._workspace_id(request, data)
        reconciliation_metadata = {
            "actual_cost_usd": actual_cost_usd,
            "total_tokens": total_tokens,
            "provider": str(data.get("provider") or "").strip(),
            "model": str(data.get("model") or "").strip(),
            "reconciled_by": str(self._actor_id(request, data) or ""),
        }
        try:
            payload = self._workspace_billing().reconcile_usage(
                workspace_id,
                usage_id=usage_id,
                actual_credits=actual_credits,
                metadata=reconciliation_metadata,
            )
        except KeyError:
            return _json_error("usage not found", status=404)
        except RuntimeError as exc:
            return _json_error(str(exc), status=409)
        return _json_ok({"reconciliation": payload})

    async def handle_v1_billing_checkout_init(self, request):
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        allowed, error = self._require_billing_write_role(request, data)
        if not allowed:
            return _json_error(error, status=403)
        workspace_id = self._workspace_id(request, data)
        try:
            payload = self._workspace_billing().create_checkout_session(
                workspace_id=workspace_id,
                plan_id=str(data.get("plan_id") or "pro").strip() or "pro",
                success_url=str(data.get("success_url") or "https://tauri.localhost/billing/success").strip(),
                cancel_url=str(data.get("cancel_url") or "https://tauri.localhost/billing/cancel").strip(),
                customer_email=str(self._auth_context(request).get("email") or data.get("email") or "").strip(),
            )
        except RuntimeError as exc:
            error = str(exc)
            status = 409 if error.startswith("billing_profile_incomplete:") else 503
            return _json_error(error, status=status)
        return _json_ok({"checkout": payload})

    async def handle_v1_billing_token_pack_purchase(self, request):
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        allowed, error = self._require_billing_write_role(request, data)
        if not allowed:
            return _json_error(error, status=403)
        workspace_id = self._workspace_id(request, data)
        try:
            payload = self._workspace_billing().purchase_token_pack(
                workspace_id=workspace_id,
                pack_id=str(data.get("pack_id") or "").strip(),
                success_url=str(data.get("success_url") or "https://tauri.localhost/billing/success").strip(),
                cancel_url=str(data.get("cancel_url") or "https://tauri.localhost/billing/cancel").strip(),
                customer_email=str(self._auth_context(request).get("email") or data.get("email") or "").strip(),
            )
        except KeyError as exc:
            return _json_error(str(exc), status=404)
        except RuntimeError as exc:
            error = str(exc)
            status = 409 if error.startswith("billing_profile_incomplete:") else 503
            return _json_error(error, status=status)
        return _json_ok({"purchase": payload})

    async def handle_v1_billing_webhook_iyzico(self, request):
        payload = await request.read()
        store = self._workspace_billing()
        try:
            result = store.handle_webhook(payload, dict(request.headers), provider="iyzico")
        except RuntimeError as exc:
            return _json_error(str(exc), status=503)
        return _json_ok({"event": result})

    async def handle_v1_billing_checkout(self, request):
        return await self.handle_v1_billing_checkout_init(request)

    async def handle_v1_billing_checkout_launch(self, request):
        reference_id = str(request.match_info.get("reference_id") or "").strip()
        if not reference_id:
            return web.Response(text="reference_id required", status=400)
        payload = self._workspace_billing().get_checkout_launch_payload(reference_id)
        if payload is None:
            return web.Response(text="Checkout not found", status=404)
        checkout_form_content = str(payload.get("checkout_form_content") or "").strip()
        payment_page_url = str(payload.get("payment_page_url") or "").strip()
        if checkout_form_content:
            return web.Response(text=checkout_form_content, content_type="text/html")
        if payment_page_url:
            raise web.HTTPFound(payment_page_url)
        return web.Response(text="Checkout launch unavailable", status=404)

    async def handle_v1_billing_callback_iyzico(self, request):
        callback_payload: dict[str, Any] = {}
        if request.method == "GET":
            callback_payload = dict(request.rel_url.query)
        else:
            try:
                callback_payload = await request.json()
            except Exception:
                try:
                    callback_payload = dict(await request.post())
                except Exception:
                    callback_payload = dict(request.rel_url.query)
        token = str(callback_payload.get("token") or "").strip()
        reference_id = str(callback_payload.get("reference_id") or request.rel_url.query.get("reference_id") or "").strip()
        mode = str(callback_payload.get("mode") or request.rel_url.query.get("mode") or "").strip()
        try:
            result = self._workspace_billing().complete_checkout_callback(
                token=token,
                reference_id=reference_id,
                mode=mode,
            )
        except RuntimeError as exc:
            if "application/json" in str(request.headers.get("Accept") or "").lower():
                return _json_error(str(exc), status=503)
            return web.Response(text=f"Billing callback failed: {exc}", status=503, content_type="text/html")
        if "application/json" in str(request.headers.get("Accept") or "").lower() or str(request.rel_url.query.get("format") or "") == "json":
            return _json_ok({"checkout": result.get("checkout"), "event": result})
        checkout = result.get("checkout") if isinstance(result.get("checkout"), dict) else {}
        status = str((checkout or {}).get("status") or result.get("status") or "pending").strip()
        body = (
            "<!doctype html><html><head><meta charset='utf-8'><title>Elyan Billing</title>"
            "<meta name='viewport' content='width=device-width, initial-scale=1'></head>"
            "<body style='font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;padding:40px;background:#f7f7f3;color:#101010;'>"
            f"<h1 style='font-size:24px;margin:0 0 12px;'>Payment {status}</h1>"
            "<p style='font-size:15px;line-height:1.6;max-width:560px;'>"
            "You can return to the Elyan desktop app. The billing state will refresh automatically."
            "</p></body></html>"
        )
        return web.Response(text=body, content_type="text/html")

    async def handle_v1_billing_portal(self, request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        workspace_id = self._workspace_id(request, data)
        try:
            payload = self._workspace_billing().create_portal_session(
                workspace_id=workspace_id,
                return_url=str(data.get("return_url") or "https://tauri.localhost/settings").strip(),
            )
        except RuntimeError as exc:
            return _json_error(str(exc), status=503)
        return _json_ok({"portal": payload})

    async def handle_v1_billing_webhook(self, request):
        return _json_error("stripe webhooks are deprecated; use /api/v1/billing/webhooks/iyzico", status=410)

    async def handle_v1_connectors(self, request):
        workspace_id = self._workspace_id(request)
        permissions = _check_macos_permissions()
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []
        channel_map = {
            _normalize_channel_type(str(item.get("type") or "")): dict(item)
            for item in channels
            if isinstance(item, dict)
        }
        adapter_status = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
        accounts_response = await self.handle_v1_connector_accounts(request)
        accounts_payload = json.loads(accounts_response.text)
        traces_response = await self.handle_v1_connector_traces(request)
        traces_payload = json.loads(traces_response.text)
        accounts = list(accounts_payload.get("accounts") or [])
        traces = list(traces_payload.get("traces") or [])
        rows = []
        for definition in self._connector_catalog():
            connector_name = str(definition.get("connector") or "").strip().lower()
            provider = str(definition.get("provider") or "")
            provider_accounts = [item for item in accounts if str(item.get("provider") or "").strip().lower() == provider]
            provider_traces = [item for item in traces if str(item.get("provider") or "").strip().lower() == provider]
            state = "connected" if any(str(item.get("status") or "").strip().lower() == "ready" for item in provider_accounts) else ("pending" if provider_accounts else "offline")
            blocking_issue = ""
            execution_mode = "cloud" if str(definition.get("integration_type") or "").strip().lower() == "api" else "local"
            if connector_name.startswith("apple_"):
                if not bool(permissions.get("osascript_available")):
                    state = "offline"
                    blocking_issue = "permission_denied"
                elif provider_accounts:
                    state = "connected" if any(str(item.get("status") or "").strip().lower() == "ready" for item in provider_accounts) else "pending"
                else:
                    state = "pending"
            elif connector_name == "imessage":
                imessage_cfg = channel_map.get("imessage", {})
                bluebubbles_ready = bool(imessage_cfg.get("server_url")) and bool(imessage_cfg.get("password"))
                imessage_status = str(adapter_status.get("imessage") or "").strip().lower()
                execution_mode = "bluebubbles"
                if imessage_status in {"connected", "online", "ok", "active", "healthy"}:
                    state = "connected"
                elif bluebubbles_ready:
                    state = "pending"
                    blocking_issue = "bridge_unreachable"
                else:
                    state = "offline"
                    blocking_issue = "auth_required"
            rows.append(
                {
                    **definition,
                    "workspace_id": workspace_id,
                    "account_count": len(provider_accounts),
                    "trace_count": len(provider_traces),
                    "status": state,
                    "blocking_issue": blocking_issue,
                    "execution_mode": execution_mode,
                    "latest_trace": provider_traces[0] if provider_traces else None,
                }
            )
        return _json_ok({"connectors": rows})

    async def handle_v1_connector_accounts(self, request):
        from integrations import oauth_broker

        workspace_id = self._workspace_id(request)
        provider = str(request.rel_url.query.get("provider", "") or "").strip().lower()
        accounts = [account.public_dump() for account in oauth_broker.list_accounts(provider or None)]
        filtered = self._filter_workspace_accounts(accounts, workspace_id)
        rows = []
        for item in filtered:
            account_id = f"{str(item.get('provider') or '').strip().lower()}::{str(item.get('account_alias') or 'default').strip()}"
            rows.append({**item, "account_id": account_id, "workspace_id": workspace_id})
        return _json_ok({"accounts": rows, "workspace_id": workspace_id})

    async def handle_v1_connector_connect(self, request):
        connector_name = str(request.match_info.get("connector") or "").strip().lower()
        connector = self._connector_lookup(connector_name)
        if connector is None:
            return _json_error("connector not found", status=404)
        try:
            data = await request.json()
        except Exception:
            data = {}
        workspace_id = self._workspace_id(request, data)
        current_accounts_response = await self.handle_v1_connector_accounts(request)
        current_accounts_payload = json.loads(current_accounts_response.text)
        limit_state = self._workspace_billing().enforce_limit(
            workspace_id,
            metric="max_connectors",
            current_value=len(list(current_accounts_payload.get("accounts") or [])),
        )
        if not limit_state.get("allowed", True):
            return _json_error(str(limit_state.get("reason") or "connector limit reached"), status=402, payload={"limit": limit_state})
        merged = {
            "provider": connector.get("provider"),
            "app_name": connector.get("label"),
            "scopes": list(connector.get("scopes") or []),
            "mode": str(data.get("mode") or "auto"),
            "account_alias": str(data.get("account_alias") or "default"),
            "display_name": str(data.get("display_name") or connector.get("label") or ""),
            "email": str(data.get("email") or ""),
            "authorization_code": str(data.get("authorization_code") or ""),
            "workspace_id": workspace_id,
        }
        from integrations import connector_factory, integration_registry, oauth_broker
        from integrations.base import AuthStrategy, ConnectorState, FallbackPolicy, OAuthAccount
        from core.integration_trace import get_integration_trace_store

        local_connector_names = {"apple_mail", "apple_calendar", "apple_reminders", "apple_notes", "apple_contacts"}
        trace_store = get_integration_trace_store()
        if connector_name in local_connector_names:
            permissions = _check_macos_permissions()
            ready = bool(permissions.get("osascript_available"))
            account = OAuthAccount(
                provider=str(connector.get("provider") or connector_name),
                account_alias=str(merged.get("account_alias") or "default"),
                display_name=str(merged.get("display_name") or connector.get("label") or connector_name),
                auth_strategy=AuthStrategy.NONE,
                fallback_mode=FallbackPolicy.NATIVE,
                granted_scopes=list(connector.get("scopes") or []),
                status=ConnectorState.READY if ready else ConnectorState.NEEDS_INPUT,
                auth_url="x-apple.systempreferences:com.apple.preference.security?Privacy_Automation" if not ready else "",
                metadata={
                    "workspace_id": workspace_id,
                    "connector": connector_name,
                    "local_first": True,
                    "blocking_issue": "" if ready else "permission_denied",
                },
            )
            account = oauth_broker._save_account(account)
            trace_store.record_trace(
                operation="workspace_connector_connect",
                provider=account.provider,
                connector_name=connector_name,
                integration_type="desktop",
                status=str(account.status),
                success=bool(account.is_ready),
                auth_state=str(account.status),
                auth_strategy=str(account.auth_strategy),
                account_alias=str(account.account_alias or "default"),
                metadata={"workspace_id": workspace_id, "connector": connector_name, "local_first": True},
            )
            self._workspace_billing().record_usage(workspace_id, "connectors", 1, metadata={"connector": connector_name})
            return _json_ok(
                {
                    "connector": connector,
                    "account": {**account.public_dump(), "workspace_id": workspace_id, "account_id": f"{account.provider}::{account.account_alias}"},
                    "connect_result": {
                        "success": bool(account.is_ready),
                        "status": "ready" if account.is_ready else "needs_attention",
                        "message": "Apple connector is ready." if account.is_ready else "macOS Automation permission is required.",
                    },
                    "launch_url": str(account.auth_url or ""),
                }
            )

        if connector_name == "imessage":
            channels = elyan_config.get("channels", [])
            if not isinstance(channels, list):
                channels = []
            imessage_cfg = next(
                (dict(item) for item in channels if isinstance(item, dict) and _normalize_channel_type(str(item.get("type") or "")) == "imessage"),
                {},
            )
            ready = bool(imessage_cfg.get("server_url")) and bool(imessage_cfg.get("password"))
            account = OAuthAccount(
                provider="imessage",
                account_alias=str(merged.get("account_alias") or "default"),
                display_name=str(merged.get("display_name") or connector.get("label") or "iMessage"),
                auth_strategy=AuthStrategy.NONE,
                fallback_mode=FallbackPolicy.NATIVE,
                granted_scopes=list(connector.get("scopes") or []),
                status=ConnectorState.READY if ready else ConnectorState.NEEDS_INPUT,
                auth_url="https://bluebubbles.app/",
                metadata={
                    "workspace_id": workspace_id,
                    "connector": connector_name,
                    "execution_mode": "bluebubbles",
                    "blocking_issue": "" if ready else "auth_required",
                },
            )
            account = oauth_broker._save_account(account)
            trace_store.record_trace(
                operation="workspace_connector_connect",
                provider="imessage",
                connector_name=connector_name,
                integration_type="desktop",
                status=str(account.status),
                success=bool(account.is_ready),
                auth_state=str(account.status),
                auth_strategy=str(account.auth_strategy),
                account_alias=str(account.account_alias or "default"),
                metadata={"workspace_id": workspace_id, "connector": connector_name, "execution_mode": "bluebubbles"},
            )
            self._workspace_billing().record_usage(workspace_id, "connectors", 1, metadata={"connector": connector_name})
            return _json_ok(
                {
                    "connector": connector,
                    "account": {**account.public_dump(), "workspace_id": workspace_id, "account_id": f"{account.provider}::{account.account_alias}"},
                    "connect_result": {
                        "success": bool(account.is_ready),
                        "status": "ready" if account.is_ready else "needs_attention",
                        "message": "BlueBubbles is configured." if account.is_ready else "Configure BlueBubbles in the iMessage channel card.",
                    },
                    "launch_url": "https://bluebubbles.app/",
                }
            )

        plan = integration_registry.resolve_connection_plan(
            app_name=str(merged.get("app_name") or ""),
            provider=str(merged.get("provider") or ""),
            scopes=list(merged.get("scopes") or []),
            mode=str(merged.get("mode") or "auto"),
            account_alias=str(merged.get("account_alias") or "default"),
            extra={"display_name": str(merged.get("display_name") or ""), "email": str(merged.get("email") or "")},
        )
        account = oauth_broker.authorize(
            str(plan.get("provider") or merged.get("provider") or ""),
            list(plan.get("required_scopes") or merged.get("scopes") or []),
            mode=str(merged.get("mode") or "auto"),
            account_alias=str(merged.get("account_alias") or "default"),
            authorization_code=str(merged.get("authorization_code") or ""),
            redirect_uri=str(data.get("redirect_uri") or "http://localhost:8765/callback"),
            extra={
                "display_name": str(merged.get("display_name") or ""),
                "email": str(merged.get("email") or ""),
                "workspace_id": workspace_id,
                "connector": connector_name,
            },
        )
        connector_result = None
        if account.is_ready:
            try:
                capability = plan.get("capability")
                connector_instance = connector_factory.get(
                    getattr(plan.get("integration_type"), "value", plan.get("integration_type") or "unknown"),
                    auth_state={
                        "capability": capability.model_dump() if hasattr(capability, "model_dump") else dict(capability or {}),
                        "auth_account": account.model_dump() if hasattr(account, "model_dump") else account.public_dump(),
                        "provider": str(plan.get("provider") or merged.get("provider") or ""),
                        "connector_name": str(plan.get("connector_name") or connector_name),
                    },
                )
                connector_result = await connector_instance.connect(str(merged.get("app_name") or connector_name), mode=str(merged.get("mode") or "auto"))
            except Exception as exc:
                connector_result = {"success": False, "status": "failed", "error": str(exc)}
        trace_store.record_trace(
            operation="workspace_connector_connect",
            provider=str(plan.get("provider") or merged.get("provider") or ""),
            connector_name=str(plan.get("connector_name") or connector_name),
            integration_type=str((plan.get("integration_type").value if hasattr(plan.get("integration_type"), "value") else plan.get("integration_type")) or ""),
            status=str((connector_result.get("status") if isinstance(connector_result, dict) else getattr(connector_result, "status", "")) or account.status),
            success=bool(account.is_ready),
            auth_state=str(account.status),
            auth_strategy=str(plan.get("auth_strategy") or ""),
            account_alias=str(account.account_alias or "default"),
            metadata={
                "workspace_id": workspace_id,
                "connector": connector_name,
                "capabilities": list(connector.get("capabilities") or []),
            },
        )
        self._workspace_billing().record_usage(workspace_id, "connectors", 1, metadata={"connector": connector_name})
        result_payload = connector_result.model_dump() if hasattr(connector_result, "model_dump") else (dict(connector_result) if isinstance(connector_result, dict) else {})
        return _json_ok(
            {
                "connector": connector,
                "account": {**account.public_dump(), "workspace_id": workspace_id, "account_id": f"{account.provider}::{account.account_alias}"},
                "connect_result": result_payload,
                "launch_url": str(account.auth_url or ""),
            }
        )

    async def handle_v1_connector_refresh(self, request):
        from integrations import oauth_broker

        account_id = str(request.match_info.get("account_id") or "").strip()
        provider, _, account_alias = account_id.partition("::")
        if not provider:
            return _json_error("account_id required", status=400)
        account = next(
            (
                item for item in oauth_broker.list_accounts(provider)
                if str(item.account_alias or "default").strip() == (account_alias or "default")
            ),
            None,
        )
        if account is None:
            return _json_error("account not found", status=404)
        refreshed = oauth_broker.authorize(
            provider,
            list(account.granted_scopes or []),
            mode="auto",
            account_alias=account_alias or "default",
            extra=dict(account.metadata or {}),
        )
        return _json_ok({"account": {**refreshed.public_dump(), "account_id": account_id}})

    async def handle_v1_connector_quick_action(self, request):
        connector_name = str(request.match_info.get("connector") or "").strip().lower()
        connector = self._connector_lookup(connector_name)
        if connector is None:
            return _json_error("connector not found", status=404)
        try:
            data = await request.json()
        except Exception:
            data = {}

        action = str(data.get("action") or "").strip().lower()
        query = str(data.get("query") or "").strip()
        workspace_id = self._workspace_id(request, data)

        result: dict[str, Any]
        blocking_issue = ""
        try:
            if connector_name == "apple_notes":
                if query:
                    from tools.note_tools.note_search import search_notes

                    raw = await search_notes(query, limit=8)
                    result = {
                        "items": list(raw.get("results") or [])[:8],
                        "count": int(raw.get("count") or 0),
                        "message": str(raw.get("message") or ""),
                    }
                else:
                    from tools.note_tools.note_manager import list_notes

                    raw = await list_notes(limit=8)
                    result = {
                        "items": list(raw.get("notes") or [])[:8],
                        "count": int(raw.get("count") or 0),
                        "message": "",
                    }
            elif connector_name == "apple_calendar":
                from tools.macos_tools.calendar_reminders import get_today_events

                raw = await get_today_events()
                result = {
                    "items": list(raw.get("events") or [])[:8],
                    "count": int(raw.get("count") or 0),
                    "date": str(raw.get("date") or ""),
                }
            elif connector_name == "apple_reminders":
                from tools.macos_tools.calendar_reminders import get_reminders

                raw = await get_reminders()
                result = {
                    "items": list(raw.get("reminders") or [])[:8],
                    "count": int(raw.get("count") or 0),
                }
            elif connector_name == "whatsapp":
                cfg = next(
                    (
                        dict(item) for item in (elyan_config.get("channels", []) or [])
                        if isinstance(item, dict) and _normalize_channel_type(str(item.get("type") or "")) == "whatsapp"
                    ),
                    {},
                )
                status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
                result = {
                    "mode": str(cfg.get("mode") or "bridge"),
                    "status": str(status_map.get("whatsapp") or "disconnected"),
                    "bridge_url": str(cfg.get("bridge_url") or ""),
                    "webhook_path": str(cfg.get("webhook_path") or ""),
                }
            elif connector_name == "imessage":
                cfg = next(
                    (
                        dict(item) for item in (elyan_config.get("channels", []) or [])
                        if isinstance(item, dict) and _normalize_channel_type(str(item.get("type") or "")) == "imessage"
                    ),
                    {},
                )
                status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
                ready = bool(cfg.get("server_url")) and bool(cfg.get("password"))
                blocking_issue = "" if ready else "auth_required"
                result = {
                    "server_url": str(cfg.get("server_url") or ""),
                    "status": str(status_map.get("imessage") or "disconnected"),
                    "ready": ready,
                }
            else:
                return _json_error("quick action unsupported", status=400)
        except Exception as exc:
            message = str(exc)
            lower = message.lower()
            if "not allowed" in lower or "erişim" in lower or "permission" in lower or "access" in lower:
                blocking_issue = "permission_denied"
            else:
                blocking_issue = "read_failed"
            return _json_error(
                message or "quick action failed",
                status=500,
                payload={"blocking_issue": blocking_issue, "connector": connector_name},
            )

        from core.integration_trace import get_integration_trace_store

        get_integration_trace_store().record_trace(
            operation=f"quick_action:{action or 'default'}",
            provider=str(connector.get("provider") or connector_name),
            connector_name=connector_name,
            integration_type=str(connector.get("integration_type") or ""),
            status="success",
            success=True,
            auth_state="ready",
            auth_strategy="none",
            account_alias="default",
            metadata={"workspace_id": workspace_id, "query": query, "blocking_issue": blocking_issue},
        )
        return _json_ok(
            {
                "connector": connector_name,
                "action": action or "default",
                "result": result,
                "blocking_issue": blocking_issue,
            }
        )

    async def handle_v1_operator_preview(self, request):
        from core.goal_graph import get_goal_graph_planner

        try:
            data = await request.json()
        except Exception:
            data = {}
        text = str(data.get("text") or data.get("request") or "").strip()
        if not text:
            return _json_error("text required", status=400)

        workspace_id = self._workspace_id(request, data)
        user_id = self._actor_id(request, data)
        session_id = str(data.get("session_id") or request.rel_url.query.get("session_id", "") or "desktop-preview").strip() or "desktop-preview"

        plan = await get_operator_control_plane().plan_request(
            request_id=str(data.get("request_id") or f"preview-{int(time.time() * 1000)}"),
            user_id=user_id,
            request=text,
            channel=str(data.get("channel") or "desktop"),
            device_id=str(data.get("device_id") or "desktop"),
            context={
                "session_id": session_id,
                "workspace_id": workspace_id,
                "metadata": {
                    "workspace_id": workspace_id,
                    "preview": True,
                },
            },
        )

        capability = dict(plan.get("capability") or {})
        integration = dict(plan.get("integration") or {})
        task_plan = dict(plan.get("task_plan") or {})
        model_selection = dict(plan.get("model_selection") or {})
        autonomy = dict(plan.get("autonomy") or {})
        operator_trace = dict(plan.get("operator_trace") or {})
        steps = list(task_plan.get("steps") or [])
        goal_graph = get_goal_graph_planner().build(text)
        return _json_ok(
            {
                "preview": {
                    "request_text": text,
                    "request_class": str(plan.get("request_class") or ""),
                    "domain": str(capability.get("domain") or operator_trace.get("route_domain") or ""),
                    "objective": str(capability.get("objective") or text),
                    "preview": str(capability.get("preview") or operator_trace.get("route_preview") or ""),
                    "primary_action": str(capability.get("primary_action") or ""),
                    "orchestration_mode": str(capability.get("orchestration_mode") or "single_agent"),
                    "model_selection": {
                        "provider": str(model_selection.get("provider") or ""),
                        "model": str(model_selection.get("model") or ""),
                        "role": str(model_selection.get("role") or ""),
                        "fallback": bool(model_selection.get("fallback")),
                    },
                    "collaboration": _sanitize_collaboration_payload(plan.get("collaboration") or {}),
                    "integration": {
                        "provider": str(integration.get("provider") or ""),
                        "connector_name": str(integration.get("connector_name") or ""),
                        "integration_type": str(integration.get("integration_type") or ""),
                        "auth_strategy": str(integration.get("auth_strategy") or ""),
                        "fallback_policy": str(integration.get("fallback_policy") or ""),
                    },
                    "autonomy": {
                        "mode": str(autonomy.get("mode") or ""),
                        "should_ask": bool(autonomy.get("should_ask")),
                        "should_resume": bool(autonomy.get("should_resume")),
                    },
                    "task_plan": {
                        "name": str(task_plan.get("name") or ""),
                        "goal": str(task_plan.get("goal") or ""),
                        "constraints": list(task_plan.get("constraints") or []),
                        "approvals": list(task_plan.get("approvals") or []),
                        "evidence": list(task_plan.get("evidence") or []),
                        "steps": [
                            {
                                "name": str(item.get("name") or item.get("tool") or "step"),
                                "kind": str(item.get("kind") or "task"),
                                "tool": str(item.get("tool") or ""),
                            }
                            for item in steps[:8]
                            if isinstance(item, dict)
                        ],
                    },
                    "fast_path": bool(plan.get("fast_path")),
                    "real_time_required": bool(((plan.get("real_time") if isinstance(plan.get("real_time"), dict) else {}) or {}).get("needs_real_time")),
                    "goal_graph": goal_graph,
                }
            }
        )

    async def handle_v1_system_platforms(self, request):
        from core.platforms_overview import build_platforms_payload

        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []
        status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
        live_channels = []
        for item in channels:
            if not isinstance(item, dict):
                continue
            channel_type = str(item.get("type") or "").strip().lower()
            if not channel_type:
                continue
            live_channels.append(
                {
                    "type": channel_type,
                    "status": str(status_map.get(channel_type) or ""),
                    "detail": str(item.get("mode") or item.get("id") or ""),
                }
            )

        payload = build_platforms_payload(
            config={"channels": channels},
            gateway={"running": True, "pid": None},
            live_channels=live_channels,
        )
        return _json_ok(payload)

    async def handle_v1_connector_revoke(self, request):
        from integrations import oauth_broker

        account_id = str(request.match_info.get("account_id") or "").strip()
        provider, _, account_alias = account_id.partition("::")
        if not provider:
            return _json_error("account_id required", status=400)
        ok = oauth_broker.delete_account(provider, account_alias or "default")
        if not ok:
            return _json_error("account revoke failed", status=404, payload={"account_id": account_id})
        return _json_ok({"account_id": account_id})

    async def handle_v1_connector_traces(self, request):
        from core.integration_trace import get_integration_trace_store

        workspace_id = self._workspace_id(request)
        try:
            limit = int(request.rel_url.query.get("limit", 100))
        except Exception:
            limit = 100
        traces = get_integration_trace_store().list_traces(limit=limit)
        filtered = self._filter_workspace_traces(traces, workspace_id)
        return _json_ok({"traces": filtered[:limit], "workspace_id": workspace_id})

    async def handle_v1_connector_health(self, request):
        connectors_response = await self.handle_v1_connectors(request)
        payload = json.loads(connectors_response.text)
        rows = []
        for item in list(payload.get("connectors") or []):
            rows.append(
                {
                    "connector": str(item.get("connector") or ""),
                    "status": str(item.get("status") or "offline"),
                    "account_count": int(item.get("account_count") or 0),
                    "trace_count": int(item.get("trace_count") or 0),
                    "provider": str(item.get("provider") or ""),
                    "blocking_issue": str(item.get("blocking_issue") or ""),
                    "execution_mode": str(item.get("execution_mode") or ""),
                }
            )
        return _json_ok({"health": rows})

    async def handle_inspector_page(self, request):
        base = Path(__file__).resolve().parent.parent.parent
        p = base / 'ui' / 'web' / 'run_inspector.html'
        if not p.exists():
            return web.Response(text="Inspector UI not found", status=404)
        return web.FileResponse(p)

    # ── Page handlers ─────────────────────────────────────────────────────────
    async def handle_dashboard_page(self, request):
        return web.Response(
            text=(
                "<html><body style='font-family:-apple-system,Segoe UI,sans-serif;padding:24px;'>"
                "<h2>Elyan Desktop-First Runtime</h2>"
                "<p>Web dashboard kaldırıldı.</p>"
                "<p>Desktop uygulamayı açmak için terminalde <code>elyan desktop</code> çalıştırın.</p>"
                "</body></html>"
            ),
            content_type="text/html",
            status=410,
        )

    async def handle_trace_page(self, request):
        task_id = str(request.match_info.get("task_id", "") or "").strip()
        if not task_id:
            return web.Response(text="task_id required", status=400)
        if not _is_loopback_request(request):
            return web.Response(text="trace page is restricted to localhost", status=403)
        bundle = build_trace_bundle(task_id, runtime=self._mission_store())
        response = web.Response(
            text=render_trace_page(task_id, bundle=bundle),
            content_type="text/html",
        )
        if _is_loopback_request(request):
            response.set_cookie(
                "elyan_admin_session",
                _ensure_admin_access_token(),
                httponly=True,
                samesite="Strict",
                secure=False,
                path="/",
            )
        return response

    async def handle_ops_console_page(self, request):
        allowed, error = self._require_admin_access(request, allow_cookie=True)
        if not allowed:
            return web.Response(text=error, status=403)
        base = Path(__file__).resolve().parent.parent.parent
        p = base / 'ui' / 'web' / 'ops_console.html'
        if not p.exists():
            return web.Response(text="Ops console file not found", status=404)
        response = web.FileResponse(p)
        response.set_cookie(
            "elyan_admin_session",
            _ensure_admin_access_token(),
            httponly=True,
            samesite="Strict",
            secure=False,
            path="/",
        )
        return response

    async def handle_canvas_page(self, request):
        base = Path(__file__).resolve().parent.parent.parent
        p = base / 'ui' / 'web' / 'canvas' / 'index.html'
        if not p.exists():
            return web.Response(text="Canvas file not found", status=404)
        return web.FileResponse(p)

    async def handle_web_asset(self, request):
        _ = request
        return web.json_response(
            {
                "ok": False,
                "error": "web_dashboard_removed",
                "message": "Web dashboard assets removed. Use `elyan desktop`.",
            },
            status=410,
        )

    async def handle_trace_api(self, request):
        task_id = str(request.match_info.get("task_id", "") or "").strip()
        if not task_id:
            return web.json_response({"ok": False, "error": "task_id required"}, status=400)
        bundle = build_trace_bundle(task_id, runtime=self._mission_store())
        return web.json_response({"ok": True, "task_id": task_id, "trace": bundle})

    async def handle_brand_asset(self, request):
        filename = str(request.match_info.get("filename", "")).strip()
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            return web.Response(text="Invalid asset path", status=400)
        base = (Path(__file__).resolve().parent.parent.parent / "assets").resolve()
        asset_path = (base / filename).resolve()
        if asset_path.parent != base or not asset_path.exists() or not asset_path.is_file():
            return web.Response(text="Brand asset not found", status=404)
        resp = web.FileResponse(asset_path)
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
        return resp

    # ── Config ────────────────────────────────────────────────────────────────
    async def handle_get_config(self, request):
        return web.json_response(elyan_config.config.model_dump())

    async def handle_update_config(self, request):
        try:
            data = await request.json()
            for k, v in data.items():
                elyan_config.set(k, v)
            return web.json_response({"status": "updated"})
        except Exception as e:
            return web.json_response({"error": str(e)}, status=400)

    async def handle_agent_profile_get(self, request):
        try:
            user_profile = get_user_profile_store().profile_summary("local")
        except Exception:
            user_profile = {}
        profile = {
            "name": str(elyan_config.get("agent.name", "Elyan") or "Elyan"),
            "personality": str(elyan_config.get("agent.personality", "professional") or "professional"),
            "language": str(elyan_config.get("agent.language", "tr") or "tr"),
            "system_prompt": str(
                elyan_config.get("agent.system_prompt", "")
                or elyan_config.get("agent.systemPrompt", "")
                or ""
            ),
            "autonomous": bool(elyan_config.get("agent.autonomous", True)),
            "memory": {
                "max_user_storage_gb": float(elyan_config.get("memory.maxUserStorageGB", 10) or 10),
                "local_only": bool(elyan_config.get("memory.localOnly", True)),
            },
            "capability": {
                "enabled": bool(elyan_config.get("agent.capability_router.enabled", True)),
                "override_confidence": float(
                    elyan_config.get("agent.capability_router.min_confidence_override", 0.5) or 0.5
                ),
                "api_tools_enabled": bool(elyan_config.get("agent.api_tools.enabled", True)),
            },
            "planning": {
                "use_llm": bool(elyan_config.get("agent.planning.use_llm", True)),
                "max_subtasks": int(elyan_config.get("agent.planning.max_subtasks", 10) or 10),
            },
            "nlu": {
                "model_a": {
                    "enabled": bool(elyan_config.get("agent.nlu.model_a.enabled", True)),
                    "model_path": str(
                        elyan_config.get(
                            "agent.nlu.model_a.model_path",
                            "~/.elyan/models/nlu/baseline_intent_model.json",
                        )
                        or "~/.elyan/models/nlu/baseline_intent_model.json"
                    ),
                    "min_confidence": float(elyan_config.get("agent.nlu.model_a.min_confidence", 0.78) or 0.78),
                    "allowed_actions": list(
                        elyan_config.get(
                            "agent.nlu.model_a.allowed_actions",
                            [
                                "open_app",
                                "close_app",
                                "open_url",
                                "web_search",
                                "create_folder",
                                "list_files",
                                "read_file",
                                "write_file",
                                "run_safe_command",
                                "http_request",
                                "api_health_get_save",
                                "set_wallpaper",
                                "analyze_screen",
                                "take_screenshot",
                            ],
                        )
                        or []
                    ),
                }
            },
            "flags": {
                "agentic_v2": bool(elyan_config.get("agent.flags.agentic_v2", False)),
                "dag_exec": bool(elyan_config.get("agent.flags.dag_exec", False)),
                "strict_taskspec": bool(elyan_config.get("agent.flags.strict_taskspec", False)),
                "upgrade_intent_hardening": bool(elyan_config.get("agent.flags.upgrade_intent_hardening", False)),
                "upgrade_intent_json_envelope": bool(elyan_config.get("agent.flags.upgrade_intent_json_envelope", False)),
                "upgrade_attachment_indexer": bool(elyan_config.get("agent.flags.upgrade_attachment_indexer", False)),
                "upgrade_planning_split_cache": bool(elyan_config.get("agent.flags.upgrade_planning_split_cache", False)),
                "upgrade_orchestration_policy": bool(elyan_config.get("agent.flags.upgrade_orchestration_policy", False)),
                "upgrade_typed_tool_io": bool(elyan_config.get("agent.flags.upgrade_typed_tool_io", False)),
                "typed_tools_strict": bool(elyan_config.get("agent.flags.typed_tools_strict", False)),
                "upgrade_fallback_ladder": bool(elyan_config.get("agent.flags.upgrade_fallback_ladder", False)),
                "upgrade_verify_mandatory_gates": bool(elyan_config.get("agent.flags.upgrade_verify_mandatory_gates", False)),
                "upgrade_performance_routing": bool(elyan_config.get("agent.flags.upgrade_performance_routing", False)),
                "upgrade_telemetry_autotune": bool(elyan_config.get("agent.flags.upgrade_telemetry_autotune", False)),
                "upgrade_workspace_isolation": bool(elyan_config.get("agent.flags.upgrade_workspace_isolation", False)),
            },
            "orchestration": {
                "multi_agent_enabled": bool(elyan_config.get("agent.multi_agent.enabled", True)),
                "complexity_threshold": float(
                    elyan_config.get("agent.multi_agent.complexity_threshold", 0.9) or 0.9
                ),
                "capability_confidence_threshold": float(
                    elyan_config.get("agent.multi_agent.capability_confidence_threshold", 0.7) or 0.7
                ),
                "max_parallel": int(
                    elyan_config.get(
                        "agent.orchestration.max_parallel",
                        elyan_config.get("agent.team_mode.max_parallel", 4),
                    )
                    or 4
                ),
                "team_mode_enabled": bool(elyan_config.get("agent.team_mode.enabled", True)),
                "team_threshold": float(elyan_config.get("agent.team_mode.threshold", 0.95) or 0.95),
                "team_max_parallel": int(elyan_config.get("agent.team_mode.max_parallel", 4) or 4),
                "team_timeout_s": int(elyan_config.get("agent.team_mode.timeout_s", 900) or 900),
                "team_max_retries_per_task": int(elyan_config.get("agent.team_mode.max_retries_per_task", 1) or 1),
            },
            "skills": {
                "enabled": list(elyan_config.get("skills.enabled", []) or []),
                "workflows_enabled": list(elyan_config.get("skills.workflows.enabled", []) or []),
            },
            "runtime_policy": {
                "preset": str(elyan_config.get("agent.runtime_policy.preset", "balanced") or "balanced"),
                "available_presets": ["strict", "balanced", "full-autonomy"],
                "model_local_first": bool(elyan_config.get("agent.model.local_first", True)),
                "dashboard_strategy": str(elyan_config.get("ui.dashboard.strategy", "balanced") or "balanced"),
                "response_mode": str(elyan_config.get("agent.response_style.mode", "friendly") or "friendly"),
                "response_friendly": bool(elyan_config.get("agent.response_style.friendly", True)),
                "share_manifest_default": bool(elyan_config.get("agent.response_style.share_manifest_default", False)),
                "share_attachments_default": bool(elyan_config.get("agent.response_style.share_attachments_default", False)),
                "kvkk_strict_mode": bool(elyan_config.get("security.kvkk.strict", True)),
                "redact_cloud_prompts": bool(elyan_config.get("security.kvkk.redactCloudPrompts", True)),
                "allow_cloud_fallback": bool(elyan_config.get("security.kvkk.allowCloudFallback", True)),
                "default_user_role": str(elyan_config.get("security.defaultUserRole", "operator") or "operator"),
                "enforce_rbac": bool(elyan_config.get("security.enforceRBAC", True)),
                "path_guard_enabled": bool(elyan_config.get("security.pathGuard.enabled", True)),
                "dangerous_tools_enabled": bool(elyan_config.get("security.enableDangerousTools", True)),
                "require_confirmation_for_risky": bool(elyan_config.get("security.requireConfirmationForRisky", True)),
                "require_evidence_for_dangerous": bool(elyan_config.get("security.requireEvidenceForDangerous", True)),
            },
            "user_profile": {
                "preferred_language": str(user_profile.get("preferred_language", "auto") or "auto"),
                "response_length_bias": str(user_profile.get("response_length_bias", "short") or "short"),
                "top_topics": list(user_profile.get("top_topics", []) or []),
                "top_actions": list(user_profile.get("top_actions", []) or []),
            },
        }
        return web.json_response({"ok": True, "profile": profile})

    async def handle_agent_profile_update(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        name = str(data.get("name", elyan_config.get("agent.name", "Elyan")) or "Elyan").strip()
        personality = str(data.get("personality", elyan_config.get("agent.personality", "professional")) or "professional").strip().lower()
        language = str(data.get("language", elyan_config.get("agent.language", "tr")) or "tr").strip().lower()
        system_prompt = str(
            data.get("system_prompt", data.get("systemPrompt", elyan_config.get("agent.system_prompt", "")))
            or ""
        ).strip()
        autonomous = bool(data.get("autonomous", elyan_config.get("agent.autonomous", True)))
        max_user_storage_gb = data.get("max_user_storage_gb", elyan_config.get("memory.maxUserStorageGB", 10))
        local_only = bool(data.get("local_only", elyan_config.get("memory.localOnly", True)))

        capability_data = data.get("capability", {}) if isinstance(data.get("capability"), dict) else {}
        planning_data = data.get("planning", {}) if isinstance(data.get("planning"), dict) else {}
        nlu_data = data.get("nlu", {}) if isinstance(data.get("nlu"), dict) else {}
        model_a_data = nlu_data.get("model_a", {}) if isinstance(nlu_data.get("model_a"), dict) else {}
        orchestration_data = data.get("orchestration", {}) if isinstance(data.get("orchestration"), dict) else {}
        flags_data = data.get("flags", {}) if isinstance(data.get("flags"), dict) else {}
        skills_data = data.get("skills", {}) if isinstance(data.get("skills"), dict) else {}
        runtime_policy_data = data.get("runtime_policy", {}) if isinstance(data.get("runtime_policy"), dict) else {}
        user_profile_data = data.get("user_profile", {}) if isinstance(data.get("user_profile"), dict) else {}

        capability_enabled = bool(
            capability_data.get(
                "enabled",
                data.get("capability_enabled", elyan_config.get("agent.capability_router.enabled", True)),
            )
        )
        capability_override_conf = capability_data.get(
            "override_confidence",
            data.get(
                "capability_override_confidence",
                elyan_config.get("agent.capability_router.min_confidence_override", 0.5),
            ),
        )
        api_tools_enabled = bool(
            capability_data.get(
                "api_tools_enabled",
                data.get("api_tools_enabled", elyan_config.get("agent.api_tools.enabled", True)),
            )
        )

        planning_use_llm = bool(
            planning_data.get("use_llm", data.get("planning_use_llm", elyan_config.get("agent.planning.use_llm", True)))
        )
        planning_max_subtasks = planning_data.get(
            "max_subtasks",
            data.get("planning_max_subtasks", elyan_config.get("agent.planning.max_subtasks", 10)),
        )
        model_a_enabled = bool(
            model_a_data.get(
                "enabled",
                data.get("model_a_enabled", elyan_config.get("agent.nlu.model_a.enabled", True)),
            )
        )
        model_a_path = str(
            model_a_data.get(
                "model_path",
                data.get(
                    "model_a_path",
                    elyan_config.get("agent.nlu.model_a.model_path", "~/.elyan/models/nlu/baseline_intent_model.json"),
                ),
            )
            or "~/.elyan/models/nlu/baseline_intent_model.json"
        ).strip()
        model_a_min_confidence = model_a_data.get(
            "min_confidence",
            data.get("model_a_min_confidence", elyan_config.get("agent.nlu.model_a.min_confidence", 0.78)),
        )
        model_a_allowed_actions = model_a_data.get(
            "allowed_actions",
            data.get(
                "model_a_allowed_actions",
                elyan_config.get(
                    "agent.nlu.model_a.allowed_actions",
                    [
                        "open_app",
                        "close_app",
                        "open_url",
                        "web_search",
                        "create_folder",
                        "list_files",
                        "read_file",
                        "write_file",
                        "run_safe_command",
                        "http_request",
                        "api_health_get_save",
                        "set_wallpaper",
                        "analyze_screen",
                        "take_screenshot",
                    ],
                ),
            ),
        )
        flag_agentic_v2 = bool(
            flags_data.get(
                "agentic_v2",
                data.get("flag_agentic_v2", elyan_config.get("agent.flags.agentic_v2", False)),
            )
        )
        flag_dag_exec = bool(
            flags_data.get(
                "dag_exec",
                data.get("flag_dag_exec", elyan_config.get("agent.flags.dag_exec", False)),
            )
        )
        flag_strict_taskspec = bool(
            flags_data.get(
                "strict_taskspec",
                data.get("flag_strict_taskspec", elyan_config.get("agent.flags.strict_taskspec", False)),
            )
        )
        upgrade_flag_names = [
            "upgrade_intent_hardening",
            "upgrade_intent_json_envelope",
            "upgrade_attachment_indexer",
            "upgrade_planning_split_cache",
            "upgrade_orchestration_policy",
            "upgrade_typed_tool_io",
            "typed_tools_strict",
            "upgrade_fallback_ladder",
            "upgrade_verify_mandatory_gates",
            "upgrade_performance_routing",
            "upgrade_telemetry_autotune",
            "upgrade_workspace_isolation",
        ]
        upgrade_flags: dict[str, bool] = {}
        for fname in upgrade_flag_names:
            upgrade_flags[fname] = bool(
                flags_data.get(
                    fname,
                    data.get(fname, elyan_config.get(f"agent.flags.{fname}", False)),
                )
            )

        multi_agent_enabled = bool(
            orchestration_data.get(
                "multi_agent_enabled",
                data.get("multi_agent_enabled", elyan_config.get("agent.multi_agent.enabled", True)),
            )
        )
        multi_agent_complexity_threshold = orchestration_data.get(
            "complexity_threshold",
            data.get("multi_agent_complexity_threshold", elyan_config.get("agent.multi_agent.complexity_threshold", 0.9)),
        )
        multi_agent_capability_threshold = orchestration_data.get(
            "capability_confidence_threshold",
            data.get(
                "multi_agent_capability_threshold",
                elyan_config.get("agent.multi_agent.capability_confidence_threshold", 0.7),
            ),
        )
        orchestration_max_parallel = orchestration_data.get(
            "max_parallel",
            data.get(
                "orchestration_max_parallel",
                elyan_config.get(
                    "agent.orchestration.max_parallel",
                    elyan_config.get("agent.team_mode.max_parallel", 4),
                ),
            ),
        )
        team_mode_enabled = bool(
            orchestration_data.get(
                "team_mode_enabled",
                data.get("team_mode_enabled", elyan_config.get("agent.team_mode.enabled", True)),
            )
        )
        team_mode_threshold = orchestration_data.get(
            "team_threshold",
            data.get("team_mode_threshold", elyan_config.get("agent.team_mode.threshold", 0.95)),
        )
        team_max_parallel = orchestration_data.get(
            "team_max_parallel",
            data.get("team_max_parallel", elyan_config.get("agent.team_mode.max_parallel", 4)),
        )
        team_timeout_s = orchestration_data.get(
            "team_timeout_s",
            data.get("team_timeout_s", elyan_config.get("agent.team_mode.timeout_s", 900)),
        )
        team_max_retries_per_task = orchestration_data.get(
            "team_max_retries_per_task",
            data.get("team_max_retries_per_task", elyan_config.get("agent.team_mode.max_retries_per_task", 1)),
        )
        skills_enabled = skills_data.get("enabled", data.get("skills_enabled", elyan_config.get("skills.enabled", [])))
        workflows_enabled = skills_data.get(
            "workflows_enabled",
            data.get("workflows_enabled", elyan_config.get("skills.workflows.enabled", [])),
        )
        runtime_policy_preset = str(
            runtime_policy_data.get(
                "preset",
                data.get("runtime_policy_preset", elyan_config.get("agent.runtime_policy.preset", "balanced")),
            )
            or "balanced"
        ).strip().lower()
        model_local_first = bool(
            runtime_policy_data.get(
                "model_local_first",
                data.get("model_local_first", elyan_config.get("agent.model.local_first", True)),
            )
        )
        dashboard_strategy = str(
            runtime_policy_data.get(
                "dashboard_strategy",
                data.get("dashboard_strategy", elyan_config.get("ui.dashboard.strategy", "balanced")),
            )
            or "balanced"
        ).strip().lower()
        response_mode = str(
            runtime_policy_data.get(
                "response_mode",
                data.get("response_mode", elyan_config.get("agent.response_style.mode", "friendly")),
            )
            or "friendly"
        ).strip().lower()
        response_friendly = bool(
            runtime_policy_data.get(
                "response_friendly",
                data.get("response_friendly", elyan_config.get("agent.response_style.friendly", True)),
            )
        )
        share_manifest_default = bool(
            runtime_policy_data.get(
                "share_manifest_default",
                data.get("share_manifest_default", elyan_config.get("agent.response_style.share_manifest_default", False)),
            )
        )
        share_attachments_default = bool(
            runtime_policy_data.get(
                "share_attachments_default",
                data.get(
                    "share_attachments_default",
                    elyan_config.get("agent.response_style.share_attachments_default", False),
                ),
            )
        )
        kvkk_strict_mode = bool(
            runtime_policy_data.get(
                "kvkk_strict_mode",
                data.get("kvkk_strict_mode", elyan_config.get("security.kvkk.strict", True)),
            )
        )
        redact_cloud_prompts = bool(
            runtime_policy_data.get(
                "redact_cloud_prompts",
                data.get("redact_cloud_prompts", elyan_config.get("security.kvkk.redactCloudPrompts", True)),
            )
        )
        allow_cloud_fallback = bool(
            runtime_policy_data.get(
                "allow_cloud_fallback",
                data.get("allow_cloud_fallback", elyan_config.get("security.kvkk.allowCloudFallback", True)),
            )
        )
        default_user_role = str(
            runtime_policy_data.get(
                "default_user_role",
                data.get("default_user_role", elyan_config.get("security.defaultUserRole", "operator")),
            )
            or "operator"
        ).strip().lower()
        enforce_rbac = bool(
            runtime_policy_data.get(
                "enforce_rbac",
                data.get("enforce_rbac", elyan_config.get("security.enforceRBAC", True)),
            )
        )
        path_guard_enabled = bool(
            runtime_policy_data.get(
                "path_guard_enabled",
                data.get("path_guard_enabled", elyan_config.get("security.pathGuard.enabled", True)),
            )
        )
        dangerous_tools_enabled = bool(
            runtime_policy_data.get(
                "dangerous_tools_enabled",
                data.get("dangerous_tools_enabled", elyan_config.get("security.enableDangerousTools", True)),
            )
        )
        require_confirmation_for_risky = bool(
            runtime_policy_data.get(
                "require_confirmation_for_risky",
                data.get("require_confirmation_for_risky", elyan_config.get("security.requireConfirmationForRisky", True)),
            )
        )
        require_evidence_for_dangerous = bool(
            runtime_policy_data.get(
                "require_evidence_for_dangerous",
                data.get("require_evidence_for_dangerous", elyan_config.get("security.requireEvidenceForDangerous", True)),
            )
        )
        response_length_bias = str(
            user_profile_data.get("response_length_bias", data.get("response_length_bias", "short")) or "short"
        ).strip().lower()

        if personality not in {"professional", "technical", "friendly", "concise", "creative"}:
            personality = "professional"
        if language not in {"tr", "en"}:
            language = "tr"
        if len(system_prompt) > 12000:
            return web.json_response({"ok": False, "error": "system_prompt too long (max 12000 chars)"}, status=400)
        try:
            max_user_storage_gb = max(1.0, min(50.0, float(max_user_storage_gb)))
        except Exception:
            max_user_storage_gb = float(elyan_config.get("memory.maxUserStorageGB", 10) or 10)
        try:
            capability_override_conf = max(0.0, min(1.0, float(capability_override_conf)))
        except Exception:
            capability_override_conf = float(elyan_config.get("agent.capability_router.min_confidence_override", 0.5) or 0.5)
        try:
            planning_max_subtasks = max(1, min(20, int(planning_max_subtasks)))
        except Exception:
            planning_max_subtasks = int(elyan_config.get("agent.planning.max_subtasks", 10) or 10)
        try:
            model_a_min_confidence = max(0.4, min(0.99, float(model_a_min_confidence)))
        except Exception:
            model_a_min_confidence = float(elyan_config.get("agent.nlu.model_a.min_confidence", 0.78) or 0.78)
        if not model_a_path:
            model_a_path = str(
                elyan_config.get("agent.nlu.model_a.model_path", "~/.elyan/models/nlu/baseline_intent_model.json")
                or "~/.elyan/models/nlu/baseline_intent_model.json"
            )
        if not isinstance(model_a_allowed_actions, list):
            model_a_allowed_actions = list(
                elyan_config.get(
                    "agent.nlu.model_a.allowed_actions",
                    [
                        "open_app",
                        "close_app",
                        "open_url",
                        "web_search",
                        "create_folder",
                        "list_files",
                        "read_file",
                        "write_file",
                        "run_safe_command",
                        "http_request",
                        "api_health_get_save",
                        "set_wallpaper",
                        "analyze_screen",
                        "take_screenshot",
                    ],
                )
                or []
            )
        model_a_allowed_actions = [str(x).strip().lower() for x in model_a_allowed_actions if str(x).strip()]
        if not model_a_allowed_actions:
            model_a_allowed_actions = [
                "open_app",
                "close_app",
                "open_url",
                "web_search",
                "create_folder",
                "list_files",
                "read_file",
                "write_file",
                "run_safe_command",
                "http_request",
                "api_health_get_save",
                "set_wallpaper",
                "analyze_screen",
                "take_screenshot",
            ]
        try:
            multi_agent_complexity_threshold = max(0.5, min(1.0, float(multi_agent_complexity_threshold)))
        except Exception:
            multi_agent_complexity_threshold = float(elyan_config.get("agent.multi_agent.complexity_threshold", 0.9) or 0.9)
        try:
            multi_agent_capability_threshold = max(0.3, min(1.0, float(multi_agent_capability_threshold)))
        except Exception:
            multi_agent_capability_threshold = float(
                elyan_config.get("agent.multi_agent.capability_confidence_threshold", 0.7) or 0.7
            )
        try:
            team_mode_threshold = max(0.6, min(1.0, float(team_mode_threshold)))
        except Exception:
            team_mode_threshold = float(elyan_config.get("agent.team_mode.threshold", 0.95) or 0.95)
        try:
            team_max_parallel = max(1, min(8, int(team_max_parallel)))
        except Exception:
            team_max_parallel = int(elyan_config.get("agent.team_mode.max_parallel", 4) or 4)
        try:
            orchestration_max_parallel = max(1, min(8, int(orchestration_max_parallel)))
        except Exception:
            orchestration_max_parallel = int(
                elyan_config.get(
                    "agent.orchestration.max_parallel",
                    elyan_config.get("agent.team_mode.max_parallel", 4),
                )
                or 4
            )
        try:
            team_timeout_s = max(60, min(3600, int(team_timeout_s)))
        except Exception:
            team_timeout_s = int(elyan_config.get("agent.team_mode.timeout_s", 900) or 900)
        try:
            team_max_retries_per_task = max(0, min(4, int(team_max_retries_per_task)))
        except Exception:
            team_max_retries_per_task = int(elyan_config.get("agent.team_mode.max_retries_per_task", 1) or 1)
        if not isinstance(skills_enabled, list):
            skills_enabled = list(elyan_config.get("skills.enabled", []) or [])
        if not isinstance(workflows_enabled, list):
            workflows_enabled = list(elyan_config.get("skills.workflows.enabled", []) or [])
        skills_enabled = [str(x).strip() for x in skills_enabled if str(x).strip()]
        workflows_enabled = [str(x).strip() for x in workflows_enabled if str(x).strip()]

        elyan_config.set("agent.name", name or "Elyan")
        elyan_config.set("agent.personality", personality)
        elyan_config.set("agent.language", language)
        elyan_config.set("agent.system_prompt", system_prompt)
        # legacy key for compatibility
        elyan_config.set("agent.systemPrompt", system_prompt)
        elyan_config.set("agent.autonomous", autonomous)
        elyan_config.set("memory.maxUserStorageGB", max_user_storage_gb)
        elyan_config.set("memory.localOnly", local_only)
        elyan_config.set("agent.capability_router.enabled", capability_enabled)
        elyan_config.set("agent.capability_router.min_confidence_override", capability_override_conf)
        elyan_config.set("agent.api_tools.enabled", api_tools_enabled)
        elyan_config.set("agent.planning.use_llm", planning_use_llm)
        elyan_config.set("agent.planning.max_subtasks", planning_max_subtasks)
        elyan_config.set("agent.nlu.model_a.enabled", model_a_enabled)
        elyan_config.set("agent.nlu.model_a.model_path", model_a_path)
        elyan_config.set("agent.nlu.model_a.min_confidence", model_a_min_confidence)
        elyan_config.set("agent.nlu.model_a.allowed_actions", model_a_allowed_actions)
        elyan_config.set("agent.flags.agentic_v2", flag_agentic_v2)
        elyan_config.set("agent.flags.dag_exec", flag_dag_exec)
        elyan_config.set("agent.flags.strict_taskspec", flag_strict_taskspec)
        for fname, fval in upgrade_flags.items():
            elyan_config.set(f"agent.flags.{fname}", bool(fval))
        elyan_config.set("agent.multi_agent.enabled", multi_agent_enabled)
        elyan_config.set("agent.multi_agent.complexity_threshold", multi_agent_complexity_threshold)
        elyan_config.set("agent.multi_agent.capability_confidence_threshold", multi_agent_capability_threshold)
        elyan_config.set("agent.orchestration.max_parallel", orchestration_max_parallel)
        elyan_config.set("agent.team_mode.enabled", team_mode_enabled)
        elyan_config.set("agent.team_mode.threshold", team_mode_threshold)
        elyan_config.set("agent.team_mode.max_parallel", team_max_parallel)
        elyan_config.set("agent.team_mode.timeout_s", team_timeout_s)
        elyan_config.set("agent.team_mode.max_retries_per_task", team_max_retries_per_task)
        elyan_config.set("agent.model.local_first", model_local_first)
        elyan_config.set("ui.dashboard.strategy", dashboard_strategy)
        elyan_config.set("skills.enabled", skills_enabled)
        elyan_config.set("skills.workflows.enabled", workflows_enabled)

        if runtime_policy_preset in {"strict", "balanced", "full-autonomy"}:
            try:
                get_runtime_policy_resolver().apply_preset(runtime_policy_preset)
            except Exception:
                elyan_config.set("agent.runtime_policy.preset", runtime_policy_preset)
        else:
            elyan_config.set("agent.runtime_policy.preset", "custom")

        # Manual runtime security toggles override preset values when explicitly saved from dashboard.
        if default_user_role not in {"admin", "operator", "viewer"}:
            default_user_role = "operator"
        if response_mode not in {"friendly", "concise", "formal"}:
            response_mode = "friendly"
        if response_length_bias not in {"short", "medium", "detailed"}:
            response_length_bias = "short"
        elyan_config.set("security.kvkk.strict", kvkk_strict_mode)
        elyan_config.set("security.kvkk.redactCloudPrompts", redact_cloud_prompts)
        elyan_config.set("security.kvkk.allowCloudFallback", allow_cloud_fallback)
        elyan_config.set("security.defaultUserRole", default_user_role)
        elyan_config.set("security.enforceRBAC", enforce_rbac)
        elyan_config.set("security.pathGuard.enabled", path_guard_enabled)
        elyan_config.set("security.enableDangerousTools", dangerous_tools_enabled)
        elyan_config.set("security.requireConfirmationForRisky", require_confirmation_for_risky)
        elyan_config.set("security.requireEvidenceForDangerous", require_evidence_for_dangerous)
        elyan_config.set("agent.response_style.mode", response_mode)
        elyan_config.set("agent.response_style.friendly", response_friendly)
        elyan_config.set("agent.response_style.share_manifest_default", share_manifest_default)
        elyan_config.set("agent.response_style.share_attachments_default", share_attachments_default)
        try:
            profile_store = get_user_profile_store()
            local_profile = profile_store.get("local")
            local_profile["preferred_language"] = language
            local_profile["response_length_bias"] = response_length_bias
            local_profile["updated_at"] = int(time.time())
            profile_store._save()
        except Exception:
            pass

        push_activity("agent_profile", "dashboard", f"profile updated ({personality}/{language}, ma={multi_agent_enabled})", True)

        return await self.handle_agent_profile_get(request)

    async def handle_models_get(self, request):
        default = elyan_config.get("models.default", {}) or {}
        fallback = elyan_config.get("models.fallback", {}) or {}
        roles = elyan_config.get("models.roles", {}) or {}
        registry = _sanitize_model_registry(elyan_config.get("models.registry", []) or [])
        collaboration = _sanitize_collaboration_payload(elyan_config.get("models.collaboration", {}) or {})
        router_enabled = bool(elyan_config.get("router.enabled", True))
        providers_cfg = elyan_config.get("models.providers", {}) or {}
        known = {"openai", "anthropic", "google", "groq", "ollama"}
        known.update({str(k).strip().lower() for k in providers_cfg.keys() if str(k).strip()})
        known.update({str(item.get("provider") or "").strip().lower() for item in registry if isinstance(item, dict)})
        provider_keys = {p: _provider_key_status(p) for p in sorted(known)}
        collaboration_pool = []
        try:
            from core.model_orchestrator import model_orchestrator
            collaboration_pool = model_orchestrator.list_registered_models()
        except Exception:
            collaboration_pool = registry
        state = {
            "ok": True,
            "default": {
                "provider": default.get("provider", "openai"),
                "model": default.get("model", "gpt-4o"),
            },
            "fallback": {
                "provider": fallback.get("provider", "openai"),
                "model": fallback.get("model", "gpt-4o"),
            },
            "roles": roles if isinstance(roles, dict) else {},
            "registry": registry,
            "collaboration": collaboration,
            "registered_models": collaboration_pool,
            "router_enabled": router_enabled,
            "provider_keys": provider_keys,
            **_get_runtime_model_info(),
        }
        return web.json_response(state)

    async def handle_models_update(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        current_default = elyan_config.get("models.default", {}) or {}
        current_fallback = elyan_config.get("models.fallback", {}) or {}

        provider = str(
            data.get("provider")
            or data.get("default_provider")
            or current_default.get("provider", "openai")
        ).strip().lower()
        model = str(
            data.get("model")
            or data.get("default_model")
            or current_default.get("model", "")
        ).strip()
        if not model:
            model = _default_model_for_provider(provider)

        fallback_provider = str(
            data.get("fallback_provider")
            or current_fallback.get("provider", "openai")
        ).strip().lower()
        fallback_model = str(
            data.get("fallback_model")
            or current_fallback.get("model", "")
        ).strip()
        if not fallback_model:
            fallback_model = _default_model_for_provider(fallback_provider)

        router_enabled = data.get("router_enabled", None)
        sync_roles = bool(data.get("sync_roles", True))
        requested_roles = data.get("roles", {})
        requested_registry = _sanitize_model_registry(data.get("registry", []))
        requested_collaboration = _sanitize_collaboration_payload(data.get("collaboration", {}))

        # Optional API key updates (write-only)
        api_keys = data.get("api_keys", {})
        clear_keys = data.get("clear_keys", [])
        if not isinstance(api_keys, dict):
            api_keys = {}
        if not isinstance(clear_keys, list):
            clear_keys = []

        key_updates = []
        key_errors = []

        for raw_provider, raw_secret in api_keys.items():
            provider_name = str(raw_provider or "").strip().lower()
            if provider_name not in _PROVIDER_ENV_KEYS:
                continue
            secret = str(raw_secret or "").strip()
            if not secret:
                continue
            env_key = _provider_env_key(provider_name)
            keychain_key = KeychainManager.key_for_env(env_key)
            stored = False
            store_mode = "config"
            if keychain_key and KeychainManager.is_available():
                try:
                    stored = bool(KeychainManager.set_key(keychain_key, secret))
                except Exception:
                    stored = False
            if stored:
                elyan_config.set(f"models.providers.{provider_name}.apiKey", f"${env_key}")
                store_mode = "keychain"
            else:
                # Fallback (non-macOS / keychain unavailable): keep in config.
                elyan_config.set(f"models.providers.{provider_name}.apiKey", secret)
            key_updates.append({"provider": provider_name, "stored_in": store_mode})

        for raw_provider in clear_keys:
            provider_name = str(raw_provider or "").strip().lower()
            if provider_name not in _PROVIDER_ENV_KEYS:
                continue
            env_key = _provider_env_key(provider_name)
            keychain_key = KeychainManager.key_for_env(env_key)
            cleared = False
            if keychain_key and KeychainManager.is_available():
                try:
                    KeychainManager.delete_key(keychain_key)
                    cleared = True
                except Exception as exc:
                    key_errors.append(f"{provider_name}: {exc}")
            # Always clear config fallback value.
            elyan_config.set(f"models.providers.{provider_name}.apiKey", "")
            key_updates.append({"provider": provider_name, "cleared": True, "keychain": bool(cleared)})

        elyan_config.set("models.default.provider", provider)
        elyan_config.set("models.default.model", model)
        elyan_config.set("models.fallback.provider", fallback_provider)
        elyan_config.set("models.fallback.model", fallback_model)

        if router_enabled is not None:
            elyan_config.set("router.enabled", bool(router_enabled))

        if requested_registry:
            elyan_config.set("models.registry", requested_registry)
        elif "registry" in data:
            elyan_config.set("models.registry", [])

        if requested_collaboration or "collaboration" in data:
            elyan_config.set("models.collaboration", requested_collaboration)

        if sync_roles:
            role_map = {
                "router": {"provider": "ollama", "model": str(elyan_config.get("models.local.model", _default_model_for_provider("ollama")))},
                "reasoning": {"provider": provider, "model": model},
                "inference": {"provider": provider, "model": model},
                "creative": {"provider": provider, "model": model},
                "planning": {"provider": provider, "model": model},
                "code": {"provider": provider, "model": model},
                "critic": {"provider": provider, "model": model},
                "qa": {"provider": provider, "model": model},
                "research_worker": {"provider": provider, "model": model},
                "code_worker": {"provider": provider, "model": model},
            }
            elyan_config.set("models.roles", role_map)
        else:
            role_map = _sanitize_roles_map(requested_roles, provider, model)
            if role_map:
                elyan_config.set("models.roles", role_map)

        # Keep runtime provider cache aligned after updates.
        try:
            from core.model_orchestrator import model_orchestrator
            model_orchestrator.active_provider = model_orchestrator._normalize_provider(provider)
            model_orchestrator._load_providers()
            registered_models = model_orchestrator.list_registered_models()
        except Exception:
            registered_models = registry

        push_activity("models", "dashboard", f"default={provider}/{model}", True)
        default = elyan_config.get("models.default", {}) or {}
        fallback = elyan_config.get("models.fallback", {}) or {}
        roles = elyan_config.get("models.roles", {}) or {}
        registry = _sanitize_model_registry(elyan_config.get("models.registry", []) or [])
        collaboration = _sanitize_collaboration_payload(elyan_config.get("models.collaboration", {}) or {})
        router_enabled = bool(elyan_config.get("router.enabled", True))
        providers_cfg = elyan_config.get("models.providers", {}) or {}
        known = {"openai", "anthropic", "google", "groq", "ollama"}
        known.update({str(k).strip().lower() for k in providers_cfg.keys() if str(k).strip()})
        known.update({str(item.get("provider") or "").strip().lower() for item in registry if isinstance(item, dict)})
        return web.json_response({
            "ok": True,
            "default": {
                "provider": default.get("provider", "openai"),
                "model": default.get("model", "gpt-4o"),
            },
            "fallback": {
                "provider": fallback.get("provider", "openai"),
                "model": fallback.get("model", "gpt-4o"),
            },
            "roles": roles if isinstance(roles, dict) else {},
            "registry": registry,
            "collaboration": collaboration,
            "router_enabled": router_enabled,
            "provider_keys": {p: _provider_key_status(p) for p in sorted(known)},
            "registered_models": registered_models,
            "key_updates": key_updates,
            "key_errors": key_errors,
            **_get_runtime_model_info(),
        })

    async def handle_ollama_list(self, request):
        from tools.ai_tools import ollama_list_models
        res = await ollama_list_models()
        return web.json_response(res)

    async def handle_ollama_pull(self, request):
        try:
            data = await request.json()
            model_name = data.get("model")
            if not model_name:
                return web.json_response({"success": False, "error": "model name required"}, status=400)
            
            from tools.ai_tools import ollama_pull_model
            # Start pull in background to avoid timeout
            asyncio.create_task(ollama_pull_model(model_name))
            
            push_activity("ollama_pull", "dashboard", f"Pulling {model_name}...")
            return web.json_response({"success": True, "message": f"{model_name} indirme işlemi arka planda başlatıldı."})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    # ── Canvas ────────────────────────────────────────────────────────────────
    async def handle_get_canvas(self, request):
        canvas_id = request.match_info.get('id')
        from core.canvas.engine import canvas_engine
        view = canvas_engine.get_view(canvas_id)
        if view:
            return web.json_response(view)
        return web.Response(status=404, text="Canvas not found")

    # ── Status ────────────────────────────────────────────────────────────────
    async def handle_status(self, request):
        from core.monitoring import get_resource_monitor, get_monitoring
        monitor = get_resource_monitor()
        health = monitor.get_health_snapshot()
        mon = get_monitoring()
        orchestration_summary = mon.get_orchestration_summary()
        pipeline_jobs_summary = mon.get_pipeline_job_summary()
        
        import psutil
        uptime_s = int(time.time() - _start_time)
        days, rem = divmod(uptime_s, 86400)
        hours, rem = divmod(rem, 3600)
        minutes, seconds = divmod(rem, 60)
        if days:
            uptime = f"{days}d {hours}s {minutes}dk"
        elif hours:
            uptime = f"{hours}s {minutes}dk"
        elif minutes:
            uptime = f"{minutes}dk {seconds}sn"
        else:
            uptime = f"{seconds}sn"
        adapter_status = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {
            k: a.get_status() for k, a in self.router.adapters.items()
        }
        adapter_health = self.router.get_adapter_health() if hasattr(self.router, "get_adapter_health") else {}
        adapter_total = len(adapter_status) if isinstance(adapter_status, dict) else 0
        adapter_healthy = 0
        adapter_optional = 0
        for _name, st in (adapter_status.items() if isinstance(adapter_status, dict) else []):
            health_row = adapter_health.get(_name, {}) if isinstance(adapter_health, dict) else {}
            bucket = _adapter_health_bucket(_name, st, health_row if isinstance(health_row, dict) else {})
            if bucket == "healthy":
                adapter_healthy += 1
            elif bucket == "optional":
                adapter_optional += 1
        adapter_degraded = max(0, adapter_total - adapter_healthy - adapter_optional)

        tool_names = AVAILABLE_TOOLS.names() if hasattr(AVAILABLE_TOOLS, "names") else list(AVAILABLE_TOOLS.keys())
        tools_total = len(tool_names)
        from tools import get_tool_load_errors

        tool_load_errors = get_tool_load_errors()
        load_error_count = len(tool_load_errors)

        runtime_health = {
            "status": "degraded" if (load_error_count > 0 or adapter_degraded > 0) else "healthy",
            "tooling": {
                "tools_total": tools_total,
                "load_errors": load_error_count,
            },
            "channels": {
                "total": adapter_total,
                "healthy": adapter_healthy,
                "degraded": adapter_degraded,
                "optional": adapter_optional,
            },
        }
        try:
            personalization_status = get_personalization_manager().get_status()
        except Exception as personalization_exc:
            personalization_status = {
                "enabled": False,
                "status": "error",
                "error": str(personalization_exc),
            }
        try:
            ml_status = get_model_runtime().snapshot()
        except Exception as ml_exc:
            ml_status = {
                "enabled": False,
                "status": "error",
                "error": str(ml_exc),
            }
        try:
            reliability_status = {
                "store": get_outcome_store().stats(),
                "evaluation": get_regression_evaluator().summary(),
            }
        except Exception as reliability_exc:
            reliability_status = {
                "status": "error",
                "error": str(reliability_exc),
            }
        try:
            learning_status = get_learning_control_plane().get_status()
        except Exception as learning_exc:
            learning_status = {
                "status": "error",
                "error": str(learning_exc),
            }
        try:
            autopilot_status = get_autopilot().get_status()
        except Exception as autopilot_exc:
            autopilot_status = {
                "status": "error",
                "error": str(autopilot_exc),
            }
        try:
            runtime_control_status = get_runtime_control_plane().get_status()
        except Exception as runtime_control_exc:
            runtime_control_status = {
                "status": "error",
                "error": str(runtime_control_exc),
            }
        try:
            operator_status = get_operator_control_plane().get_status()
        except Exception as operator_exc:
            operator_status = {
                "status": "error",
                "error": str(operator_exc),
            }
        try:
            dependency_runtime = get_dependency_runtime().snapshot()
        except Exception as dependency_exc:
            dependency_runtime = {
                "enabled": False,
                "mode": "error",
                "error": str(dependency_exc),
            }
        try:
            from core.integration_trace import get_integration_trace_store
            from integrations import oauth_broker

            integration_summary = {
                "traces": get_integration_trace_store().summary(limit=100),
                "accounts": {
                    "total": len(oauth_broker.list_accounts()),
                    "by_provider": {},
                },
            }
            for account in oauth_broker.list_accounts():
                provider_name = str(account.provider or "").strip().lower() or "unknown"
                bucket = integration_summary["accounts"]["by_provider"].setdefault(provider_name, {"ready": 0, "needs_input": 0, "blocked": 0})
                status_name = str(account.status or "").strip().lower()
                bucket[status_name if status_name in bucket else "needs_input"] = int(bucket.get(status_name if status_name in bucket else "needs_input", 0)) + 1
        except Exception as integration_exc:
            integration_summary = {"status": "error", "error": str(integration_exc)}

        from core.action_lock import action_lock
        return web.json_response({
            "status": "online",
            "health_status": health.status,
            "health_issues": health.issues,
            "cpu_pct": health.cpu_percent,
            "ram_pct": health.ram_percent,
            "disk_pct": health.disk_percent,
            "battery_pct": health.battery_percent,
            "is_on_ac": health.is_on_ac,
            "uptime": uptime,
            "uptime_s": uptime_s,
            "uptime_seconds": uptime_s,
            "version": elyan_config.get("version", APP_VERSION),
            "protocol_version": RUNTIME_PROTOCOL_VERSION,
            "adapters": adapter_status,
            "adapter_health": adapter_health,
            "cron_jobs": len(self.cron.scheduler.get_jobs()),
            "tool_count": tools_total,
            "tools_total": tools_total,
            "runtime_health": runtime_health,
            "personalization": personalization_status,
            "ml": ml_status,
            "reliability": reliability_status,
            "learning": learning_status,
            "autopilot": autopilot_status,
            "runtime_control": runtime_control_status,
            "operator": operator_status,
            "dependency_runtime": dependency_runtime,
            "integrations": integration_summary,
            "runtime": {
                "uptime_seconds": uptime_s,
                "cpu_pct": health.cpu_percent,
                "ram_pct": health.ram_percent,
                "disk_pct": health.disk_percent,
                "protocol_version": RUNTIME_PROTOCOL_VERSION,
                "app_version": elyan_config.get("version", APP_VERSION),
                "tools_total": tools_total,
                "tool_load_errors": load_error_count,
                "channels_total": adapter_total,
                "channels_healthy": adapter_healthy,
                "channels_degraded": adapter_degraded,
                "channels_optional": adapter_optional,
                "health_status": runtime_health["status"],
                "personalization": personalization_status,
                "ml": ml_status,
                "reliability": reliability_status,
                "learning": learning_status,
                "autopilot": autopilot_status,
                "runtime_control": runtime_control_status,
                "dependency_runtime": dependency_runtime,
                "integrations": integration_summary,
                "orchestration": orchestration_summary,
                "pipeline_jobs": pipeline_jobs_summary,
            },
            "orchestration_telemetry": orchestration_summary,
            "pipeline_jobs_telemetry": pipeline_jobs_summary,
            "action_lock": {
                "is_locked": action_lock.is_locked,
                "progress": action_lock.progress,
                "message": action_lock.status_message,
                "task_id": action_lock.current_task_id,
                "policy_scope": getattr(action_lock, "policy_scope", "global"),
                "queue_depth": len(getattr(action_lock, "queued_requests", []) or []),
                "last_conflict": dict(getattr(action_lock, "last_conflict", {}) or {}),
            },
            **_get_runtime_model_info(),
        })

    def _product_workflow_catalog(self) -> list[dict[str, Any]]:
        reports = list_emre_workflow_reports(limit=20)
        latest_by_name = {str(item.get("name") or "").strip(): dict(item) for item in reports if isinstance(item, dict)}
        catalog: list[dict[str, Any]] = []
        for preset in EMRE_WORKFLOW_PRESETS:
            row = dict(preset)
            latest = latest_by_name.get(str(row.get("name") or "").strip(), {})
            catalog.append(
                {
                    "name": str(row.get("name") or "").strip(),
                    "workflow_name": str(row.get("workflow_name") or row.get("name") or "").strip(),
                    "description": str(row.get("description") or "").strip(),
                    "request": str(row.get("request") or "").strip(),
                    "last_status": str(latest.get("status") or "").strip(),
                    "last_failure_code": str(latest.get("failure_code") or "").strip(),
                    "last_retry_count": int(latest.get("retry_count") or 0),
                    "last_replan_count": int(latest.get("replan_count") or 0),
                    "last_updated_at": float(latest.get("updated_at") or 0.0),
                }
            )
        return catalog

    async def _build_product_home_payload(self) -> dict[str, Any]:
        status_req = SimpleNamespace(rel_url=SimpleNamespace(query={}))
        tasks_req = SimpleNamespace(rel_url=SimpleNamespace(query={}))
        runs_req = SimpleNamespace(rel_url=SimpleNamespace(query={"limit": "6"}))
        status_payload = json.loads((await self.handle_status(status_req)).text)
        tasks_payload = json.loads((await self.handle_tasks(tasks_req)).text)
        runs_payload = json.loads((await self.handle_recent_runs(runs_req)).text)
        adapter_status = dict(status_payload.get("adapters") or {}) if isinstance(status_payload.get("adapters"), dict) else {}
        model_info = _get_runtime_model_info()
        benchmark = load_latest_benchmark_summary()
        recent_reports = list_emre_workflow_reports(limit=5)
        permissions = _check_macos_permissions()
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []
        channel_map = {
            _normalize_channel_type(str(item.get("type") or "")): dict(item)
            for item in channels
            if isinstance(item, dict)
        }
        desktop_state_path = resolve_elyan_data_dir() / "desktop_host" / "state.json"
        playwright_ready = importlib.util.find_spec("playwright") is not None
        telegram_status = str(adapter_status.get("telegram") or "").strip().lower()
        telegram_ready = telegram_status in {"connected", "online", "ok", "active", "healthy"}
        imessage_channel = channel_map.get("imessage", {})
        bluebubbles_ready = bool(imessage_channel.get("server_url")) and bool(imessage_channel.get("password"))
        whatsapp_channel = channel_map.get("whatsapp", {})
        whatsapp_mode = str(whatsapp_channel.get("mode") or "bridge").strip().lower() or "bridge"
        desktop_ready = bool(permissions.get("osascript_available")) and bool(permissions.get("screencapture_available"))
        browser_ready = bool(playwright_ready or desktop_ready)
        productivity_apps_ready = bool(desktop_ready or bluebubbles_ready or telegram_ready)
        channel_connected = any(
            str(state or "").strip().lower() in {"connected", "online", "ok", "active", "healthy"}
            for state in adapter_status.values()
        )
        provider = str(model_info.get("active_provider") or "—").strip()
        model = str(model_info.get("active_model") or "—").strip()
        provider_ready = provider not in {"", "—"} and model not in {"", "—"}
        benchmark_green = int(benchmark.get("pass_count") or 0) == int(benchmark.get("total") or 0) and int(benchmark.get("total") or 0) > 0
        runtime_health_status = str(((status_payload.get("runtime_health") if isinstance(status_payload.get("runtime_health"), dict) else {}) or {}).get("status") or "").strip().lower()
        setup_complete = bool(is_setup_complete())
        routines = routine_engine.list_routines()
        has_routine = bool(routines)
        has_daily_summary_run = any(
            str(item.get("template_id") or "").strip() == "personal-daily-summary"
            and (int(item.get("run_count") or 0) > 0 or bool(item.get("history")))
            for item in routines
        )
        learning_counts = {"preferences": 0, "skills": 0, "routines": 0, "total": 0}
        try:
            runtime_db = get_runtime_database()
            latest_session = runtime_db.auth_sessions.get_latest_session()
            if latest_session:
                workspace_id = str(latest_session.get("workspace_id") or "local-workspace")
                actor_id = str(latest_session.get("user_id") or "local-user")
                learning_counts["preferences"] = len(runtime_db.learning.list_preference_updates(workspace_id=workspace_id, user_id=actor_id, limit=5))
                learning_counts["skills"] = len(runtime_db.learning.list_skill_drafts(workspace_id=workspace_id, user_id=actor_id, limit=5))
                learning_counts["routines"] = len(runtime_db.learning.list_routine_drafts(workspace_id=workspace_id, user_id=actor_id, limit=5))
                learning_counts["total"] = int(learning_counts["preferences"]) + int(learning_counts["skills"]) + int(learning_counts["routines"])
        except Exception:
            learning_counts = {"preferences": 0, "skills": 0, "routines": 0, "total": 0}
        core_ready = bool(
            status_payload.get("status") == "online"
            and provider_ready
            and browser_ready
            and setup_complete
            and runtime_health_status != "degraded"
        )
        first_demo = str((EMRE_WORKFLOW_PRESETS[0] if EMRE_WORKFLOW_PRESETS else {}).get("name") or "").strip()
        cli_mod = f"{Path(os.sys.executable)} -m cli.main"
        setup = [
            {
                "key": "provider_model",
                "label": "Provider / model",
                "ready": provider_ready,
                "detail": f"{provider}/{model}",
            },
            {
                "key": "desktop_permissions",
                "label": "Desktop operator readiness",
                "ready": desktop_ready,
                "detail": f"osascript={bool(permissions.get('osascript_available'))} screencapture={bool(permissions.get('screencapture_available'))}",
            },
            {
                "key": "channel_connection",
                "label": "Channel connection readiness",
                "ready": channel_connected,
                "detail": ",".join(
                    sorted(
                        key for key, value in adapter_status.items()
                        if str(value or "").strip().lower() in {"connected", "online", "ok", "active", "healthy"}
                    )
                ) or "not_connected",
            },
            {
                "key": "browser",
                "label": "Browser readiness",
                "ready": browser_ready,
                "detail": "playwright" if playwright_ready else "screen-operator fallback",
            },
            {
                "key": "first_routine",
                "label": "First routine created",
                "ready": has_routine,
                "detail": str(routines[0].get("name") or "not_created") if routines else "not_created",
            },
            {
                "key": "first_daily_summary",
                "label": "First daily summary executed",
                "ready": has_daily_summary_run,
                "detail": "personal-daily-summary" if has_daily_summary_run else "run a daily summary routine once",
            },
            {
                "key": "apple_apps",
                "label": "Apple apps readiness",
                "ready": productivity_apps_ready,
                "detail": f"automation={bool(permissions.get('osascript_available'))} bluebubbles={bluebubbles_ready}",
            },
            {
                "key": "whatsapp",
                "label": "WhatsApp lane",
                "ready": str(adapter_status.get("whatsapp") or "").strip().lower() in {"connected", "online", "ok", "active", "healthy"},
                "detail": whatsapp_mode,
            },
            {
                "key": "demo_workflow",
                "label": "First demo workflow execution",
                "ready": bool(recent_reports),
                "detail": str(recent_reports[0].get("workflow_name") or first_demo or "not_run") if recent_reports else (first_demo or "not_run"),
            },
            {
                "key": "learning_queue",
                "label": "Learned draft review",
                "ready": int(learning_counts["total"]) == 0,
                "detail": f"preferences={learning_counts['preferences']} skills={learning_counts['skills']} routines={learning_counts['routines']}",
            },
        ]
        return {
            "ok": True,
            "readiness": {
                "elyan_ready": core_ready,
                "desktop_operator_ready": desktop_ready,
                "browser_ready": browser_ready,
                "telegram_ready": telegram_ready,
                "channel_connected": channel_connected,
                "apple_permissions": {
                    "automation": bool(permissions.get("osascript_available")),
                    "screen_capture": bool(permissions.get("screencapture_available")),
                },
                "bluebubbles_ready": bluebubbles_ready,
                "whatsapp_mode": whatsapp_mode,
                "productivity_apps_ready": productivity_apps_ready,
                "connected_provider": provider,
                "connected_model": model,
                "runtime_health": runtime_health_status,
                "desktop_state_available": desktop_state_path.exists(),
                "setup_complete": setup_complete,
                "learning_queue": learning_counts,
                "has_routine": has_routine,
                "has_daily_summary_run": has_daily_summary_run,
            },
            "recent_tasks": {
                "active": list(tasks_payload.get("active") or [])[:5],
                "history": list(tasks_payload.get("history") or [])[:5],
            },
            "recent_runs": list(runs_payload.get("runs") or [])[:6],
            "preset_workflows": self._product_workflow_catalog(),
            "recent_workflow_reports": recent_reports,
            "benchmark": benchmark,
            "setup": setup,
            "onboarding": {
                "first_demo_workflow": first_demo,
                "recommended_steps": [
                    {"label": "Provider / model sec", "ready": provider_ready},
                    {"label": "Desktop izinlerini dogrula", "ready": desktop_ready},
                    {"label": "Bir kanal bagla", "ready": channel_connected},
                    {"label": "Browser hazirligini kontrol et", "ready": browser_ready},
                    {"label": "Ilk rutini olustur", "ready": has_routine},
                    {"label": "Ilk gunluk ozeti calistir", "ready": has_daily_summary_run},
                    {"label": "Ogrenilen draftlari gozden gecir", "ready": int(learning_counts["total"]) == 0},
                    {"label": "Ilk demo workflow'u calistir", "ready": bool(recent_reports)},
                ],
            },
            "release": {
                "version": str(status_payload.get("version") or ""),
                "entrypoint": "elyan desktop",
                "entrypoint_aliases": ["elyan desktop", "elyan launch"],
                "health_endpoint": "/healthz",
                "health_status": str(status_payload.get("health_status") or ""),
                "benchmark_green": benchmark_green,
                "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
                "quickstart_checks": [
                    {"label": "Gateway status", "value": str(status_payload.get("status") or "unknown")},
                    {"label": "Desktop entrypoint", "value": "elyan desktop"},
                    {"label": "Health page", "value": "/healthz"},
                    {"label": "CLI quickstart", "value": f"{cli_mod} desktop"},
                    {"label": "Desktop start script", "value": "bash scripts/start_product.sh"},
                    {
                        "label": "Production benchmark gate",
                        "value": "python scripts/run_production_path_benchmarks.py --min-pass-count 20 --require-perfect",
                    },
                    {
                        "label": "Hero workflow pack",
                        "value": "python scripts/run_emre_workflow_pack.py",
                    },
                ],
            },
        }

    async def handle_product_home(self, request):
        return web.json_response(await self._build_product_home_payload())

    async def handle_product_health(self, request):
        home = await self._build_product_home_payload()
        readiness = dict(home.get("readiness") or {})
        benchmark = dict(home.get("benchmark") or {})
        release = dict(home.get("release") or {})
        try:
            from core.dependencies import get_system_dependency_runtime

            system_dependencies = get_system_dependency_runtime().snapshot()
        except Exception:
            system_dependencies = {"enabled": False, "status_counts": {}}
        payload: dict = {
                "ok": bool(readiness.get("elyan_ready")),
                "status": "ready" if readiness.get("elyan_ready") else "degraded",
                "version": str(release.get("version") or ""),
                "protocol_version": RUNTIME_PROTOCOL_VERSION,
                "health_status": str(release.get("health_status") or ""),
                "entrypoint": str(release.get("entrypoint") or "elyan desktop"),
                "runtime": {
                    "protocol_version": RUNTIME_PROTOCOL_VERSION,
                    "app_version": str(release.get("version") or APP_VERSION),
                    "health_status": str(release.get("health_status") or ""),
                    "entrypoint": str(release.get("entrypoint") or "elyan desktop"),
                },
                "benchmark": benchmark,
                "readiness": readiness,
                "system_dependencies": system_dependencies,
            }
        # Non-Tauri (browser/dev) mode: expose admin token to loopback callers so
        # AppProviders.tsx can call apiClient.setAdminToken() without Rust involvement.
        if _is_loopback_request(request):
            payload["admin_token"] = _ensure_admin_access_token()

        # Elyan subsystem status (non-blocking)
        elyan_status: dict = {}
        try:
            from core.voice.voice_pipeline import get_voice_pipeline
            from core.voice.wake_word import get_wake_word_detector
            from core.proactive.system_monitor import get_system_monitor
            elyan_status = {
                "voice_state": get_voice_pipeline().state.value,
                "wake_backend": get_wake_word_detector().backend,
                "monitor_running": get_system_monitor().running,
            }
        except Exception:
            pass
        payload["elyan"] = elyan_status

        return web.json_response(payload)

    async def handle_product_workflows(self, request):
        return web.json_response({"ok": True, "workflows": self._product_workflow_catalog()})

    async def handle_product_workflow_reports(self, request):
        try:
            limit = int(request.rel_url.query.get("limit", 8))
        except Exception:
            limit = 8
        return web.json_response({"ok": True, "reports": list_emre_workflow_reports(limit=limit)})

    async def handle_product_workflow_run(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name") or "").strip()
        if not name:
            return web.json_response({"ok": False, "error": "workflow name required"}, status=400)
        try:
            report = await run_emre_workflow_preset(name, clear_live_state=bool(data.get("clear_live_state", True)))
        except ValueError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=400)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)
        push_activity("workflow_run", "dashboard", f"{name} -> {report.get('status')}", bool(report.get("success")))
        return web.json_response({"ok": True, **report})

    # ── Analytics (new) ───────────────────────────────────────────────────────
    async def handle_analytics(self, request):
        """Aggregate analytics for dashboard overview cards."""
        try:
            from core.pipeline_state import get_pipeline_state
            ps = get_pipeline_state()
            summary = ps.history_summary(window_hours=24)
            total_ops = int(summary.get("recent_total", 0))
            success_rate = float(summary.get("recent_success_rate", 0.0))
        except Exception:
            total_ops, success_rate = 0, 0.0

        # Active model info (router-aware, config-consistency included)
        model_info = _get_runtime_model_info()
        model_name = model_info.get("active_model", "—")
        provider = model_info.get("active_provider", "—")

        # Pricing tracker
        cost_usd = 0.0
        total_tokens = 0
        try:
            from core.pricing_tracker import get_pricing_tracker
            pt = get_pricing_tracker()
            stats = pt.get_stats() if hasattr(pt, "get_stats") else {}
            cost_usd = float(stats.get("total_usd", 0))
            total_tokens = int(stats.get("total_tokens", 0))
        except Exception:
            pass

        # Channel/model breakdown from activity log
        from collections import Counter
        ch_counter: Counter = Counter()
        model_counter: Counter = Counter()
        for entry in _activity_log:
            ch = entry.get("channel", "")
            if ch:
                ch_counter[ch] += 1
        if model_name and model_name != "—":
            model_counter[model_name] = total_ops

        import datetime
        day_of_month = datetime.datetime.now().day
        budget_usd = float(elyan_config.get("monthly_budget_usd", 20.0))

        return web.json_response({
            "total_operations": total_ops,
            "total_tasks": total_ops,
            "success_rate": round(success_rate * 100, 1) if success_rate <= 1 else round(success_rate, 1),
            "avg_response_ms": 0,
            "avg_task_time_s": 0,
            "cost_usd": cost_usd,
            "total_cost_usd": cost_usd,
            "cost_limit_usd": float(elyan_config.get("cost_limit_usd", 50.0)),
            "budget_usd": budget_usd,
            "days_elapsed": day_of_month,
            "total_tokens": total_tokens,
            "model": model_name,
            "provider": provider,
            "configured_model": model_info.get("configured_model", "—"),
            "configured_provider": model_info.get("configured_provider", "—"),
            "model_source": model_info.get("model_source", "config"),
            "model_consistent": bool(model_info.get("model_consistent", True)),
            "active_channels": len(self.router.adapters) if hasattr(self.router, "adapters") else 0,
            "channel_breakdown": dict(ch_counter),
            "model_breakdown": dict(model_counter),
        })

    async def handle_subscription_get(self, request):
        user_id = request.query.get("user_id", "local")
        summary = subscription_manager.get_subscription_summary(user_id)
        return web.json_response({
            "ok": True,
            **summary
        })

    async def handle_quota_get(self, request):
        user_id = request.query.get("user_id", "local")
        stats = quota_manager.get_user_stats(user_id)
        return web.json_response({
            "ok": True,
            **stats
        })

    @staticmethod
    def _normalize_foreground_task(record: Any) -> dict[str, Any]:
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record or {})
        context = payload.get("context") if isinstance(payload.get("context"), dict) else {}
        history = payload.get("history") if isinstance(payload.get("history"), list) else []
        artifacts = payload.get("artifacts") if isinstance(payload.get("artifacts"), list) else []
        subtasks = payload.get("subtasks") if isinstance(payload.get("subtasks"), list) else []
        return {
            "task_id": str(payload.get("task_id") or ""),
            "kind": "foreground",
            "objective": str(payload.get("objective") or ""),
            "summary": str(payload.get("objective") or context.get("user_input") or ""),
            "user_id": str(context.get("user_id") or "local"),
            "channel": str(context.get("channel") or ""),
            "state": str(payload.get("state") or "pending"),
            "created_at": float(payload.get("created_at") or 0.0),
            "updated_at": float(payload.get("updated_at") or 0.0),
            "history": history,
            "subtasks": subtasks,
            "artifacts": artifacts,
            "artifacts_count": len(artifacts),
            "mode": "foreground",
            "workflow_id": str(context.get("workflow_id") or ""),
            "capability_domain": str(context.get("capability_domain") or ""),
            "result_summary": "",
            "error": "",
            "retry_count": 0,
            "max_retries": 0,
            "next_retry_at": 0.0,
        }

    @staticmethod
    def _normalize_background_task(record: Any) -> dict[str, Any]:
        payload = record.to_dict() if hasattr(record, "to_dict") else dict(record or {})
        return {
            "task_id": str(payload.get("task_id") or ""),
            "kind": "background",
            "objective": str(payload.get("user_input") or ""),
            "summary": str(payload.get("result_summary") or payload.get("user_input") or ""),
            "user_id": str(payload.get("user_id") or "local"),
            "channel": str(payload.get("channel") or ""),
            "state": str(payload.get("state") or "queued"),
            "created_at": float(payload.get("created_at") or 0.0),
            "updated_at": float(payload.get("updated_at") or 0.0),
            "history": [],
            "subtasks": [],
            "artifacts": list(payload.get("attachments") or []),
            "artifacts_count": len(list(payload.get("attachments") or [])),
            "mode": str(payload.get("mode") or "background"),
            "workflow_id": str(payload.get("workflow_id") or ""),
            "capability_domain": str(payload.get("capability_domain") or ""),
            "result_summary": str(payload.get("result_summary") or ""),
            "error": str(payload.get("error") or ""),
            "retry_count": int(payload.get("retry_count") or 0),
            "max_retries": int(payload.get("max_retries") or 0),
            "next_retry_at": float(payload.get("next_retry_at") or 0.0),
        }

    def _ops_tasks_snapshot(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        try:
            for record in task_brain.list_all():
                items.append(self._normalize_foreground_task(record))
        except Exception:
            pass
        try:
            for record in away_task_registry.list_all():
                items.append(self._normalize_background_task(record))
        except Exception:
            pass
        items.sort(key=lambda row: float(row.get("updated_at") or 0.0), reverse=True)
        return items

    def _ops_users_snapshot(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        user_ids = {
            str(row.get("user_id") or "local")
            for row in tasks
            if str(row.get("user_id") or "").strip()
        }
        user_ids.update(str(user_id or "local") for user_id in getattr(subscription_manager, "_users", {}).keys())
        user_ids.update(str(user_id or "local") for user_id in getattr(quota_manager, "_usage", {}).keys())

        users: list[dict[str, Any]] = []
        for user_id in sorted(user_ids):
            user_tasks = [row for row in tasks if str(row.get("user_id") or "local") == user_id]
            active_tasks = [
                row for row in user_tasks
                if str(row.get("state") or "").lower() not in {"completed", "failed", "cancelled"}
            ]
            background_tasks = [row for row in user_tasks if row.get("kind") == "background"]
            failed_tasks = [row for row in user_tasks if str(row.get("state") or "").lower() in {"failed", "partial"}]
            stats = quota_manager.get_user_stats(user_id)
            quota = quota_manager.check_quota(user_id)
            sub = subscription_manager.get_subscription_summary(user_id)
            raw_usage = getattr(quota_manager, "_usage", {}).get(user_id, {}) if hasattr(quota_manager, "_usage") else {}
            last_active_at = max(
                [float(row.get("updated_at") or 0.0) for row in user_tasks] + [float(raw_usage.get("last_active") or 0.0)]
            )
            users.append({
                "user_id": user_id,
                "tier": str(sub.get("tier") or stats.get("tier") or "free"),
                "subscription_status": str(sub.get("status") or "none"),
                "expiry_at": int(sub.get("expiry_at") or 0),
                "quota": {
                    "allowed": bool(quota.get("allowed", True)),
                    "reason": str(quota.get("reason") or "within_limits"),
                    "daily_messages": int(stats.get("daily_messages") or 0),
                    "daily_limit": int(stats.get("daily_limit") or 0),
                    "monthly_tokens": int(stats.get("monthly_tokens") or 0),
                    "monthly_limit": int(stats.get("monthly_limit") or 0),
                    "lifetime_messages": int(stats.get("lifetime_messages") or 0),
                    "lifetime_tokens": int(stats.get("lifetime_tokens") or 0),
                },
                "tasks_total": len(user_tasks),
                "active_tasks": len(active_tasks),
                "background_tasks": len(background_tasks),
                "failed_tasks": len(failed_tasks),
                "last_active_at": last_active_at,
                "channels": sorted({str(row.get("channel") or "") for row in user_tasks if str(row.get("channel") or "").strip()}),
                "top_states": sorted({str(row.get("state") or "") for row in user_tasks if str(row.get("state") or "").strip()}),
            })
        users.sort(
            key=lambda row: (
                int(row.get("active_tasks") or 0),
                float(row.get("last_active_at") or 0.0),
                str(row.get("user_id") or ""),
            ),
            reverse=True,
        )
        return users

    def _ops_overview_snapshot(self) -> dict[str, Any]:
        tasks = self._ops_tasks_snapshot()
        users = self._ops_users_snapshot(tasks)
        foreground_active = sum(
            1 for row in tasks
            if row.get("kind") == "foreground" and str(row.get("state") or "").lower() not in {"completed", "failed", "cancelled"}
        )
        background_active = sum(
            1 for row in tasks
            if row.get("kind") == "background" and str(row.get("state") or "").lower() not in {"completed", "failed", "cancelled"}
        )
        by_tier: dict[str, int] = {}
        for user in users:
            tier = str(user.get("tier") or "free")
            by_tier[tier] = int(by_tier.get(tier, 0)) + 1
        try:
            from core.intelligent_planner import get_intelligent_planner

            planner_summary = get_intelligent_planner().get_plan_summary()
        except Exception:
            planner_summary = {}
        return {
            "ok": True,
            "generated_at": time.time(),
            "users_total": len(users),
            "active_users": sum(1 for row in users if int(row.get("active_tasks") or 0) > 0),
            "quota_blocked_users": sum(1 for row in users if not bool((row.get("quota") or {}).get("allowed", True))),
            "tasks_total": len(tasks),
            "foreground_active": foreground_active,
            "background_active": background_active,
            "failed_or_partial": sum(
                1 for row in tasks if str(row.get("state") or "").lower() in {"failed", "partial"}
            ),
            "tiers": by_tier,
            "planner": planner_summary,
        }

    async def handle_admin_overview(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        return web.json_response(self._ops_overview_snapshot())

    async def handle_admin_users(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        tasks = self._ops_tasks_snapshot()
        users = self._ops_users_snapshot(tasks)
        return web.json_response({"ok": True, "users": users, "count": len(users)})

    async def handle_admin_plans(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        user_id = str(request.query.get("user_id", "") or "").strip()
        state = str(request.query.get("state", "") or "").strip().lower()
        try:
            limit = int(request.query.get("limit", 120))
        except Exception:
            limit = 120
        limit = max(1, min(500, limit))
        rows = self._ops_tasks_snapshot()
        if user_id:
            rows = [row for row in rows if str(row.get("user_id") or "") == user_id]
        if state:
            rows = [row for row in rows if str(row.get("state") or "").strip().lower() == state]
        return web.json_response({"ok": True, "plans": rows[:limit], "count": len(rows[:limit])})

    async def handle_admin_user_subscription(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        user_id = str(request.match_info.get("user_id", "") or "").strip()
        if not user_id:
            return web.json_response({"ok": False, "error": "user_id required"}, status=400)
        try:
            data = await request.json()
        except Exception:
            data = {}
        tier_raw = str(data.get("tier") or "").strip().lower()
        if not tier_raw:
            return web.json_response({"ok": False, "error": "tier required"}, status=400)
        try:
            from core.domain.models import SubscriptionTier

            tier = SubscriptionTier(tier_raw)
        except Exception:
            return web.json_response({"ok": False, "error": f"invalid tier: {tier_raw}"}, status=400)
        expiry_days = data.get("expiry_days")
        try:
            expiry_days = int(expiry_days) if expiry_days is not None else None
        except Exception:
            return web.json_response({"ok": False, "error": "expiry_days must be integer"}, status=400)
        subscription_manager.set_user_tier(user_id, tier, expiry_days=expiry_days)
        return web.json_response({
            "ok": True,
            "user": {
                "user_id": user_id,
                **subscription_manager.get_subscription_summary(user_id),
                "quota": quota_manager.get_user_stats(user_id),
            },
        })

    async def handle_admin_away_task_action(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        task_id = str(request.match_info.get("task_id", "") or "").strip()
        if not task_id:
            return web.json_response({"ok": False, "error": "task_id required"}, status=400)
        try:
            data = await request.json()
        except Exception:
            data = {}
        action = str(data.get("action") or "").strip().lower()
        if action not in {"cancel", "requeue"}:
            return web.json_response({"ok": False, "error": "action must be cancel or requeue"}, status=400)
        if action == "cancel":
            record = away_task_registry.cancel(task_id)
        else:
            record = away_task_registry.requeue(task_id)
        if record is None:
            return web.json_response({"ok": False, "error": "task not found"}, status=404)
        push_activity("admin_task_action", "ops", f"{action}:{task_id}", True)
        return web.json_response({"ok": True, "task": self._normalize_background_task(record)})

    # ── Tasks (new) ───────────────────────────────────────────────────────────
    async def handle_tasks(self, request):
        """Return active + recent task history."""
        try:
            from core.pipeline_state import get_pipeline_state
            ps = get_pipeline_state()
            active = ps.list_resume_candidates()
            history = ps._state.get("history", [])[-20:]
        except Exception:
            active, history = [], []
        return web.json_response({"active": active, "history": list(reversed(history))})

    async def handle_task_suggest(self, request):
        """Analyze quick-task text and return automation intent snapshot."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        text = (data.get("text") or "").strip()
        if not text:
            return web.json_response({"ok": False, "error": "text required"}, status=400)
        intent = self._task_intent_snapshot(text)
        return web.json_response({"ok": True, "intent": intent})

    async def handle_file_upload(self, request):
        """POST /api/upload — Multi-modal file drop."""
        try:
            reader = await request.multipart()
            field = await reader.next()
            if not field or field.name != 'file':
                return _json_error("file field required", status=400)

            mime = _normalize_upload_mime(getattr(field, "headers", {}).get("Content-Type", ""))
            if not _is_allowed_upload_mime(mime):
                return _json_error("unsupported file type", status=415, payload={"mime": mime})

            upload_dir = resolve_elyan_data_dir() / "uploads"
            filename, filepath = _build_upload_path(
                upload_dir,
                str(field.filename or f"upload_{int(time.time())}"),
                fallback_prefix="upload",
            )
            size = await _save_upload_field(field, filepath, max_bytes=_UPLOAD_MAX_BYTES)

            logger.info(f"File uploaded via Dashboard: {filename} ({size} bytes)")
            push_activity("upload", "dashboard", f"{filename} ({round(size/1024, 1)} KB)")
            prompt = f"Dropped file: {filepath}. Lütfen bu dosyayı analiz et."
            asyncio.create_task(self.agent.process(prompt))

            return _json_ok({
                "filename": filename,
                "path": str(filepath),
                "size": size,
                "mime": mime,
            })
        except _UploadValidationError as exc:
            return _json_error(str(exc), status=exc.status)
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return _json_error(str(e), status=500)

    async def handle_voice_upload(self, request):
        """POST /api/voice — Voice command upload."""
        try:
            reader = await request.multipart()
            field = await reader.next()
            if not field or field.name != 'file':
                return _json_error("file field required", status=400)

            mime = _normalize_upload_mime(getattr(field, "headers", {}).get("Content-Type", ""))
            if mime not in {"audio/mpeg", "audio/ogg", "audio/wav", "audio/webm"}:
                return _json_error("unsupported voice file type", status=415, payload={"mime": mime})

            temp_dir = resolve_elyan_data_dir() / "tmp" / "voice"
            filename, filepath = _build_upload_path(
                temp_dir,
                str(field.filename or f"voice_{int(time.time())}.webm"),
                fallback_prefix="voice",
            )
            await _save_upload_field(field, filepath, max_bytes=_UPLOAD_MAX_BYTES)

            from core.voice.voice_agent import get_voice_agent
            va = get_voice_agent(self.agent)
            
            result = await va.process_voice_input(str(filepath))
            
            if result.get("success"):
                # Return relative audio path for frontend
                if result.get("response_audio"):
                    result["audio_url"] = f"/api/voice/file?path={os.path.basename(result['response_audio'])}"
                
                push_activity("voice_cmd", "dashboard", result.get("input_text", "")[:60])
                return web.json_response({"ok": True, **result})
            else:
                return web.json_response({"ok": False, "error": result.get("error")}, status=400)
        except _UploadValidationError as exc:
            return _json_error(str(exc), status=exc.status)
        except Exception as e:
            logger.error(f"Voice upload failed: {e}")
            return _json_error(str(e), status=500)

    async def handle_voice_file_get(self, request):
        """GET /api/voice/file?path=filename.mp3 — Serve generated speech."""
        filename = request.query.get("path")
        if not filename:
            return web.Response(status=400, text="path required")
        
        # Security: only allow files from voice tmp dir
        voice_dir = resolve_elyan_data_dir() / "tmp" / "voice"
        safe_path = (voice_dir / filename).resolve()
        
        if not str(safe_path).startswith(str(voice_dir.resolve())):
            return web.Response(status=403, text="Forbidden")
            
        if not safe_path.exists():
            return web.Response(status=404, text="File not found")
            
        return web.FileResponse(safe_path)

    async def handle_evidence_file_get(self, request):
        raw_path = str(request.query.get("path") or "").strip()
        if not raw_path:
            return web.Response(status=400, text="path required")
        safe_path = resolve_evidence_path(raw_path)
        if safe_path is None:
            return web.Response(status=404, text="Evidence not found")
        response = web.FileResponse(safe_path)
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
        return response

    async def handle_create_task(self, request):
        """Create and enqueue a new task."""
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = (data.get("text") or "").strip()
        if not text:
            return web.json_response({"error": "text required"}, status=400)

        intent = self._task_intent_snapshot(text)

        if intent.get("should_auto_create"):
            try:
                suggestion = intent.get("suggestion", {}) if isinstance(intent.get("suggestion"), dict) else {}
                routine = routine_engine.create_from_text(
                    text=text,
                    enabled=True,
                    created_by="quick_task",
                    report_channel=str(data.get("report_channel", "")).strip()
                    or str(suggestion.get("report_channel", "")).strip(),
                    report_chat_id=str(data.get("report_chat_id", "")).strip()
                    or str(suggestion.get("report_chat_id", "")).strip(),
                    expression=str(data.get("expression", "")).strip(),
                    name=str(data.get("name", "")).strip(),
                )
                self.cron.sync_job(self._routine_to_job(routine))
                push_activity("routine_create", "dashboard", f"{routine.get('name')} ({routine.get('id')})", True)
                return web.json_response(
                    {
                        "status": "routine_created",
                        "text": text,
                        "routine": routine,
                        "note": "Zamanlama ifadesi algılandığı için rutin oluşturuldu.",
                        "intent": intent,
                    }
                )
            except Exception as e:
                return web.json_response({"error": f"routine create failed: {e}"}, status=400)

        user_id = str(data.get("user_id") or "local").strip() or "local"
        channel = str(data.get("channel") or "dashboard").strip() or "dashboard"
        mode = str(data.get("mode") or "Balanced").strip() or "Balanced"
        attachments = [str(item) for item in list(data.get("attachments") or []) if str(item).strip()]
        mission = await self._mission_store().create_mission(
            text,
            user_id=user_id,
            channel=channel,
            mode=mode,
            attachments=attachments,
            metadata={"source": "legacy_task_api", "intent": intent},
            agent=self.agent,
            auto_start=True,
        )
        push_activity("task_created", channel, text[:60])
        return web.json_response({
            "ok": True,
            "status": "mission_created",
            "text": text,
            "intent": intent,
            "mission": mission.to_dict(),
        })

    async def handle_missions_overview(self, request):
        user_id = str(request.query.get("user_id", "local") or "local").strip()
        return web.json_response(self._mission_store().overview(owner=user_id))

    async def handle_missions_list(self, request):
        user_id = str(request.query.get("user_id", "local") or "local").strip()
        try:
            limit = int(request.query.get("limit", 30))
        except Exception:
            limit = 30
        return web.json_response({"ok": True, "missions": self._mission_store().list_missions(owner=user_id, limit=limit)})

    async def handle_mission_detail(self, request):
        mission_id = str(request.match_info.get("mission_id", "") or "").strip()
        if not mission_id:
            return web.json_response({"ok": False, "error": "mission_id required"}, status=400)
        mission = self._mission_store().get_mission(mission_id)
        if mission is None:
            return web.json_response({"ok": False, "error": "mission not found"}, status=404)
        return web.json_response({"ok": True, "mission": mission.to_dict()})

    async def handle_missions_create(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        goal = str(data.get("goal") or data.get("text") or "").strip()
        if not goal:
            return web.json_response({"ok": False, "error": "goal required"}, status=400)
        user_id = str(data.get("user_id") or "local").strip() or "local"
        channel = str(data.get("channel") or "dashboard").strip() or "dashboard"
        mode = str(data.get("mode") or "Balanced").strip() or "Balanced"
        attachments = [str(item) for item in list(data.get("attachments") or []) if str(item).strip()]
        mission = await self._mission_store().create_mission(
            goal,
            user_id=user_id,
            channel=channel,
            mode=mode,
            attachments=attachments,
            metadata={"source": "dashboard"},
            agent=self.agent,
            auto_start=True,
        )
        return web.json_response({"ok": True, "mission": mission.to_dict()})

    async def handle_missions_approvals(self, request):
        user_id = str(request.query.get("user_id", "local") or "local").strip()
        return web.json_response({"ok": True, "pending": self._mission_store().pending_approvals(owner=user_id)})

    async def handle_missions_approval_resolve(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        approval_id = str(data.get("id") or data.get("approval_id") or "").strip()
        if not approval_id:
            return web.json_response({"ok": False, "error": "approval id required"}, status=400)
        mission = await self._mission_store().resolve_approval(
            approval_id,
            bool(data.get("approved", False)),
            note=str(data.get("note") or "").strip(),
            agent=self.agent,
        )
        if mission is None:
            return web.json_response({"ok": False, "error": "approval not found"}, status=404)
        return web.json_response({"ok": True, "mission": mission.to_dict()})

    async def handle_missions_skills(self, request):
        return web.json_response({"ok": True, "skills": self._mission_store().list_skills()})

    async def handle_missions_skill_save(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        mission_id = str(data.get("mission_id") or "").strip()
        if not mission_id:
            return web.json_response({"ok": False, "error": "mission_id required"}, status=400)
        recipe = self._mission_store().save_skill(mission_id, name=str(data.get("name") or "").strip())
        if recipe is None:
            return web.json_response({"ok": False, "error": "mission not found"}, status=404)
        return web.json_response({"ok": True, "skill": recipe.to_dict()})

    async def handle_missions_memory(self, request):
        user_id = str(request.query.get("user_id", "local") or "local").strip()
        return web.json_response(self._mission_store().memory_snapshot(user_id=user_id))

    async def handle_packs_overview(self, request):
        pack = normalize_pack(str(request.query.get("pack", "") or "all"))
        path = str(request.query.get("path", "") or "").strip()
        payload = await build_pack_overview(pack=pack, path=path)
        return web.json_response({"ok": True, **payload})

    async def handle_pack_detail(self, request):
        pack = normalize_pack(str(request.match_info.get("pack", "") or ""))
        path = str(request.query.get("path", "") or "").strip()
        payload = await build_pack_overview(pack=pack, path=path)
        if not payload.get("packs"):
            return web.json_response({"ok": False, "error": f"pack not found: {pack}"}, status=404)
        return web.json_response({"ok": True, **payload, "pack": pack})

    # ── Memory stats (new) ────────────────────────────────────────────────────
    async def handle_memory_stats(self, request):
        try:
            from core.memory import get_memory

            memory = get_memory()
            limit = int(request.rel_url.query.get("limit", 5))
            stats = await _fetch_memory_stats(memory)
            top_users = await _fetch_memory_top_users(memory, limit=limit)

            total_items = (
                int(stats.get("conversations", 0))
                + int(stats.get("preferences", 0))
                + int(stats.get("tasks", 0))
                + int(stats.get("knowledge_items", 0))
                + int(stats.get("embeddings", 0))
            )
            size_bytes = int(stats.get("database_size_bytes", 0))
            return web.json_response({
                "total_items": total_items,
                "size_mb": round(size_bytes / (1024**2), 2),
                "size_bytes": size_bytes,
                "db_path": stats.get("database_path"),
                "default_user_limit_bytes": int(stats.get("default_user_limit_bytes", 0)),
                "top_users": top_users,
            })
        except Exception as e:
            logger.debug(f"Memory stats unavailable: {e}")
            return web.json_response({
                "total_items": 0,
                "size_mb": 0.0,
                "size_bytes": 0,
                "top_users": [],
            })

    async def handle_get_profile(self, request):
        """GET /api/memory/profile — Tiered Memory Profile."""
        from core.memory_v2 import memory_v2
        return web.json_response({
            "ok": True,
            "profile": memory_v2.profile.__dict__
        })

    async def handle_memory_recall(self, request):
        allowed, error, session = self._require_user_session(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=401)
        query = str(request.rel_url.query.get("query") or request.rel_url.query.get("q") or "").strip()
        if not query:
            return web.json_response({"ok": False, "error": "query required"}, status=400)
        try:
            limit = max(1, min(20, int(request.rel_url.query.get("limit", 8) or 8)))
        except Exception:
            limit = 8
        from core.runtime.session_store import get_runtime_session_api

        results = get_runtime_session_api().search_history(
            user_id=str(session.get("user_id") or ""),
            query=query,
            limit=limit,
            runtime_metadata=session,
        )
        return web.json_response(
            {
                "ok": True,
                "query": query,
                "count": len(results),
                "results": results,
                "workspace_id": str(session.get("workspace_id") or ""),
                "user_id": str(session.get("user_id") or ""),
            }
        )

    async def handle_memory_history(self, request):
        allowed, error, session = self._require_user_session(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=401)
        try:
            limit = max(1, min(20, int(request.rel_url.query.get("limit", 8) or 8)))
        except Exception:
            limit = 8
        from core.runtime.session_store import get_runtime_session_api

        history = get_runtime_session_api().list_recent_history(
            user_id=str(session.get("user_id") or ""),
            limit=limit,
            runtime_metadata=session,
        )
        return web.json_response(
            {
                "ok": True,
                "count": len(history),
                "history": history,
                "workspace_id": str(session.get("workspace_id") or ""),
                "user_id": str(session.get("user_id") or ""),
            }
        )

    async def handle_learning_drafts(self, request):
        allowed, error, session = self._require_user_session(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=401)
        try:
            limit = max(1, min(20, int(request.rel_url.query.get("limit", 8) or 8)))
        except Exception:
            limit = 8
        draft_type = str(request.rel_url.query.get("type", "all") or "all").strip().lower() or "all"
        from core.runtime.session_store import get_runtime_session_api

        drafts = get_runtime_session_api().list_learning_drafts(
            user_id=str(session.get("user_id") or ""),
            draft_type=draft_type,
            limit=limit,
            runtime_metadata=session,
        )
        return web.json_response(
            {
                "ok": True,
                "workspace_id": str(session.get("workspace_id") or ""),
                "user_id": str(session.get("user_id") or ""),
                **drafts,
            }
        )

    async def handle_health_telemetry(self, request):
        """Aggregate all health and performance metrics for the live dashboard."""
        try:
            from core.model_orchestrator import model_orchestrator
            from core.resilience.circuit_breaker import resilience_manager
            from core.llm.token_budget import token_budget
            from core.automation_registry import automation_registry
            from core.monitoring import get_resource_monitor, get_monitoring
            from core.dependencies import get_system_dependency_runtime
            
            monitor = get_resource_monitor()
            mon = get_monitoring()
            hw = monitor.get_health_snapshot()
            orchestration = mon.get_orchestration_summary()
            pipeline_jobs = mon.get_pipeline_job_summary()
            active_automations = automation_registry.get_active()
            module_health = automation_registry.get_module_health(limit=12)
            system_dependencies = get_system_dependency_runtime().snapshot()
            
            return web.json_response({
                "ok": True,
                "timestamp": time.time(),
                "hardware": {
                    "cpu": hw.cpu_percent,
                    "ram": hw.ram_percent,
                    "disk": hw.disk_percent,
                    "on_ac": hw.is_on_ac
                },
                "resilience": {
                    "providers": model_orchestrator.get_health_report(),
                    "circuits": resilience_manager.get_all_states(),
                    "budget": token_budget.get_usage_summary()
                },
                "automations": {
                    "active_count": len(active_automations),
                    "tasks": active_automations[:10],
                    "module_health": module_health,
                },
                "system_dependencies": system_dependencies,
                "orchestration": orchestration,
                "pipeline_jobs": pipeline_jobs,
                "uptime_s": int(time.time() - _start_time)
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # ── Multi-LLM Engine API ─────────────────────────────────────────────────
    def _get_multi_llm_engine(self):
        try:
            from core.multi_llm_engine import get_multi_llm_engine
            engine = get_multi_llm_engine()
            if not engine._initialized:
                from core.model_orchestrator import model_orchestrator
                engine.initialize(model_orchestrator)
            return engine
        except Exception:
            return None

    async def handle_llm_live_metrics(self, request):
        """GET /api/llm/live — Live metrics for all model slots."""
        engine = self._get_multi_llm_engine()
        if not engine:
            return web.json_response({"ok": False, "error": "engine_unavailable"}, status=500)
        try:
            metrics = engine.get_live_metrics()
            # Merge orchestrator health report
            from core.model_orchestrator import model_orchestrator
            metrics["health_report"] = model_orchestrator.get_health_report()

            # Provider key status for dashboard provider cards
            import os
            key_map = {
                "groq": "GROQ_API_KEY", "google": "GOOGLE_API_KEY",
                "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY", "mistral": "MISTRAL_API_KEY",
                "cohere": "COHERE_API_KEY", "together": "TOGETHER_API_KEY",
                "perplexity": "PERPLEXITY_API_KEY", "xai": "XAI_API_KEY",
            }
            provider_keys = {}
            orch_providers = model_orchestrator.providers or {}
            for prov, env_name in key_map.items():
                has_env = bool(os.environ.get(env_name, ""))
                has_orch = prov in orch_providers and bool(orch_providers[prov].get("apiKey"))
                provider_keys[prov] = {"configured": has_env or has_orch}
            provider_keys["ollama"] = {"configured": True}
            metrics["provider_keys"] = provider_keys

            # Role assignments
            try:
                role_assignments = {}
                for role in ["inference", "code", "reasoning", "creative", "router"]:
                    best = model_orchestrator.get_best_available(role)
                    if best and isinstance(best, dict):
                        role_assignments[role] = {
                            "provider": best.get("provider") or best.get("type") or "-",
                            "model": best.get("model") or "-",
                        }
                fallback = getattr(model_orchestrator, "fallback_config", None)
                if fallback and isinstance(fallback, dict):
                    role_assignments["fallback"] = {
                        "provider": fallback.get("provider") or fallback.get("type") or "-",
                        "model": fallback.get("model") or "-",
                    }
                metrics["role_assignments"] = role_assignments
            except Exception:
                metrics["role_assignments"] = {}

            return web.json_response({"ok": True, **metrics})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_llm_toggle_model(self, request):
        """POST /api/llm/toggle — Enable/disable a model slot."""
        engine = self._get_multi_llm_engine()
        if not engine:
            return web.json_response({"ok": False, "error": "engine_unavailable"}, status=500)
        try:
            body = await request.json()
            slot_id = str(body.get("slot_id", ""))
            enabled = bool(body.get("enabled", True))
            ok = engine.toggle_model(slot_id, enabled)
            return web.json_response({"ok": ok, "slot_id": slot_id, "enabled": enabled})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_llm_set_priority(self, request):
        """POST /api/llm/priority — Set model priority."""
        engine = self._get_multi_llm_engine()
        if not engine:
            return web.json_response({"ok": False, "error": "engine_unavailable"}, status=500)
        try:
            body = await request.json()
            slot_id = str(body.get("slot_id", ""))
            priority = int(body.get("priority", 50))
            ok = engine.set_model_priority(slot_id, priority)
            return web.json_response({"ok": ok, "slot_id": slot_id, "priority": priority})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_llm_reset_circuit(self, request):
        """POST /api/llm/reset-circuit — Reset circuit breaker for a model."""
        engine = self._get_multi_llm_engine()
        if not engine:
            return web.json_response({"ok": False, "error": "engine_unavailable"}, status=500)
        try:
            body = await request.json()
            slot_id = str(body.get("slot_id", ""))
            ok = engine.reset_circuit_breaker(slot_id)
            return web.json_response({"ok": ok, "slot_id": slot_id})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_llm_race(self, request):
        """POST /api/llm/race — Run race mode: same prompt on N models."""
        engine = self._get_multi_llm_engine()
        if not engine:
            return web.json_response({"ok": False, "error": "engine_unavailable"}, status=500)
        try:
            body = await request.json()
            prompt = str(body.get("prompt", "")).strip()
            if not prompt:
                return web.json_response({"ok": False, "error": "prompt required"}, status=400)
            max_models = int(body.get("max_models", 3))
            role = str(body.get("role", "inference"))

            llm_client = getattr(self.agent, "llm", None)
            if llm_client is None:
                self.agent._ensure_llm()
                llm_client = getattr(self.agent, "llm", None)
            if llm_client is None:
                return web.json_response({"ok": False, "error": "llm_client_unavailable"}, status=500)

            result = await engine.race(
                llm_client, prompt, role=role, max_models=max_models
            )

            return web.json_response({
                "ok": True,
                "request_id": result.request_id,
                "winner": {
                    "provider": result.winner.provider,
                    "model": result.winner.model,
                    "latency_ms": round(result.winner.latency_ms, 1),
                    "response_preview": result.winner.response[:300],
                    "tokens": result.winner.tokens_used,
                } if result.winner else None,
                "all_results": [
                    {
                        "provider": r.provider, "model": r.model,
                        "success": r.success, "latency_ms": round(r.latency_ms, 1),
                        "tokens": r.tokens_used,
                        "response_preview": r.response[:200] if r.success else r.error[:200],
                    }
                    for r in result.all_results
                ],
                "total_time_ms": result.total_time_ms,
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_llm_provider_key(self, request):
        """POST /api/llm/provider-key — Save an API key for a provider."""
        try:
            body = await request.json()
            provider = str(body.get("provider", "")).strip().lower()
            api_key = str(body.get("api_key", "")).strip()
            if not provider or not api_key:
                return web.json_response({"ok": False, "error": "provider and api_key required"}, status=400)

            key_map = {
                "groq": "GROQ_API_KEY",
                "google": "GOOGLE_API_KEY",
                "openai": "OPENAI_API_KEY",
                "anthropic": "ANTHROPIC_API_KEY",
                "deepseek": "DEEPSEEK_API_KEY",
                "mistral": "MISTRAL_API_KEY",
                "cohere": "COHERE_API_KEY",
                "together": "TOGETHER_API_KEY",
                "perplexity": "PERPLEXITY_API_KEY",
                "xai": "XAI_API_KEY",
            }
            env_name = key_map.get(provider)
            if not env_name:
                return web.json_response({"ok": False, "error": f"unknown provider: {provider}"}, status=400)

            # Save to environment
            import os
            os.environ[env_name] = api_key

            # Try to save to keychain
            try:
                from security.keychain import keychain_set
                keychain_set(env_name, api_key)
            except Exception:
                pass

            # Notify model orchestrator
            try:
                from core.model_orchestrator import model_orchestrator
                model_orchestrator._provider_keys[provider] = True
            except Exception:
                pass

            return web.json_response({"ok": True, "provider": provider})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_llm_ollama_models(self, request):
        """GET /api/llm/ollama-models — List locally available Ollama models."""
        try:
            import aiohttp
            ollama_url = "http://localhost:11434/api/tags"
            async with aiohttp.ClientSession() as session:
                async with session.get(ollama_url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status != 200:
                        return web.json_response({"ok": False, "error": "ollama not reachable"}, status=502)
                    data = await resp.json()
                    models = []
                    for m in data.get("models", []):
                        name = m.get("name", "")
                        size_bytes = m.get("size", 0)
                        size_str = f"{size_bytes / (1024**3):.1f}GB" if size_bytes > 0 else ""
                        models.append({"name": name, "size": size_str})
                    return web.json_response({"ok": True, "models": models})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_llm_ollama_pull(self, request):
        """POST /api/llm/ollama-pull — Pull an Ollama model."""
        try:
            body = await request.json()
            model = str(body.get("model", "")).strip()
            if not model:
                return web.json_response({"ok": False, "error": "model required"}, status=400)
            import aiohttp
            ollama_url = "http://localhost:11434/api/pull"
            async with aiohttp.ClientSession() as session:
                async with session.post(ollama_url, json={"name": model}, timeout=aiohttp.ClientTimeout(total=300)) as resp:
                    if resp.status != 200:
                        err_text = await resp.text()
                        return web.json_response({"ok": False, "error": f"pull failed: {err_text[:200]}"}, status=502)
                    return web.json_response({"ok": True, "model": model})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # ── Activity log (new) ────────────────────────────────────────────────────
    async def handle_activity_log(self, request):
        return web.json_response({"events": list(reversed(_activity_log))})

    async def handle_recent_runs(self, request):
        """Return recent run summaries from the resolved runs root."""
        global _recent_runs_cache
        try:
            limit = int(request.rel_url.query.get("limit", 10))
        except Exception:
            limit = 10
        limit = max(1, min(50, limit))

        runs_root = resolve_runs_root().expanduser()
        if not runs_root.exists():
            return web.json_response({"runs": [], "count": 0})

        run_stats: list[tuple[Path, float]] = []
        for p in runs_root.iterdir():
            if not p.is_dir():
                continue
            try:
                mtime = float(p.stat().st_mtime)
            except Exception:
                mtime = 0.0
            run_stats.append((p, mtime))
        run_stats.sort(key=lambda row: row[1], reverse=True)
        run_dirs = [row[0] for row in run_stats]
        mtime_by_name = {row[0].name: int(row[1]) for row in run_stats}

        signature = tuple((p.name, mtime_by_name.get(p.name, 0)) for p in run_dirs[:limit])
        now_ts = time.time()
        cache_ttl_s = 6.0
        if (
            _recent_runs_cache.get("signature") == signature
            and int(_recent_runs_cache.get("limit", 0) or 0) >= limit
            and (now_ts - float(_recent_runs_cache.get("ts", 0.0) or 0.0)) <= cache_ttl_s
        ):
            cached = list(_recent_runs_cache.get("items") or [])
            return web.json_response({"runs": cached[:limit], "count": min(limit, len(cached)), "cached": True})

        items = []
        for run_dir in run_dirs[:limit]:
            evidence_path = run_dir / "evidence.json"
            task_path = run_dir / "task.json"
            summary_path = existing_text_path(run_dir / "summary.txt")
            status = "unknown"
            action = ""
            error_code = ""
            duration_ms = 0
            artifacts = 0
            claim_coverage = 0.0
            critical_claim_coverage = 0.0
            uncertainty_count = 0
            conflict_count = 0
            manual_review_claim_count = 0
            quality_status = ""
            claim_map_path = ""
            revision_summary_path = ""
            team_quality_avg = 0.0
            team_research_claim_coverage = 0.0
            team_research_critical_claim_coverage = 0.0
            team_research_uncertainty_count = 0
            workflow_profile = ""
            workflow_phase = ""
            execution_route = ""
            autonomy_mode = ""
            autonomy_policy = ""
            orchestration_decision_path = []
            approval_status = ""
            plan_progress = ""
            review_status = ""
            workspace_mode = ""
            design_artifact_path = ""
            plan_artifact_path = ""
            review_artifact_path = ""
            finish_branch_report_path = ""
            team_parallel_waves = 0
            team_max_wave_size = 0
            team_parallelizable_packets = 0
            team_serial_packets = 0
            team_ownership_conflicts = 0

            if evidence_path.exists():
                try:
                    ev = json.loads(evidence_path.read_text(encoding="utf-8"))
                    meta = ev.get("metadata", {}) if isinstance(ev, dict) else {}
                    if isinstance(meta, dict):
                        status = str(meta.get("status", status) or status)
                        error_code = str(meta.get("error_code", "") or "")
                        if not error_code:
                            errors = meta.get("errors", [])
                            if isinstance(errors, list):
                                for err in errors:
                                    if isinstance(err, dict):
                                        code = str(err.get("error_code", "") or err.get("code", "")).strip()
                                        if code:
                                            error_code = code
                                            break
                                        text = str(err.get("error", "") or err.get("message", "")).strip()
                                        if text and "error_code" in text.lower():
                                            error_code = text
                                            break
                                    else:
                                        err_s = str(err or "").strip()
                                        if "error_code" in err_s.lower():
                                            error_code = err_s
                                            break
                        if "duration_ms" in meta:
                            try:
                                duration_ms = int(meta.get("duration_ms", 0) or 0)
                            except Exception:
                                duration_ms = 0
                        try:
                            claim_coverage = float(meta.get("claim_coverage", 0.0) or 0.0)
                        except Exception:
                            claim_coverage = 0.0
                        try:
                            critical_claim_coverage = float(meta.get("critical_claim_coverage", 0.0) or 0.0)
                        except Exception:
                            critical_claim_coverage = 0.0
                        try:
                            uncertainty_count = int(meta.get("uncertainty_count", 0) or 0)
                        except Exception:
                            uncertainty_count = 0
                        try:
                            conflict_count = int(meta.get("conflict_count", 0) or 0)
                        except Exception:
                            conflict_count = 0
                        try:
                            manual_review_claim_count = int(meta.get("manual_review_claim_count", 0) or 0)
                        except Exception:
                            manual_review_claim_count = 0
                        quality_status = str(meta.get("quality_status", "") or "")
                        claim_map_path = str(meta.get("claim_map_path", "") or "")
                        revision_summary_path = str(meta.get("revision_summary_path", "") or "")
                        execution_route = str(meta.get("execution_route", "") or "")
                        autonomy_mode = str(meta.get("autonomy_mode", "") or "")
                        autonomy_policy = str(meta.get("autonomy_policy", "") or "")
                        orchestration_decision_path = list(meta.get("orchestration_decision_path") or []) if isinstance(meta.get("orchestration_decision_path"), list) else []
                        try:
                            team_quality_avg = float(meta.get("team_quality_avg", 0.0) or 0.0)
                        except Exception:
                            team_quality_avg = 0.0
                        try:
                            team_parallel_waves = int(meta.get("team_parallel_waves", 0) or 0)
                        except Exception:
                            team_parallel_waves = 0
                        try:
                            team_max_wave_size = int(meta.get("team_max_wave_size", 0) or 0)
                        except Exception:
                            team_max_wave_size = 0
                        try:
                            team_parallelizable_packets = int(meta.get("team_parallelizable_packets", 0) or 0)
                        except Exception:
                            team_parallelizable_packets = 0
                        try:
                            team_serial_packets = int(meta.get("team_serial_packets", 0) or 0)
                        except Exception:
                            team_serial_packets = 0
                        try:
                            team_ownership_conflicts = int(meta.get("team_ownership_conflicts", 0) or 0)
                        except Exception:
                            team_ownership_conflicts = 0
                        try:
                            team_research_claim_coverage = float(meta.get("team_research_claim_coverage", 0.0) or 0.0)
                        except Exception:
                            team_research_claim_coverage = 0.0
                        try:
                            team_research_critical_claim_coverage = float(meta.get("team_research_critical_claim_coverage", 0.0) or 0.0)
                        except Exception:
                            team_research_critical_claim_coverage = 0.0
                        try:
                            team_research_uncertainty_count = int(meta.get("team_research_uncertainty_count", 0) or 0)
                        except Exception:
                            team_research_uncertainty_count = 0
                        workflow_profile = str(meta.get("workflow_profile", "") or "")
                        workflow_phase = str(meta.get("workflow_phase", "") or "")
                        approval_status = str(meta.get("approval_status", "") or "")
                        plan_progress = str(meta.get("plan_progress", "") or "")
                        review_status = str(meta.get("review_status", "") or "")
                        workspace_mode = str(meta.get("workspace_mode", "") or "")
                        design_artifact_path = str(meta.get("design_artifact_path", "") or "")
                        plan_artifact_path = str(meta.get("plan_artifact_path", "") or "")
                        review_artifact_path = str(meta.get("review_artifact_path", "") or "")
                        finish_branch_report_path = str(meta.get("finish_branch_report_path", "") or "")
                    steps = ev.get("steps", []) if isinstance(ev, dict) else []
                    if isinstance(steps, list):
                        total_step_duration = 0
                        for step in steps:
                            if isinstance(step, dict):
                                try:
                                    total_step_duration += int(step.get("duration_ms", 0) or 0)
                                except Exception:
                                    continue
                        if not duration_ms:
                            duration_ms = total_step_duration
                    arts = ev.get("artifacts", []) if isinstance(ev, dict) else []
                    artifacts = len(arts) if isinstance(arts, list) else 0
                except Exception:
                    pass

            if task_path.exists():
                try:
                    task = json.loads(task_path.read_text(encoding="utf-8"))
                    meta = task.get("metadata", {}) if isinstance(task, dict) else {}
                    if isinstance(meta, dict):
                        action = str(meta.get("action", "") or "")
                        workflow_profile = workflow_profile or str(meta.get("workflow_profile", "") or "")
                        workflow_phase = workflow_phase or str(meta.get("workflow_phase", "") or "")
                        execution_route = execution_route or str(meta.get("execution_route", "") or "")
                        autonomy_mode = autonomy_mode or str(meta.get("autonomy_mode", "") or "")
                        autonomy_policy = autonomy_policy or str(meta.get("autonomy_policy", "") or "")
                        if not orchestration_decision_path and isinstance(meta.get("orchestration_decision_path"), list):
                            orchestration_decision_path = list(meta.get("orchestration_decision_path") or [])
                        approval_status = approval_status or str(meta.get("approval_status", "") or "")
                        plan_progress = plan_progress or str(meta.get("plan_progress", "") or "")
                        review_status = review_status or str(meta.get("review_status", "") or "")
                        workspace_mode = workspace_mode or str(meta.get("workspace_mode", "") or "")
                        design_artifact_path = design_artifact_path or str(meta.get("design_artifact_path", "") or "")
                        plan_artifact_path = plan_artifact_path or str(meta.get("plan_artifact_path", "") or "")
                        review_artifact_path = review_artifact_path or str(meta.get("review_artifact_path", "") or "")
                        finish_branch_report_path = finish_branch_report_path or str(meta.get("finish_branch_report_path", "") or "")
                except Exception:
                    pass

            items.append(
                {
                    "run_id": run_dir.name,
                    "status": status,
                    "action": action,
                    "duration_ms": duration_ms,
                    "error_code": error_code,
                    "artifacts": artifacts,
                    "claim_coverage": round(claim_coverage, 2),
                    "critical_claim_coverage": round(critical_claim_coverage, 2),
                    "uncertainty_count": uncertainty_count,
                    "conflict_count": conflict_count,
                    "manual_review_claim_count": manual_review_claim_count,
                    "quality_status": quality_status,
                    "claim_map_path": claim_map_path,
                    "revision_summary_path": revision_summary_path,
                    "team_quality_avg": round(team_quality_avg, 2),
                    "team_research_claim_coverage": round(team_research_claim_coverage, 2),
                    "team_research_critical_claim_coverage": round(team_research_critical_claim_coverage, 2),
                    "team_research_uncertainty_count": team_research_uncertainty_count,
                    "workflow_profile": workflow_profile,
                    "workflow_phase": workflow_phase,
                    "execution_route": execution_route,
                    "autonomy_mode": autonomy_mode,
                    "autonomy_policy": autonomy_policy,
                    "orchestration_decision_path": orchestration_decision_path,
                    "approval_status": approval_status,
                    "plan_progress": plan_progress,
                    "review_status": review_status,
                    "workspace_mode": workspace_mode,
                    "design_artifact_path": design_artifact_path,
                    "plan_artifact_path": plan_artifact_path,
                    "review_artifact_path": review_artifact_path,
                    "finish_branch_report_path": finish_branch_report_path,
                    "team_parallel_waves": team_parallel_waves,
                    "team_max_wave_size": team_max_wave_size,
                    "team_parallelizable_packets": team_parallelizable_packets,
                    "team_serial_packets": team_serial_packets,
                    "team_ownership_conflicts": team_ownership_conflicts,
                    "summary_path": str(summary_path),
                    "evidence_path": str(evidence_path),
                    "created_at": int(mtime_by_name.get(run_dir.name, 0)),
                }
            )

        _recent_runs_cache = {
            "ts": now_ts,
            "signature": signature,
            "limit": limit,
            "items": list(items),
        }
        return web.json_response({"runs": items, "count": len(items)})

    # ── Routine automation (new) ────────────────────────────────────────────
    @staticmethod
    def _routine_job_id(routine_id: str) -> str:
        return f"routine:{routine_id}"

    @staticmethod
    def _resolve_routine_id_api(raw_id: str) -> tuple[str | None, str | None]:
        rid = str(raw_id or "").strip()
        if not rid:
            return None, "id required"
        matches = routine_engine.match_routine_ids(rid)
        if not matches:
            return None, "routine not found"
        if len(matches) > 1:
            return None, f"ambiguous id prefix ({len(matches)} matches)"
        return matches[0], None

    @staticmethod
    def _looks_like_automation_request(text: str) -> bool:
        intent = ElyanGatewayServer._task_intent_snapshot(text)
        return bool(intent.get("should_auto_create"))

    @staticmethod
    def _task_intent_snapshot(text: str) -> dict:
        raw = str(text or "").strip()
        low = raw.lower()
        if not low:
            return {
                "text": raw,
                "has_schedule": False,
                "has_action": False,
                "automation_score": 0.0,
                "should_auto_create": False,
                "suggestion": {},
            }

        schedule_markers = (
            "her gün",
            "hergun",
            "günlük",
            "gunluk",
            "daily",
            "hafta içi",
            "haftaici",
            "hafta sonu",
            "haftasonu",
            "haftalık",
            "haftalik",
            "weekly",
            "saat",
            "cron",
            "dakikada bir",
            "saatte bir",
            "her ay",
            "ayda bir",
            "her pazartesi",
            "her salı",
            "her sali",
            "her çarşamba",
            "her carsamba",
            "her perşembe",
            "her persembe",
            "her cuma",
            "her cumartesi",
            "her pazar",
        )
        action_markers = (
            "rutin",
            "otomasyon",
            "kontrol et",
            "rapor",
            "gönder",
            "gonder",
            "panel",
            "tarayıcı",
            "tarayici",
            "sipariş",
            "siparis",
            "stok",
            "mail",
            "e-posta",
            "excel",
            "tablo",
            "muhasebe",
            "öğrenci",
            "ogrenci",
            "hatırlat",
            "hatirlat",
            "anımsat",
            "animsat",
            "uyar",
            "bildir",
            "takip et",
        )

        has_schedule_marker = any(m in low for m in schedule_markers)
        has_action_marker = any(m in low for m in action_markers)

        suggestion: dict = {}
        schedule_from_parser = False
        confidence = 0.0
        try:
            suggestion = routine_engine.suggest_from_text(raw)
            expr = str(suggestion.get("expression", "")).strip()
            schedule_from_parser = bool(expr and expr != "0 9 * * *")
            confidence = coerce_confidence(suggestion.get("confidence", 0.0), 0.0)
        except Exception:
            suggestion = {}

        has_schedule = bool(has_schedule_marker or schedule_from_parser)
        has_action = bool(has_action_marker or str(suggestion.get("template_id", "")).strip())

        score = 0.0
        if has_schedule_marker:
            score += 0.45
        if schedule_from_parser:
            score += 0.2
        if has_action_marker:
            score += 0.35
        if str(suggestion.get("template_id", "")).strip():
            score += 0.1
        if confidence >= 0.7:
            score += 0.05
        score = min(1.0, score)

        should_auto = bool(has_schedule and has_action and score >= 0.6)

        return {
            "text": raw,
            "has_schedule": has_schedule,
            "has_action": has_action,
            "automation_score": round(score, 2),
            "should_auto_create": should_auto,
            "suggestion": suggestion,
        }

    def _routine_to_job(self, routine: dict) -> dict:
        rid = str(routine.get("id", "")).strip()
        return {
            "id": self._routine_job_id(rid),
            "expression": str(routine.get("expression", "")).strip(),
            "enabled": bool(routine.get("enabled", True)),
            "job_type": "routine",
            "routine_id": rid,
            "name": routine.get("name", f"routine-{rid}"),
            "channel": routine.get("report_channel", "telegram"),
            "channel_id": routine.get("report_chat_id", ""),
            "source": "runtime",
        }

    def _sync_all_routines_to_cron(self) -> None:
        routines = routine_engine.list_routines()
        active_ids = set()
        for routine in routines:
            rid = str(routine.get("id", "")).strip()
            if not rid:
                continue
            job_id = self._routine_job_id(rid)
            try:
                self.cron.sync_job(self._routine_to_job(routine))
                active_ids.add(job_id)
            except Exception as exc:
                logger.warning(f"Routine cron sync skipped for {rid}: {exc}")

        # Cleanup deleted routines from cron runtime jobs.
        for job in self.cron.list_jobs():
            jid = str(job.get("id", "")).strip()
            if jid.startswith("routine:") and jid not in active_ids:
                try:
                    self.cron.remove_job(jid)
                except Exception as exc:
                    logger.warning(f"Routine cron cleanup skipped for {jid}: {exc}")

    async def _on_cron_report(self, job: dict, success: bool, report: str) -> None:
        channel = str(job.get("channel", "")).strip().lower()
        chat_id = str(job.get("channel_id", "")).strip()
        job_name = str(job.get("name") or job.get("id") or "job")
        if not report:
            report = f"{job_name} tamamlandı ({'başarılı' if success else 'hatalı'})."
        # Keep channel payload compact to avoid adapter-side message limits.
        if len(report) > 3500:
            report = report[:3500] + "\n...\n[rapor kısaltıldı]"
        report = (
            f"Rutin: {job_name}\n"
            f"Durum: {'SUCCESS' if success else 'FAILED'}\n\n"
            f"{report}"
        )

        if channel and chat_id and channel in self.router.adapters:
            try:
                await self.router.send_outgoing_response(
                    channel,
                    chat_id,
                    UnifiedResponse(text=report, format="plain"),
                )
                push_activity("routine_report", channel, f"{job_name} -> delivered", success=success)
                return
            except Exception as e:
                logger.warning(f"Routine report delivery failed ({channel}/{chat_id}): {e}")

        push_activity("routine_report", "dashboard", f"{job_name} -> local log", success=success)

    async def handle_routines(self, request):
        routines = routine_engine.list_routines()
        out = []
        enabled_count = 0
        for r in routines:
            rid = str(r.get("id", "")).strip()
            if not rid:
                continue
            enabled = bool(r.get("enabled", True))
            enabled_count += 1 if enabled else 0
            item = dict(r)
            try:
                aps_job = self.cron.scheduler.get_job(self._routine_job_id(rid))
                item["next_run"] = aps_job.next_run_time.isoformat() if aps_job and aps_job.next_run_time else None
            except Exception:
                item["next_run"] = None
            out.append(item)
        templates = routine_engine.list_templates()
        return web.json_response({
            "routines": out,
            "templates": templates,
            "summary": {
                "total": len(out),
                "enabled": enabled_count,
                "disabled": len(out) - enabled_count,
                "templates": len(templates),
            },
        })

    async def handle_routine_templates(self, request):
        templates = routine_engine.list_templates()
        return web.json_response({"ok": True, "templates": templates})

    async def handle_routine_suggest(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        text = str(data.get("text", "")).strip()
        if not text:
            return web.json_response({"ok": False, "error": "text required"}, status=400)
        try:
            suggestion = routine_engine.suggest_from_text(text)
            return web.json_response({"ok": True, "suggestion": suggestion})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_from_text(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        text = str(data.get("text", "")).strip()
        if not text:
            return web.json_response({"ok": False, "error": "text required"}, status=400)

        try:
            routine = routine_engine.create_from_text(
                text=text,
                enabled=bool(data.get("enabled", True)),
                created_by=str(data.get("created_by", "dashboard-nl") or "dashboard-nl"),
                report_chat_id=str(data.get("report_chat_id", "")).strip(),
                report_channel=str(data.get("report_channel", "")).strip(),
                expression=str(data.get("expression", "")).strip(),
                name=str(data.get("name", "")).strip(),
                panels=data.get("panels", []),
                tags=data.get("tags", []) if isinstance(data.get("tags"), list) else [],
            )
            self.cron.sync_job(self._routine_to_job(routine))
            push_activity("routine_nl_create", "dashboard", f"{routine.get('name')} ({routine.get('id')})", True)
            return web.json_response({"ok": True, "routine": routine})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_from_draft(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        draft_id = str(data.get("draft_id", "")).strip()
        if not draft_id:
            return web.json_response({"ok": False, "error": "draft_id required"}, status=400)

        runtime_db = get_runtime_database()
        user_ref = str(data.get("user_id", "") or data.get("user", "")).strip()
        workspace_id = str(data.get("workspace_id", "")).strip()
        session = runtime_db.auth_sessions.get_latest_session(user_ref=user_ref, workspace_id=workspace_id)
        if not session:
            return web.json_response({"ok": False, "error": "active local session required"}, status=403)

        from core.runtime.session_store import get_runtime_session_api

        try:
            promoted = get_runtime_session_api().promote_routine_draft(
                user_id=str(session.get("user_id") or ""),
                draft_id=draft_id,
                runtime_metadata={
                    "workspace_id": str(session.get("workspace_id") or "local-workspace"),
                    "user_id": str(session.get("user_id") or ""),
                    "channel": str((session.get("metadata") or {}).get("client") or "desktop"),
                    "session_id": str(session.get("session_id") or ""),
                },
                enabled=bool(data.get("enabled", True)),
                name=str(data.get("name", "")).strip(),
                expression=str(data.get("expression", "")).strip(),
                report_channel=str(data.get("report_channel", "")).strip(),
                report_chat_id=str(data.get("report_chat_id", "")).strip(),
            )
            routine = dict(promoted.get("routine") or {})
            if routine:
                self.cron.sync_job(self._routine_to_job(routine))
            push_activity("routine_draft_promote", "dashboard", f"{draft_id} -> {routine.get('id', '?')}", True)
            return web.json_response({"ok": True, **promoted})
        except KeyError:
            return web.json_response({"ok": False, "error": "routine draft not found"}, status=404)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_skill_from_draft(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        draft_id = str(data.get("draft_id", "")).strip()
        if not draft_id:
            return web.json_response({"ok": False, "error": "draft_id required"}, status=400)

        runtime_db = get_runtime_database()
        user_ref = str(data.get("user_id", "") or data.get("user", "")).strip()
        workspace_id = str(data.get("workspace_id", "")).strip()
        session = runtime_db.auth_sessions.get_latest_session(user_ref=user_ref, workspace_id=workspace_id)
        if not session:
            return web.json_response({"ok": False, "error": "active local session required"}, status=403)

        from core.runtime.session_store import get_runtime_session_api

        try:
            promoted = get_runtime_session_api().promote_skill_draft(
                user_id=str(session.get("user_id") or ""),
                draft_id=draft_id,
                runtime_metadata={
                    "workspace_id": str(session.get("workspace_id") or "local-workspace"),
                    "user_id": str(session.get("user_id") or ""),
                    "channel": str((session.get("metadata") or {}).get("client") or "desktop"),
                    "session_id": str(session.get("session_id") or ""),
                },
                name=str(data.get("name", "")).strip(),
                description=str(data.get("description", "")).strip(),
                enabled=bool(data.get("enabled", True)),
            )
            push_activity("skill_draft_promote", "dashboard", f"{draft_id} -> {promoted.get('skill', {}).get('name', '?')}", True)
            return web.json_response({"ok": True, **promoted})
        except KeyError:
            return web.json_response({"ok": False, "error": "skill draft not found"}, status=404)
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_create(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        name = str(data.get("name", "")).strip()
        expression = str(data.get("expression", "")).strip()
        steps = data.get("steps", [])
        report_channel = str(data.get("report_channel", "telegram")).strip().lower() or "telegram"
        report_chat_id = str(data.get("report_chat_id", "")).strip()
        enabled = bool(data.get("enabled", True))
        created_by = str(data.get("created_by", "dashboard")).strip() or "dashboard"
        panels = data.get("panels", [])
        template_id = str(data.get("template_id", "")).strip()

        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        if not expression:
            return web.json_response({"ok": False, "error": "expression required"}, status=400)
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(expression)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"invalid cron expression: {e}"}, status=400)

        try:
            routine = routine_engine.add_routine(
                name=name,
                expression=expression,
                steps=steps,
                report_channel=report_channel,
                report_chat_id=report_chat_id,
                enabled=enabled,
                created_by=created_by,
                tags=data.get("tags", []) if isinstance(data.get("tags"), list) else [],
                panels=panels,
                template_id=template_id,
            )
            self.cron.sync_job(self._routine_to_job(routine))
            push_activity("routine_create", "dashboard", f"{routine['name']} ({routine['id']})", True)
            return web.json_response({"ok": True, "routine": routine})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_from_template(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        template_id = str(data.get("template_id", "")).strip()
        expression = str(data.get("expression", "")).strip()
        name = str(data.get("name", "")).strip()
        report_channel = str(data.get("report_channel", "telegram")).strip().lower() or "telegram"
        report_chat_id = str(data.get("report_chat_id", "")).strip()
        created_by = str(data.get("created_by", "dashboard")).strip() or "dashboard"
        enabled = bool(data.get("enabled", True))
        panels = data.get("panels", [])
        tags = data.get("tags", []) if isinstance(data.get("tags"), list) else []

        if not template_id:
            return web.json_response({"ok": False, "error": "template_id required"}, status=400)
        if not expression:
            return web.json_response({"ok": False, "error": "expression required"}, status=400)
        try:
            from apscheduler.triggers.cron import CronTrigger
            CronTrigger.from_crontab(expression)
        except Exception as e:
            return web.json_response({"ok": False, "error": f"invalid cron expression: {e}"}, status=400)

        try:
            routine = routine_engine.create_from_template(
                template_id=template_id,
                expression=expression,
                report_channel=report_channel,
                report_chat_id=report_chat_id,
                enabled=enabled,
                created_by=created_by,
                name=name,
                panels=panels,
                tags=tags,
            )
            self.cron.sync_job(self._routine_to_job(routine))
            push_activity("routine_template", "dashboard", f"{template_id} -> {routine['id']}", True)
            return web.json_response({"ok": True, "routine": routine})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_routine_toggle(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        rid_raw = str(data.get("id", "")).strip()
        enabled = bool(data.get("enabled", True))
        rid, err = self._resolve_routine_id_api(rid_raw)
        if err:
            status = 400 if "id required" in err else 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)

        routine = routine_engine.set_enabled(rid, enabled)
        if not routine:
            return web.json_response({"ok": False, "error": "routine not found"}, status=404)
        if enabled:
            self.cron.sync_job(self._routine_to_job(routine))
        else:
            self.cron.disable_job(self._routine_job_id(rid))
        push_activity("routine_toggle", "dashboard", f"{rid} -> {'on' if enabled else 'off'}", True)
        return web.json_response({"ok": True, "routine": routine})

    async def handle_routine_run(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        rid_raw = str(data.get("id", "")).strip()
        rid, err = self._resolve_routine_id_api(rid_raw)
        if err:
            status = 400 if "id required" in err else 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)

        job_id = self._routine_job_id(rid)
        if not self.cron.get_job(job_id):
            routine = routine_engine.get_routine(rid)
            if not routine:
                return web.json_response({"ok": False, "error": "routine not found"}, status=404)
            self.cron.sync_job(self._routine_to_job(routine))

        result = await self.cron.run_job(job_id)
        push_activity("routine_run", "dashboard", f"{rid} -> {'ok' if result.get('success') else 'fail'}", bool(result.get("success")))
        return web.json_response({"ok": True, "result": result})

    async def handle_routine_history(self, request):
        rid = str(request.rel_url.query.get("id", "")).strip()
        if not rid:
            # lightweight global snapshot
            items = []
            for routine in routine_engine.list_routines():
                r_id = str(routine.get("id", "")).strip()
                if not r_id:
                    continue
                hist = routine_engine.get_history(r_id, limit=5)
                if hist:
                    items.append({"id": r_id, "name": routine.get("name"), "history": hist})
            return web.json_response({"items": items})

        resolved_id, err = self._resolve_routine_id_api(rid)
        if err:
            status = 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)
        history = routine_engine.get_history(resolved_id, limit=int(request.rel_url.query.get("limit", 20)))
        return web.json_response({"id": resolved_id, "history": history})

    async def handle_routine_remove(self, request):
        rid_raw = str(request.match_info.get("id", "")).strip()
        rid, err = self._resolve_routine_id_api(rid_raw)
        if err:
            status = 400 if "id required" in err else 404 if "not found" in err else 409
            return web.json_response({"ok": False, "error": err}, status=status)
        ok = routine_engine.remove_routine(rid)
        if not ok:
            return web.json_response({"ok": False, "error": "routine not found"}, status=404)
        self.cron.remove_job(self._routine_job_id(rid))
        push_activity("routine_remove", "dashboard", rid, True)
        return web.json_response({"ok": True})

    @staticmethod
    def _module_automation_snapshot(*, include_inactive: bool = True, limit: int = 100) -> dict[str, Any]:
        from core.automation_registry import automation_registry

        health = automation_registry.get_module_health(limit=max(1, min(100, int(limit or 100))))
        tasks = automation_registry.list_module_tasks(
            include_inactive=bool(include_inactive),
            limit=max(1, min(200, int(limit or 100) * 2)),
        )
        summary = health.get("summary") if isinstance(health, dict) else {}
        if tasks:
            summary = {
                "active_modules": sum(1 for row in tasks if str(row.get("status") or "").strip().lower() == "active"),
                "healthy": sum(1 for row in tasks if str(row.get("health") or "").strip().lower() == "healthy"),
                "failing": sum(1 for row in tasks if str(row.get("health") or "").strip().lower() == "failing"),
                "unknown": sum(1 for row in tasks if str(row.get("health") or "").strip().lower() == "unknown"),
                "circuit_open": sum(1 for row in tasks if str(row.get("health") or "").strip().lower() == "circuit_open"),
                "paused": sum(1 for row in tasks if str(row.get("status") or "").strip().lower() in {"paused", "disabled"}),
            }
        return {
            "summary": summary,
            "health_rows": health.get("modules") if isinstance(health, dict) else [],
            "tasks": tasks,
        }

    async def handle_module_automations(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)

        include_inactive = str(request.rel_url.query.get("include_inactive", "1")).strip().lower() not in {"0", "false", "no"}
        try:
            limit = int(request.rel_url.query.get("limit", 100))
        except Exception:
            limit = 100
        snapshot = self._module_automation_snapshot(include_inactive=include_inactive, limit=limit)
        return web.json_response({"ok": True, **snapshot})

    async def handle_module_automations_action(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        action = str(data.get("action") or "").strip().lower()
        task_id = str(data.get("task_id") or "").strip()
        raw_ids = data.get("task_ids", [])
        task_ids: list[str] = []
        if isinstance(raw_ids, list):
            task_ids = [str(item).strip() for item in raw_ids if str(item).strip()]
        if task_id:
            task_ids.insert(0, task_id)
        # Preserve order while deduplicating.
        unique_ids: list[str] = []
        seen_ids: set[str] = set()
        for rid in task_ids:
            if rid not in seen_ids:
                seen_ids.add(rid)
                unique_ids.append(rid)
        task_ids = unique_ids
        if action not in {"run_now", "pause", "resume", "remove"}:
            return web.json_response({"ok": False, "error": "invalid action"}, status=400)
        if not task_ids:
            return web.json_response({"ok": False, "error": "task_id required"}, status=400)

        from core.automation_registry import automation_registry

        try:
            results: list[dict[str, Any]] = []
            for rid in task_ids:
                if action == "run_now":
                    result = await automation_registry.run_task_now(rid, agent=self.agent)
                    ok = bool(result.get("success"))
                    results.append({"task_id": rid, "ok": ok, "status": str(result.get("status") or ""), "result": result})
                    push_activity("module_run_now", "dashboard", f"{rid} -> {result.get('status')}", ok)
                    continue

                if action == "pause":
                    changed = automation_registry.set_status(rid, "paused")
                    results.append({"task_id": rid, "ok": bool(changed), "status": "paused" if changed else "not_found"})
                    if changed:
                        push_activity("module_pause", "dashboard", rid, True)
                    continue
                if action == "resume":
                    changed = automation_registry.set_status(rid, "active")
                    results.append({"task_id": rid, "ok": bool(changed), "status": "active" if changed else "not_found"})
                    if changed:
                        push_activity("module_resume", "dashboard", rid, True)
                    continue

                changed = automation_registry.unregister(rid)
                results.append({"task_id": rid, "ok": bool(changed), "status": "removed" if changed else "not_found"})
                if changed:
                    push_activity("module_remove", "dashboard", rid, True)

            success_count = sum(1 for item in results if bool(item.get("ok")))
            if success_count <= 0:
                return web.json_response(
                    {
                        "ok": False,
                        "error": "task not found",
                        "action": action,
                        "results": results,
                        **self._module_automation_snapshot(include_inactive=True, limit=100),
                    },
                    status=404,
                )
            snapshot = self._module_automation_snapshot(include_inactive=True, limit=100)
            response_payload = {
                "ok": success_count == len(results),
                "action": action,
                "requested": len(results),
                "succeeded": success_count,
                "failed": len(results) - success_count,
                "results": results,
                "result": results[0] if len(results) == 1 else {"count": len(results)},
                **snapshot,
            }
            return web.json_response(response_payload)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_module_automations_update(self, request):
        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        task_id = str(data.get("task_id") or "").strip()
        if not task_id:
            return web.json_response({"ok": False, "error": "task_id required"}, status=400)

        raw_params = data.get("params")
        params: dict[str, Any] | None = raw_params if isinstance(raw_params, dict) else None
        workspace = str(data.get("workspace") or "").strip()
        if workspace:
            params = dict(params or {})
            params.setdefault("workspace", workspace)

        from core.automation_registry import automation_registry

        updated = automation_registry.update_module_task(
            task_id,
            interval_seconds=data.get("interval_seconds", data.get("interval")),
            timeout_seconds=data.get("timeout_seconds", data.get("timeout")),
            max_retries=data.get("max_retries", data.get("retries")),
            retry_backoff_seconds=data.get("retry_backoff_seconds", data.get("backoff")),
            circuit_breaker_threshold=data.get("circuit_breaker_threshold", data.get("circuit_threshold")),
            circuit_breaker_cooldown_seconds=data.get(
                "circuit_breaker_cooldown_seconds", data.get("circuit_cooldown")
            ),
            params=params,
            channel=data.get("channel"),
            status=data.get("status"),
        )
        if not updated:
            return web.json_response({"ok": False, "error": "task not found"}, status=404)

        snapshot = self._module_automation_snapshot(include_inactive=True, limit=100)
        return web.json_response({"ok": True, "task": updated, **snapshot})

    # ── Tools management (new) ───────────────────────────────────────────────
    @staticmethod
    def _tool_probe_params(tool_name: str) -> dict | None:
        """Return safe probe parameters for selected tools."""
        probe_dir = resolve_elyan_data_dir() / "tmp"
        probe_dir.mkdir(parents=True, exist_ok=True)
        probe_file = probe_dir / "tool_probe.txt"
        if not probe_file.exists():
            probe_file.write_text("elyan tool probe\n", encoding="utf-8")

        mapping = {
            "get_system_info": {},
            "get_running_apps": {},
            "get_process_info": {"process_name": "python", "limit": 5},
            "list_files": {"path": "~/Desktop"},
            "search_files": {"pattern": "*.txt", "directory": "~/Desktop"},
            "read_file": {"path": str(probe_file)},
            "write_file": {"path": str(probe_file), "content": "elyan tool probe\n"},
            "write_word": {"path": str(probe_dir / "tool_probe.docx"), "content": "elyan tool probe"},
            "write_excel": {"path": str(probe_dir / "tool_probe.xlsx"), "data": [{"Veri": "elyan tool probe"}], "headers": ["Veri"]},
            "wifi_status": {},
            "get_public_ip": {},
            "get_today_events": {},
            "get_reminders": {},
        }
        return mapping.get(str(tool_name or "").strip())

    @staticmethod
    def _required_params_for_callable(func) -> list[str]:
        if not callable(func):
            return []
        try:
            sig = inspect.signature(func)
        except Exception:
            return []
        required = []
        for pname, p in sig.parameters.items():
            if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
                continue
            if p.default is inspect.Parameter.empty:
                required.append(pname)
        return required

    async def _compute_tool_health(self, tool_names: list[str], probe: bool = False) -> tuple[dict, dict]:
        """
        Build tool health map:
        - broken: tool is not callable
        - ready: callable and no required params
        - needs_params: callable but requires args
        Optional probe executes a safe smoke test for selected tools.
        """
        from tools import get_tool_load_errors

        global _tool_health_cache
        now = time.time()
        ttl = 45 if probe else 20
        if (
            _tool_health_cache.get("items")
            and _tool_health_cache.get("probe") == bool(probe)
            and (now - float(_tool_health_cache.get("ts", 0.0) or 0.0)) <= ttl
        ):
            return dict(_tool_health_cache.get("items", {})), dict(_tool_health_cache.get("summary", {}))

        load_errors = get_tool_load_errors()
        items: dict[str, dict] = {}
        summary = {
            "ready": 0,
            "needs_params": 0,
            "broken": 0,
            "probed": 0,
            "probe_ok": 0,
            "probe_fail": 0,
        }

        for name in tool_names:
            tool_name = str(name or "").strip()
            if not tool_name:
                continue

            fn = AVAILABLE_TOOLS.get(tool_name)
            source = "lazy_catalog"
            load_error = str(load_errors.get(tool_name, "") or "")
            if not callable(fn) and hasattr(self.agent, "kernel") and hasattr(self.agent.kernel, "tools"):
                try:
                    tdef = self.agent.kernel.tools.get_tool(tool_name)
                except Exception:
                    tdef = None
                if tdef and callable(getattr(tdef, "func", None)):
                    fn = tdef.func
                    source = "registry"
                    load_error = ""

            required_params = self._required_params_for_callable(fn)
            if not callable(fn):
                status = "broken"
            elif required_params:
                status = "needs_params"
            else:
                status = "ready"

            probe_result = {"status": "skipped", "latency_ms": 0, "error": ""}
            if probe and callable(fn):
                params = self._tool_probe_params(tool_name)
                if isinstance(params, dict):
                    summary["probed"] += 1
                    started = time.perf_counter()
                    try:
                        result = await self.agent._execute_tool(
                            tool_name,
                            params,
                            user_input=f"tool probe {tool_name}",
                            step_name="tool_probe",
                        )
                        latency_ms = int((time.perf_counter() - started) * 1000)
                        ok = not (isinstance(result, dict) and result.get("success") is False)
                        if ok:
                            summary["probe_ok"] += 1
                            probe_result = {"status": "ok", "latency_ms": latency_ms, "error": ""}
                        else:
                            summary["probe_fail"] += 1
                            err = str(result.get("error", "probe failed")) if isinstance(result, dict) else "probe failed"
                            probe_result = {"status": "fail", "latency_ms": latency_ms, "error": err}
                    except Exception as probe_exc:
                        latency_ms = int((time.perf_counter() - started) * 1000)
                        summary["probe_fail"] += 1
                        probe_result = {"status": "fail", "latency_ms": latency_ms, "error": str(probe_exc)}
                else:
                    probe_result = {"status": "unsupported", "latency_ms": 0, "error": ""}

            if status == "broken":
                summary["broken"] += 1
            elif status == "needs_params":
                summary["needs_params"] += 1
            else:
                summary["ready"] += 1

            items[tool_name] = {
                "status": status,
                "callable": bool(callable(fn)),
                "required_params": required_params,
                "load_error": load_error,
                "source": source,
                "probe": probe_result,
            }

        _tool_health_cache = {
            "ts": now,
            "probe": bool(probe),
            "items": dict(items),
            "summary": dict(summary),
        }
        return items, summary

    # ── Tool Request Log API ──────────────────────────────────────────────────

    async def handle_tool_requests(self, request):
        """GET /api/tool-requests — Son N tool çağrısı."""
        from core.tool_request import get_tool_request_log
        limit = min(int(request.rel_url.query.get("limit", 100) or 100), 500)
        tool_filter = (request.rel_url.query.get("tool", "") or "").strip()
        success_only = request.rel_url.query.get("success_only", "0") in {"1", "true"}
        try:
            log = get_tool_request_log()
            records = log.get_recent(limit=limit, tool_name=tool_filter, success_only=success_only)
            return web.json_response({"ok": True, "records": records, "count": len(records)})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_tool_requests_stats(self, request):
        """GET /api/tool-requests/stats — Tool istek özet istatistikleri."""
        from core.tool_request import get_tool_request_log
        try:
            log = get_tool_request_log()
            stats = log.get_stats()
            return web.json_response({"ok": True, **stats})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def handle_tool_events(self, request):
        """GET /api/tool-events — Recent tool start/update/end stream events."""
        try:
            limit = int(request.rel_url.query.get("limit", 120) or 120)
        except Exception:
            limit = 120
        limit = max(1, min(500, limit))
        stage = str(request.rel_url.query.get("stage", "") or "").strip().lower()
        rows = list(_tool_event_log)
        if stage:
            rows = [r for r in rows if str(r.get("stage", "")).strip().lower() == stage]
        rows = rows[-limit:]
        return web.json_response({"ok": True, "events": list(reversed(rows)), "count": len(rows)})

    async def handle_tools(self, request):
        query = (request.rel_url.query.get("q", "") or "").strip().lower()
        group_filter = (request.rel_url.query.get("group", "") or "").strip().lower()
        policy_filter = (request.rel_url.query.get("policy", "") or "").strip().lower()
        health_filter = (request.rel_url.query.get("health", "") or "").strip().lower()
        run_probe = request.rel_url.query.get("probe", "0") in {"1", "true", "yes"}

        allow, deny, require_approval = _get_policy_lists()
        usage = get_tool_usage_snapshot().get("stats", {})
        reg_desc = self.agent.kernel.tools.list_tools() if hasattr(self.agent, "kernel") else {}
        if not isinstance(reg_desc, dict):
            reg_desc = {}

        tool_names = sorted(set(list(AVAILABLE_TOOLS.keys()) + list(reg_desc.keys())))
        health_map, health_summary = await self._compute_tool_health(tool_names, probe=run_probe)
        skill_tool_links: dict[str, list[str]] = {}
        workflow_tool_links: dict[str, list[str]] = {}
        try:
            for s in skill_manager.list_skills(available=True):
                s_name = str(s.get("name", "")).strip()
                for t in list(s.get("required_tools", []) or []):
                    tool = str(t or "").strip()
                    if not tool:
                        continue
                    skill_tool_links.setdefault(tool, []).append(s_name)
            for wf in skill_manager.list_workflows():
                wf_id = str(wf.get("id", "")).strip()
                for t in list(wf.get("required_tools", []) or []):
                    tool = str(t or "").strip()
                    if not tool:
                        continue
                    workflow_tool_links.setdefault(tool, []).append(wf_id)
        except Exception:
            skill_tool_links = {}
            workflow_tool_links = {}
        items = []
        group_counts = {}
        total_allowed = 0
        total_denied = 0
        total_approval = 0
        filtered_health = {"ready": 0, "needs_params": 0, "broken": 0}
        with_skill_links = 0
        with_workflow_links = 0

        for name in tool_names:
            group, allowed, denied, needs_approval = _policy_state(name)

            if query and query not in name.lower():
                continue
            if group_filter and group_filter != group:
                continue
            if policy_filter == "allowed" and not allowed:
                continue
            if policy_filter == "denied" and not denied:
                continue
            if policy_filter == "approval" and not needs_approval:
                continue
            health = health_map.get(name, {})
            if health_filter and str(health.get("status", "")).lower() != health_filter:
                continue

            total_allowed += 1 if allowed else 0
            total_denied += 1 if denied else 0
            total_approval += 1 if needs_approval else 0
            group_counts[group] = int(group_counts.get(group, 0)) + 1
            hstatus = str(health.get("status", "")).lower()
            if hstatus in filtered_health:
                filtered_health[hstatus] += 1
            linked_skills = sorted(list(dict.fromkeys(skill_tool_links.get(name, []) or [])))
            linked_workflows = sorted(list(dict.fromkeys(workflow_tool_links.get(name, []) or [])))
            if linked_skills:
                with_skill_links += 1
            if linked_workflows:
                with_workflow_links += 1

            u = usage.get(name, {})
            items.append({
                "name": name,
                "group": group,
                "description": reg_desc.get(name, ""),
                "allowed": allowed,
                "denied": denied,
                "requires_approval": needs_approval,
                "health": health,
                "linked_skills": linked_skills,
                "linked_workflows": linked_workflows,
                "usage": {
                    "calls": int(u.get("calls", 0) or 0),
                    "success_rate": float(u.get("success_rate", 0.0) or 0.0),
                    "last_latency_ms": int(u.get("last_latency_ms", 0) or 0),
                    "avg_latency_ms": float(u.get("avg_latency_ms", 0.0) or 0.0),
                    "last_used_at": u.get("last_used_at", ""),
                    "last_success": u.get("last_success"),
                    "last_error": u.get("last_error", ""),
                },
            })

        return web.json_response({
            "tools": items,
            "summary": {
                "total": len(items),
                "allowed": total_allowed,
                "denied": total_denied,
                "approval_required": total_approval,
                "groups": group_counts,
                "health": {
                    **filtered_health,
                    "probed": int(health_summary.get("probed", 0) or 0),
                    "probe_ok": int(health_summary.get("probe_ok", 0) or 0),
                    "probe_fail": int(health_summary.get("probe_fail", 0) or 0),
                },
                "linked_skills": with_skill_links,
                "linked_workflows": with_workflow_links,
            },
            "policy": {
                "allow": allow,
                "deny": deny,
                "requireApproval": require_approval,
                "defaultDeny": _policy_default_deny_enabled(),
            },
        })

    async def handle_tool_detail(self, request):
        name = str(request.rel_url.query.get("name", "") or "").strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        tool_name = name
        if tool_name not in AVAILABLE_TOOLS and hasattr(self.agent, "_resolve_tool_name"):
            resolved = self.agent._resolve_tool_name(tool_name)
            if resolved:
                tool_name = resolved

        reg_desc = self.agent.kernel.tools.list_tools() if hasattr(self.agent, "kernel") else {}
        if not isinstance(reg_desc, dict):
            reg_desc = {}
        usage = get_tool_usage_snapshot().get("stats", {}).get(tool_name, {})
        allow, deny, require_approval = _get_policy_lists()
        group, allowed, denied, needs_approval = _policy_state(tool_name)
        health_map, _ = await self._compute_tool_health([tool_name], probe=False)
        health = health_map.get(tool_name, {})

        signature = ""
        parameters = []
        tdef = None
        try:
            if hasattr(self.agent, "kernel") and hasattr(self.agent.kernel, "tools"):
                tdef = self.agent.kernel.tools.get_tool(tool_name)
        except Exception:
            tdef = None
        if tdef and getattr(tdef, "func", None):
            try:
                signature = str(inspect.signature(tdef.func))
            except Exception:
                signature = ""
            parameters = list((getattr(tdef, "parameters", {}) or {}).keys())

        return web.json_response({
            "ok": True,
            "tool": {
                "name": tool_name,
                "description": reg_desc.get(tool_name, ""),
                "group": group,
                "allowed": allowed,
                "denied": denied,
                "requires_approval": needs_approval,
                "signature": signature,
                "parameters": parameters,
                "suggested_params": self._tool_probe_params(tool_name) or {},
                "health": health,
                "usage": {
                    "calls": int(usage.get("calls", 0) or 0),
                    "success_rate": float(usage.get("success_rate", 0.0) or 0.0),
                    "last_latency_ms": int(usage.get("last_latency_ms", 0) or 0),
                    "avg_latency_ms": float(usage.get("avg_latency_ms", 0.0) or 0.0),
                    "last_used_at": usage.get("last_used_at", ""),
                    "last_success": usage.get("last_success"),
                    "last_error": usage.get("last_error", ""),
                },
            },
            "policy": {
                "allow": allow,
                "deny": deny,
                "requireApproval": require_approval,
                "defaultDeny": _policy_default_deny_enabled(),
            },
        })

    async def handle_tools_diagnostics(self, request):
        run_probe = request.rel_url.query.get("probe", "0") in {"1", "true", "yes"}
        names_raw = str(request.rel_url.query.get("tools", "") or "").strip()
        selected = []
        if names_raw:
            selected = [x.strip() for x in names_raw.split(",") if x.strip()]
        if not selected:
            selected = sorted(set(list(AVAILABLE_TOOLS.keys())))

        health_map, summary = await self._compute_tool_health(selected, probe=run_probe)
        broken = [name for name, h in health_map.items() if h.get("status") == "broken"]
        return web.json_response({
            "ok": True,
            "probe": run_probe,
            "summary": summary,
            "broken_tools": broken,
            "items": health_map,
        })

    async def handle_get_logs(self, request):
        """GET /api/logs — Latest gateway logs."""
        from config.settings import LOGS_DIR
        log_file = LOGS_DIR / "gateway.log"
        if not log_file.exists():
            return web.json_response({"ok": False, "error": "Log file not found"}, status=404)
        
        try:
            # Read last 100 lines
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                latest = lines[-100:]
            return web.json_response({"ok": True, "logs": latest})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_tools_policy_get(self, request):
        allow, deny, require_approval = _get_policy_lists()
        return web.json_response(
            {
                "ok": True,
                "policy": {
                    "allow": allow,
                    "deny": deny,
                    "requireApproval": require_approval,
                    "defaultDeny": _policy_default_deny_enabled(),
                },
                "defaults": {
                    "allow": [
                        "group:fs",
                        "group:web",
                        "group:ui",
                        "group:runtime",
                        "group:messaging",
                        "group:automation",
                        "group:memory",
                        "browser",
                    ],
                    "deny": ["exec"],
                    "requireApproval": ["delete_file", "write_file"],
                    "defaultDeny": True,
                },
            }
        )

    async def handle_tools_policy(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        allow, deny, require_approval = _get_policy_lists()

        # Full list replacement
        if isinstance(data.get("allow"), list):
            allow = _unique_clean(data.get("allow"), [])
        if isinstance(data.get("deny"), list):
            deny = _unique_clean(data.get("deny"), [])
        if isinstance(data.get("requireApproval"), list):
            require_approval = _unique_clean(data.get("requireApproval"), [])
        if isinstance(data.get("require_approval"), list):
            require_approval = _unique_clean(data.get("require_approval"), [])
        default_deny = _policy_default_deny_enabled()
        default_deny_raw = data.get("defaultDeny", data.get("default_deny"))
        if default_deny_raw is not None:
            default_deny = _to_bool(default_deny_raw, default_deny)

        # Per-tool / per-group toggle
        target = None
        if data.get("tool"):
            target = str(data.get("tool", "")).strip()
        elif data.get("group"):
            group = str(data.get("group", "")).strip().lower().replace("group:", "")
            if group:
                target = f"group:{group}"

        if target:
            if isinstance(data.get("allow"), bool):
                if data["allow"]:
                    if target not in allow:
                        allow.append(target)
                    if target in deny:
                        deny.remove(target)
                elif target in allow:
                    allow.remove(target)

            if isinstance(data.get("deny"), bool):
                if data["deny"]:
                    if target not in deny:
                        deny.append(target)
                    if target in allow:
                        allow.remove(target)
                elif target in deny:
                    deny.remove(target)

            approval_toggle = data.get("requireApproval", data.get("require_approval"))
            if isinstance(approval_toggle, bool):
                if approval_toggle and target not in require_approval:
                    require_approval.append(target)
                if not approval_toggle and target in require_approval:
                    require_approval.remove(target)

        allow = _unique_clean(allow, [])
        deny = _unique_clean(deny, [])
        require_approval = _unique_clean(require_approval, [])

        elyan_config.set("tools.allow", allow)
        elyan_config.set("tools.deny", deny)
        # Store both keys for compatibility.
        elyan_config.set("tools.requireApproval", require_approval)
        elyan_config.set("tools.require_approval", require_approval)
        elyan_config.set("tools.default_deny", default_deny)
        elyan_config.set("security.toolPolicy.defaultDeny", default_deny)
        tool_policy.reload()
        push_activity("tools_policy", "dashboard", "Tool policy updated", True)

        return web.json_response({
            "ok": True,
            "policy": {
                "allow": allow,
                "deny": deny,
                "requireApproval": require_approval,
                "defaultDeny": default_deny,
            },
        })

    async def handle_tools_test(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        tool = str(data.get("tool", "")).strip()
        params = data.get("params", {})
        execute = bool(data.get("execute", True))
        if not tool:
            return web.json_response({"ok": False, "error": "tool required"}, status=400)
        if not isinstance(params, dict):
            return web.json_response({"ok": False, "error": "params must be object"}, status=400)

        group = tool_policy.infer_group(tool)
        access = tool_policy.check_access(tool, group)
        if not access.get("allowed"):
            return web.json_response({"ok": False, "error": access.get("reason", "policy denied"), "access": access}, status=403)
        if access.get("requires_approval"):
            return web.json_response({"ok": False, "requires_approval": True, "access": access}, status=202)

        suggested_params = self._tool_probe_params(tool) or {}
        if not params and suggested_params:
            params = dict(suggested_params)

        health_map, _ = await self._compute_tool_health([tool], probe=False)
        h = health_map.get(tool, {}) if isinstance(health_map, dict) else {}
        required_params = h.get("required_params", []) if isinstance(h, dict) else []
        if execute and required_params and not params:
            return web.json_response({
                "ok": False,
                "error": f"'{tool}' için parametre gerekli.",
                "required_params": required_params,
                "suggested_params": suggested_params,
            }, status=400)

        if not execute:
            return web.json_response({
                "ok": True,
                "dry_run": True,
                "access": access,
                "tool": tool,
                "group": group,
                "required_params": required_params,
                "suggested_params": suggested_params,
            })

        # Keep dashboard-side test execution constrained to diagnostics/safe reads.
        safe_tools = {
            "list_files", "read_file", "search_files", "write_file", "write_word", "write_excel",
            "get_system_info", "get_process_info", "get_running_apps",
            "web_search", "fetch_page", "extract_text",
            "take_screenshot", "read_clipboard",
            "get_today_events", "get_reminders", "wifi_status", "get_public_ip",
        }
        if tool not in safe_tools:
            return web.json_response({
                "ok": False,
                "error": f"'{tool}' dashboard test çalıştırması için güvenli listede değil.",
                "safe_tools": sorted(safe_tools),
            }, status=400)

        started = time.perf_counter()
        try:
            result = await self.agent._execute_tool(tool, params, user_input=f"dashboard tool test: {tool}", step_name="dashboard_test")
            latency_ms = int((time.perf_counter() - started) * 1000)
            push_activity("tool_test", "dashboard", f"{tool} ({latency_ms}ms)", True)
            return web.json_response({
                "ok": True,
                "tool": tool,
                "group": group,
                "latency_ms": latency_ms,
                "used_params": params,
                "formatted": self.agent._format_result_text(result),
                "result": result,
            })
        except Exception as e:
            latency_ms = int((time.perf_counter() - started) * 1000)
            push_activity("tool_test", "dashboard", f"{tool} failed ({latency_ms}ms)", False)
            return web.json_response({"ok": False, "error": str(e), "latency_ms": latency_ms}, status=500)

    # ── Skills management (new) ──────────────────────────────────────────────
    async def handle_skills(self, request):
        available = request.rel_url.query.get("available", "0") in {"1", "true", "yes"}
        enabled_only = request.rel_url.query.get("enabled", "0") in {"1", "true", "yes"}
        q = (request.rel_url.query.get("q", "") or "").strip()
        from core.skills_overview import build_skills_summary

        return web.json_response(build_skills_summary(query=q, available=available, enabled_only=enabled_only))

    async def handle_skill_detail(self, request):
        name = str(request.rel_url.query.get("name", "") or "").strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        info = skill_manager.get_skill(name)
        if not info:
            return web.json_response({"ok": False, "error": "skill not found"}, status=404)
        check = skill_manager.check(name=name)
        return web.json_response({
            "ok": True,
            "skill": info,
            "check": check,
        })

    async def handle_skill_install(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg, info = skill_manager.install_skill(name)
        skill_registry.refresh()
        push_activity("skill_install", "dashboard", f"{name}: {msg}", success=ok)
        return web.json_response({"ok": ok, "message": msg, "skill": info}, status=200 if ok else 400)

    async def handle_skill_toggle(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        enabled = bool(data.get("enabled", True))
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg, info = skill_manager.set_enabled(name, enabled)
        skill_registry.refresh()
        push_activity("skill_toggle", "dashboard", f"{name}: {'on' if enabled else 'off'}", success=ok)
        return web.json_response({"ok": ok, "message": msg, "skill": info}, status=200 if ok else 400)

    async def handle_skill_remove(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg = skill_manager.remove_skill(name)
        skill_registry.refresh()
        push_activity("skill_remove", "dashboard", f"{name}: {msg}", success=ok)
        return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)

    async def handle_skill_update(self, request):
        try:
            data = await request.json()
        except Exception:
            data = {}
        name = str(data.get("name", "")).strip() if data.get("name") else None
        update_all = bool(data.get("all", False))
        result = skill_manager.update_skills(name=name, update_all=update_all)
        skill_registry.refresh()
        push_activity("skill_update", "dashboard", f"updated={len(result.get('updated', []))}", success=True)
        return web.json_response({"ok": True, **result})

    async def handle_skill_refresh(self, request):
        skill_registry.refresh()
        summary = {
            "skills": len(skill_registry.list_skills(available=True, enabled_only=True)),
            "workflows": len(skill_registry.list_workflows(enabled_only=True)),
        }
        push_activity("skill_refresh", "dashboard", f"skills={summary['skills']} workflows={summary['workflows']}", success=True)
        return web.json_response({"ok": True, "message": "skill registry refreshed", **summary})

    async def handle_skill_check(self, request):
        name = request.rel_url.query.get("name")
        result = skill_manager.check(name=name)
        return web.json_response(result)

    async def handle_skill_workflows(self, request):
        enabled_only = request.rel_url.query.get("enabled", "0") in {"1", "true", "yes"}
        q = (request.rel_url.query.get("q", "") or "").strip()
        items = skill_manager.list_workflows(enabled_only=enabled_only, query=q)
        executable = [x for x in items if x.get("executable")]
        auto_intent = [x for x in items if x.get("auto_intent")]
        enabled = [x for x in items if x.get("enabled")]
        runtime_ready = [x for x in items if x.get("runtime_ready")]
        return web.json_response({
            "ok": True,
            "workflows": items,
            "summary": {
                "total": len(items),
                "enabled": len(enabled),
                "executable": len(executable),
                "auto_intent": len(auto_intent),
                "runtime_ready": len(runtime_ready),
            },
        })

    async def handle_skill_workflow_toggle(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        workflow_id = str(data.get("id", "")).strip()
        enabled = bool(data.get("enabled", True))
        if not workflow_id:
            return web.json_response({"ok": False, "error": "id required"}, status=400)
        ok, msg, info = skill_manager.set_workflow_enabled(workflow_id, enabled)
        skill_registry.refresh()
        push_activity("workflow_toggle", "dashboard", f"{workflow_id}: {'on' if enabled else 'off'}", success=ok)
        return web.json_response({"ok": ok, "message": msg, "workflow": info}, status=200 if ok else 400)

    # ── Marketplace Handlers ────────────────────────────────────────────────
    async def handle_marketplace_browse(self, request):
        from core.skills.marketplace import get_marketplace
        mp = get_marketplace()
        category = request.rel_url.query.get("category", "")
        query = request.rel_url.query.get("q", "")
        sort_by = request.rel_url.query.get("sort", "rating")
        listings = await mp.browse(category=category, query=query, sort_by=sort_by)
        return web.json_response({"ok": True, "listings": listings, "total": len(listings)})

    async def handle_marketplace_search(self, request):
        from core.skills.marketplace import get_marketplace
        mp = get_marketplace()
        q = request.rel_url.query.get("q", "")
        results = await mp.search(q)
        return web.json_response({"ok": True, "results": results, "total": len(results)})

    async def handle_marketplace_categories(self, request):
        from core.skills.marketplace import get_marketplace
        mp = get_marketplace()
        categories = await mp.get_categories()
        return web.json_response({"ok": True, "categories": categories})

    async def handle_marketplace_install(self, request):
        from core.skills.marketplace import get_marketplace
        mp = get_marketplace()
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        url = str(data.get("url", "")).strip()
        if url:
            ok, msg, warnings = await mp.install_from_url(url)
        elif isinstance(data.get("package"), dict):
            ok, msg, warnings = await mp.install_from_dict(data["package"])
        else:
            return web.json_response({"ok": False, "error": "url or package required"}, status=400)
        if ok:
            skill_registry.refresh()
        return web.json_response({"ok": ok, "message": msg, "warnings": warnings}, status=200 if ok else 400)

    async def handle_marketplace_review(self, request):
        from core.skills.marketplace import get_marketplace
        mp = get_marketplace()
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        skill_name = str(data.get("skill", "")).strip()
        rating = int(data.get("rating", 0))
        comment = str(data.get("comment", ""))
        if not skill_name or not (1 <= rating <= 5):
            return web.json_response({"ok": False, "error": "skill and rating (1-5) required"}, status=400)
        mp.add_review(skill_name, rating, comment)
        avg = mp.get_average_rating(skill_name)
        return web.json_response({"ok": True, "average_rating": avg})

    async def handle_marketplace_export(self, request):
        from core.skills.marketplace import get_marketplace
        mp = get_marketplace()
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        name = str(data.get("name", "")).strip()
        if not name:
            return web.json_response({"ok": False, "error": "name required"}, status=400)
        ok, msg = mp.export_skill(name)
        return web.json_response({"ok": ok, "message": msg}, status=200 if ok else 400)

    # ── Integrations / Accounts & Trace ────────────────────────────────────
    async def handle_integrations_accounts(self, request):
        from integrations import oauth_broker

        provider = str(request.rel_url.query.get("provider", "") or "").strip().lower()
        accounts = [account.public_dump() for account in oauth_broker.list_accounts(provider or None)]
        counts: dict[str, int] = {}
        for item in accounts:
            state = str(item.get("status") or "unknown").strip().lower()
            counts[state] = int(counts.get(state, 0)) + 1
        return web.json_response({
            "ok": True,
            "provider": provider,
            "accounts": accounts,
            "total": len(accounts),
            "counts": counts,
        })

    async def handle_integrations_connect(self, request):
        return await self.handle_integrations_account_connect(request)

    async def handle_integrations_account_connect(self, request):
        from integrations import connector_factory, integration_registry, oauth_broker
        from core.integration_trace import get_integration_trace_store

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        app_name = str(data.get("app_name") or data.get("intent") or data.get("application") or "").strip()
        provider = str(data.get("provider", "") or "").strip().lower()
        scopes = data.get("scopes", [])
        if isinstance(scopes, str):
            scopes = [item.strip() for item in scopes.split(",") if item.strip()]
        if not isinstance(scopes, list):
            scopes = []
        mode = str(data.get("mode") or "auto")
        alias_input = str(data.get("account_alias") or "").strip()
        redirect_uri = str(data.get("redirect_uri") or "").strip() or "http://localhost:8765/callback"
        plan = integration_registry.resolve_connection_plan(
            app_name=app_name,
            provider=provider,
            scopes=scopes,
            mode=mode,
            account_alias=alias_input or "default",
            extra={
                "display_name": str(data.get("display_name") or "").strip(),
                "email": str(data.get("email") or "").strip(),
            },
        )
        provider = str(plan.get("provider") or provider or "").strip().lower()
        if not provider:
            return web.json_response({"ok": False, "error": "provider required"}, status=400)
        scopes = list(plan.get("required_scopes") or scopes or [])
        account_alias = alias_input or str(plan.get("account_alias") or "default").strip() or "default"
        trace_store = get_integration_trace_store()
        trace_store.record_trace(
            operation="integration_connect_requested",
            provider=provider,
            connector_name=str(plan.get("connector_name") or provider or "connector"),
            integration_type=str((plan.get("integration_type").value if hasattr(plan.get("integration_type"), "value") else plan.get("integration_type")) or ""),
            status="requested",
            success=False,
            auth_state="pending",
            account_alias=account_alias,
            metadata={
                "app_name": app_name,
                "resolved_from": dict(plan.get("resolved_from") or {}),
                "resolved_scopes": list(scopes),
                "mode": mode,
            },
        )
        account = oauth_broker.authorize(
            provider,
            scopes,
            mode=mode,
            account_alias=account_alias,
            authorization_code=str(data.get("authorization_code") or ""),
            redirect_uri=redirect_uri,
            extra={
                "display_name": str(data.get("display_name") or "").strip(),
                "email": str(data.get("email") or "").strip(),
                "app_name": app_name,
                "resolved_provider": provider,
            },
        )
        connector_result = None
        if account.is_ready:
            try:
                capability = plan.get("capability")
                connector = connector_factory.get(
                    getattr(plan.get("integration_type"), "value", plan.get("integration_type") or "unknown"),
                    auth_state={
                        "capability": capability.model_dump() if hasattr(capability, "model_dump") else dict(capability or {}),
                        "auth_account": account.model_dump() if hasattr(account, "model_dump") else account.public_dump(),
                        "provider": provider,
                        "connector_name": str(plan.get("connector_name") or provider or "connector"),
                    },
                )
                connect_target = app_name or provider or str(plan.get("connector_name") or "integration")
                connector_result = await connector.connect(connect_target, mode=mode)
            except Exception as exc:
                connector_result = {"success": False, "status": "failed", "error": str(exc), "message": str(exc)}
        connector_success = True
        connector_fallback_used = False
        connector_fallback_reason = ""
        if isinstance(connector_result, dict):
            connector_success = bool(connector_result.get("success", False))
            connector_fallback_used = bool(connector_result.get("fallback_used", False))
            connector_fallback_reason = str(connector_result.get("fallback_reason") or "")
        elif connector_result is not None:
            connector_success = bool(getattr(connector_result, "success", False))
            connector_fallback_used = bool(getattr(connector_result, "fallback_used", False))
            connector_fallback_reason = str(getattr(connector_result, "fallback_reason", "") or "")
        account_needs_input = str(getattr(account, "status", "") or "").strip().lower() == "needs_input"
        account_fallback_mode = str(getattr(account.fallback_mode, "value", account.fallback_mode) or "")
        push_activity(
            "integration_connect",
            "dashboard",
            f"{provider}:{account.account_alias}:{account.status}",
            success=bool(account.is_ready and connector_success),
        )
        payload = {
            "ok": True,
            "resolved_app_name": plan.get("app_name") or app_name or provider,
            "resolved_provider": provider,
            "resolved_scopes": scopes,
            "resolved_account_alias": account_alias,
            "account": account.public_dump(),
            "needs_input": bool(account_needs_input),
            "auth_url": account.auth_url,
            "launch_url": account.auth_url if account.auth_url else "",
            "fallback_mode": account_fallback_mode,
            "connect_result": connector_result.model_dump() if hasattr(connector_result, "model_dump") else (dict(connector_result) if isinstance(connector_result, dict) else {}),
        }
        trace_store.record_trace(
            operation="integration_connect_result",
            provider=provider,
            connector_name=str(plan.get("connector_name") or provider or "connector"),
            integration_type=str((plan.get("integration_type").value if hasattr(plan.get("integration_type"), "value") else plan.get("integration_type")) or ""),
            status=str((payload.get("connect_result") or {}).get("status") or account.status),
            success=bool(account.is_ready and connector_success),
            auth_state=str(account.status),
            auth_strategy=str(plan.get("auth_strategy") or ""),
            account_alias=account.account_alias,
            fallback_used=bool(connector_fallback_used or account_needs_input),
            fallback_reason=str(connector_fallback_reason or (account_fallback_mode if account_needs_input else "") or ""),
            metadata={
                "app_name": app_name,
                "resolved_app_name": payload["resolved_app_name"],
                "resolved_provider": provider,
                "resolved_scopes": scopes,
                "launch_url": payload["launch_url"],
                "connect_result": payload.get("connect_result") or {},
            },
        )
        return web.json_response(payload)

    async def handle_integrations_account_revoke(self, request):
        from integrations import oauth_broker

        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)
        provider = str(data.get("provider", "") or "").strip().lower()
        if not provider:
            return web.json_response({"ok": False, "error": "provider required"}, status=400)
        alias = str(data.get("account_alias") or "default").strip() or "default"
        ok = oauth_broker.delete_account(provider, alias)
        push_activity("integration_revoke", "dashboard", f"{provider}:{alias}", success=ok)
        return web.json_response({"ok": ok, "provider": provider, "account_alias": alias})

    async def handle_integration_traces(self, request):
        from core.integration_trace import get_integration_trace_store

        store = get_integration_trace_store()
        try:
            limit = int(request.rel_url.query.get("limit", 100))
        except Exception:
            limit = 100
        traces = store.list_traces(
            limit=limit,
            provider=str(request.rel_url.query.get("provider", "") or "").strip().lower(),
            user_id=str(request.rel_url.query.get("user_id", "") or "").strip(),
            operation=str(request.rel_url.query.get("operation", "") or "").strip().lower(),
            connector_name=str(request.rel_url.query.get("connector_name", "") or "").strip().lower(),
            integration_type=str(request.rel_url.query.get("integration_type", "") or "").strip().lower(),
        )
        return web.json_response({"ok": True, "traces": traces, "total": len(traces), "summary": store.summary(limit=limit)})

    async def handle_integration_summary(self, request):
        from core.integration_trace import get_integration_trace_store
        from integrations import oauth_broker

        provider = str(request.rel_url.query.get("provider", "") or "").strip().lower()
        accounts = [account.public_dump() for account in oauth_broker.list_accounts(provider or None)]
        trace_summary = get_integration_trace_store().summary(limit=200)
        account_counts: dict[str, int] = {}
        for item in accounts:
            state = str(item.get("status") or "unknown").strip().lower()
            account_counts[state] = int(account_counts.get(state, 0)) + 1
        return web.json_response({
            "ok": True,
            "accounts": {
                "total": len(accounts),
                "counts": account_counts,
                "provider": provider,
                "items": accounts[:20],
            },
            "traces": trace_summary,
        })

    # ── LLM Setup Manager Handlers ───────────────────────────────────────────
    async def handle_llm_setup_status(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        statuses = await setup.get_all_provider_status()
        return _json_ok({"providers": statuses, "first_run": setup.is_first_run()})

    async def handle_llm_setup_health(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        health = await setup.quick_health()
        return _json_ok(dict(health))

    async def handle_llm_setup_save_key(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        provider = str(data.get("provider", "")).strip()
        api_key = str(data.get("api_key", "") or "").strip()
        if not provider:
            return _json_error("provider required", status=400)
        if provider != "ollama" and not api_key:
            return _json_error("api_key required", status=400)
        result = await setup.save_api_key(provider, api_key)
        if result.get("success", False):
            return _json_ok(dict(result))
        return _json_error(str(result.get("error") or result.get("message") or "request_failed"), payload=dict(result))

    async def handle_llm_setup_remove_key(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        provider = str(data.get("provider", "")).strip()
        result = await setup.remove_api_key(provider)
        if result.get("success", False):
            return _json_ok(dict(result))
        return _json_error(str(result.get("error") or result.get("message") or "request_failed"), payload=dict(result))

    async def handle_llm_setup_ollama(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        status = await setup.ollama_status()
        return _json_ok(dict(status))

    async def handle_llm_setup_ollama_pull(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        model = str(data.get("model", "")).strip()
        if not model:
            return _json_error("model required", status=400)
        result = await setup.ollama_pull_model(model)
        if result.get("success", False):
            return _json_ok(dict(result))
        return _json_error(str(result.get("error") or result.get("message") or "request_failed"), payload=dict(result))

    async def handle_llm_setup_ollama_delete(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        try:
            data = await request.json()
        except Exception:
            return _json_error("invalid json", status=400)
        model = str(data.get("model", "")).strip()
        if not model:
            return _json_error("model required", status=400)
        result = await setup.ollama_delete_model(model)
        if result.get("success", False):
            return _json_ok(dict(result))
        return _json_error(str(result.get("error") or result.get("message") or "request_failed"), payload=dict(result))

    async def handle_llm_setup_recommend(self, request):
        from core.llm_setup import get_llm_setup
        setup = get_llm_setup()
        return _json_ok(dict(setup.get_setup_recommendation()))

    # ── WebSocket: Dashboard push (new) ───────────────────────────────────────
    async def handle_dashboard_ws(self, request):
        if not _is_loopback_request(request):
            return web.json_response({"ok": False, "error": "dashboard websocket is restricted to localhost"}, status=403)

        allowed, error, _auth_context = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            admin_allowed, admin_error = self._require_admin_access(request, allow_cookie=True)
            if admin_allowed:
                allowed = True
                error = ""
            else:
                error = admin_error or error

        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)

        if not allowed:
            allowed, error = await _await_dashboard_ws_auth(ws)
            if not allowed:
                await ws.send_json({"type": "error", "event": "error", "data": {"error": error}})
                await ws.close(code=WSCloseCode.POLICY_VIOLATION, message=str(error or "authentication required").encode("utf-8"))
                return ws

        _dashboard_ws_clients.add(ws)

        try:
            await ws.send_json(
                {
                    "type": "connected",
                    "event": "connected",
                    "data": {
                        "runtime": "elyan_gateway",
                        "connected_at": time.time(),
                        "activity_buffer_size": len(_activity_log),
                        "tool_event_buffer_size": len(_tool_event_log),
                    },
                }
            )

            for entry in list(_activity_log)[-12:]:
                await ws.send_json({"type": "activity", "event": "activity", "data": entry})

            for entry in list(_tool_event_log)[-24:]:
                await ws.send_json({"type": "tool_event", "event": "tool_event", "data": entry})

            for entry in list(_cowork_event_log)[-24:]:
                await ws.send_json({"type": entry.get("event_type", "cowork.delta"), "event": entry.get("event_type", "cowork.delta"), "data": entry.get("payload", {})})

            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    if str(msg.data).strip().lower() == "ping":
                        await ws.send_str('{"type":"pong","event":"pong","data":{"ok":true}}')
                elif msg.type in {WSMsgType.ERROR, WSMsgType.CLOSE, WSMsgType.CLOSED}:
                    break
        finally:
            _dashboard_ws_clients.discard(ws)

        return ws

    # ── WebSocket: Node connection (new for v2) ───────────────────────────────
    async def handle_node_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        
        node_id = None
        logger.info("Node WS connecting...")
        
        try:
            async for msg in ws:
                if msg.type == WSMsgType.TEXT:
                    try:
                        event = json.loads(msg.data)
                        event_type = event.get("event_type")
                        data = event.get("data", {})
                        
                        if event_type == "NodeRegistered":
                            node_id = data.get("node_id")
                            if node_id:
                                self.connected_nodes[node_id] = ws
                                
                                from core.runtime.node_manager import node_manager, NodeInfo
                                from core.protocol.shared_types import NodeType
                                node_manager.register_node(NodeInfo(
                                    node_id=node_id,
                                    node_type=NodeType(data.get("node_type", "desktop")),
                                    capabilities=data.get("capabilities", []),
                                    hostname=data.get("hostname", "unknown"),
                                    platform=data.get("platform", "unknown"),
                                    metadata=data
                                ))
                                
                                logger.info(f"Node registered and connected: {node_id}")
                                push_activity("node_connect", "system", f"Node {node_id} online", True)
                        
                        elif event_type == "ActionResult":
                            action_id = data.get("action_id")
                            if action_id:
                                self.execution_hub.resolve_action(action_id, data)
                                logger.info(f"Action result from {node_id}: {action_id} -> {data.get('status')}")
                            
                        elif event_type == "Pong":
                            pass
                            
                    except Exception as e:
                        logger.error(f"Error processing node message: {e}")
                        
                elif msg.type == WSMsgType.ERROR:
                    logger.debug(f"Node WS error: {ws.exception()}")
        finally:
            if node_id:
                self.connected_nodes.pop(node_id, None)
                from core.runtime.node_manager import node_manager
                from core.protocol.shared_types import HealthStatus
                node_manager.update_health(node_id, HealthStatus.UNAVAILABLE)
                logger.info(f"Node disconnected: {node_id}")
                push_activity("node_disconnect", "system", f"Node {node_id} offline", False)
        
        return ws

    # ── Security endpoints ────────────────────────────────────────────────────
    async def handle_security_events(self, request):
        """Audit log events for Security tab."""
        limit = int(request.rel_url.query.get("limit", 20))
        severity = request.rel_url.query.get("severity", "")
        events = []
        try:
            import sqlite3
            from pathlib import Path
            audit_path = resolve_elyan_data_dir() / "audit.db"
            if not audit_path.exists():
                audit_path = Path(".elyan_audit/audit.db")
            if audit_path.exists():
                conn = sqlite3.connect(audit_path)
                conn.row_factory = sqlite3.Row
                q = "SELECT timestamp, operation, risk_level, status FROM audit_log ORDER BY timestamp DESC LIMIT ?"
                params = [limit]
                rows = conn.execute(q, params).fetchall()
                conn.close()
                for row in rows:
                    ev = dict(row)
                    if severity and ev.get("risk_level", "").lower() != severity.lower():
                        continue
                    events.append(ev)
        except Exception:
            pass
        return web.json_response({"events": events, "total": len(events)})

    async def handle_pending_approvals(self, request):
        """Pending approval requests (v2 integrated)."""
        from core.security.approval_engine import approval_engine
        pending = []
        for rid, req in approval_engine._pending.items():
            pending.append({
                "id": rid,
                "session_id": req.session_id,
                "run_id": req.run_id,
                "action": req.action_type,
                "risk": req.risk_level.value,
                "reason": req.reason,
                "payload": req.payload,
                "ts": req.created_at
            })
        return web.json_response({"pending": pending})

    async def handle_interventions_get(self, request):
        """List active agent questions/interventions."""
        manager = get_intervention_manager()
        return web.json_response({"ok": True, "interventions": manager.list_pending()})

    async def handle_interventions_resolve(self, request):
        """Resolve an active intervention with user response."""
        try:
            data = await request.json()
            request_id = data.get("id")
            response = data.get("response")
            if not request_id or response is None:
                return web.json_response({"ok": False, "error": "id and response required"}, status=400)
            
            manager = get_intervention_manager()
            success = manager.resolve(request_id, response)
            return web.json_response({"ok": success})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_approve_action(self, request):
        """Approve or reject a pending action (v2 integrated)."""
        try:
            data = await request.json()
            request_id = data.get("id")
            approved = bool(data.get("approved", False))
            resolver_id = "admin_ui" # Placeholder for actual admin user id
            
            from core.security.approval_engine import approval_engine
            approval_engine.resolve_approval(request_id, approved, resolver_id)
            
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_privacy_summary(self, request):
        """Privacy summary visible to the authenticated user."""
        allowed, error, session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return web.json_response({"success": False, "error": error}, status=403)
        user_id = str(
            request.rel_url.query.get("user_id", "")
            or session.get("user_id", "")
            or ""
        ).strip()
        if not user_id:
            return web.json_response({"success": False, "error": "user_id required"}, status=400)
        workspace_id = self._workspace_id(request, {"user_id": user_id})
        try:
            summary = get_learning_control_plane().get_privacy_summary(user_id, workspace_id=workspace_id)
            return web.json_response({"success": True, "summary": summary})
        except Exception as e:
            return web.json_response({"success": False, "error": str(e)}, status=500)

    async def handle_privacy_export(self, request):
        """KVKK/GDPR: export user audit footprint."""
        allowed, error, session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        user_id = str(
            request.rel_url.query.get("user_id", "")
            or session.get("user_id", "")
            or ""
        ).strip()
        if not user_id:
            return web.json_response({"ok": False, "error": "user_id required"}, status=400)
        workspace_id = self._workspace_id(request, {"user_id": user_id})
        try:
            export = {
                "audit": audit_trail.export_for_user(user_id),
                "privacy": get_learning_control_plane().export_privacy_bundle(user_id, workspace_id=workspace_id),
            }
            return web.json_response({"ok": True, "export": export})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_privacy_delete(self, request):
        """KVKK/GDPR: right to be forgotten (audit trail scope)."""
        allowed, error, session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return web.json_response({"ok": False, "error": error}, status=403)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        user_id = str(
            payload.get("user_id", "")
            or request.rel_url.query.get("user_id", "")
            or session.get("user_id", "")
            or ""
        ).strip()
        if not user_id:
            return web.json_response({"ok": False, "error": "user_id required"}, status=400)
        workspace_id = self._workspace_id(request, payload)
        try:
            result = {
                "audit": audit_trail.delete_user_data(user_id),
                "personalization": get_personalization_manager().delete_user_data(user_id),
                "reliability": get_outcome_store().delete_user(user_id),
                "runtime_control": get_runtime_control_plane().sync_store.delete_user(user_id),
                "privacy": get_runtime_database().privacy.delete_user_data(user_id, workspace_id=workspace_id),
            }
            push_activity("privacy", "dashboard", f"user_data_deleted:{user_id}", True)
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    def _privacy_subject(self, request, explicit_user_id: str) -> tuple[bool, str, dict[str, Any]]:
        allowed, error, session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return False, error, session
        session_user = str(session.get("user_id") or "").strip()
        subject = str(explicit_user_id or session_user or "").strip()
        if session_user and subject and session_user != subject:
            return False, "user_mismatch", session
        return True, subject or session_user, session

    async def handle_privacy_consent_get(self, request):
        from core.privacy import get_privacy_engine

        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        workspace_id = self._workspace_id(request, {"user_id": subject})
        scope = str(request.rel_url.query.get("scope", "") or "learning").strip()
        return web.json_response({"ok": True, "consent": get_privacy_engine().get_consent(subject, workspace_id=workspace_id, scope=scope)})

    async def handle_privacy_consent_set(self, request):
        from core.privacy import get_privacy_engine

        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        workspace_id = self._workspace_id(request, dict(payload, user_id=subject))
        metadata = dict(payload.get("metadata") or {})
        for key in (
            "allow_personal_data_learning",
            "allow_workspace_data_learning",
            "allow_operational_data_learning",
            "allow_public_data_learning",
            "allow_global_aggregate",
            "allow_global_aggregation",
            "paused",
            "opt_out",
        ):
            if key in payload:
                metadata[key] = payload.get(key)
        consent = get_privacy_engine().set_consent(
            subject,
            workspace_id=workspace_id,
            scope=str(payload.get("scope") or "learning").strip(),
            granted=bool(payload.get("granted", False)),
            source=str(payload.get("source") or "gateway").strip(),
            expires_at=float(payload.get("expires_at") or 0.0),
            metadata=metadata,
        )
        return web.json_response({"ok": True, "consent": consent})

    async def handle_privacy_data_delete(self, request):
        from core.learning import get_tiered_hub
        from core.privacy import get_privacy_engine

        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        workspace_id = self._workspace_id(request, {"user_id": subject})
        result = {
            "privacy": get_privacy_engine().delete_user_data(subject, workspace_id=workspace_id),
            "learning": get_learning_control_plane().delete_user_data(subject),
            "tiered": get_tiered_hub().delete_user_data(subject),
        }
        return web.json_response({"ok": True, "result": result})

    async def handle_privacy_export_user(self, request):
        from core.learning import get_tiered_hub
        from core.privacy import get_privacy_engine

        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        workspace_id = self._workspace_id(request, {"user_id": subject})
        export = {
            "privacy": get_privacy_engine().export_user_data(subject, workspace_id=workspace_id),
            "learning": get_learning_control_plane().export_privacy_bundle(subject, workspace_id=workspace_id),
            "tiered": get_tiered_hub().stats(),
        }
        return web.json_response({"ok": True, "export": export})

    async def handle_privacy_learning_stats(self, request):
        from core.learning import get_tiered_hub

        allowed, error, _session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return web.json_response({"error": error, "code": error}, status=403)
        return web.json_response({"ok": True, "stats": get_tiered_hub().stats()})

    async def handle_privacy_learning_global(self, request):
        from core.learning import get_tiered_hub

        allowed, error = self._require_admin_access(request)
        if not allowed:
            return web.json_response({"error": error, "code": error}, status=403)
        return web.json_response({"ok": True, "global": get_tiered_hub().global_summary()})

    async def handle_privacy_learning_pause(self, request):
        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        return web.json_response({"ok": True, "policy": get_learning_control_plane().set_learning_paused(True, user_id=subject)})

    async def handle_privacy_learning_resume(self, request):
        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        return web.json_response({"ok": True, "policy": get_learning_control_plane().set_learning_paused(False, user_id=subject)})

    async def handle_privacy_learning_optout(self, request):
        allowed, subject, _session = self._privacy_subject(request, str(request.match_info.get("user_id") or ""))
        if not allowed:
            return web.json_response({"error": subject, "code": subject}, status=403)
        return web.json_response({"ok": True, "policy": get_learning_control_plane().set_learning_opt_out(subject, True)})

    async def handle_mobile_dispatch_sessions(self, request):
        from elyan.channels.mobile_dispatch import MobileDispatchBridge

        allowed, error, _session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return web.json_response({"error": error, "code": error}, status=403)
        return web.json_response({"ok": True, **MobileDispatchBridge().get_dashboard_sessions()})

    async def handle_operator_status(self, request):
        from core.operator_status import get_operator_status

        allowed, error, _session = self._require_user_session(request, allow_cookie=True)
        if not allowed:
            return web.json_response({"error": error, "code": error}, status=403)
        payload = await get_operator_status()
        return web.json_response({"ok": True, **payload})

    # ── Channels ──────────────────────────────────────────────────────────────
    async def handle_list_channels(self, request):
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
        health_map = self.router.get_adapter_health() if hasattr(self.router, "get_adapter_health") else {}
        enriched = []
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            safe_ch = _mask_sensitive_fields(ch)
            ctype = ch.get("type")
            status = status_map.get(ctype, "disconnected")
            health = health_map.get(ctype, {})
            recv = int(health.get("received_count", 0) or 0)
            sent = int(health.get("sent_count", 0) or 0)
            send_failures = int(health.get("send_failures", 0) or 0)
            proc_errors = int(health.get("processing_errors", 0) or 0)
            total_ops = max(1, recv + sent)
            failure_rate_pct = round(((send_failures + proc_errors) / total_ops) * 100.0, 2)

            last_activity_ts = max(
                float(health.get("last_message_in_ts") or 0),
                float(health.get("last_message_out_ts") or 0),
                float(health.get("last_connected_ts") or 0),
            )
            last_activity_iso = (
                datetime.fromtimestamp(last_activity_ts).isoformat()
                if last_activity_ts > 0
                else None
            )
            entry = {
                **safe_ch,
                "status": status,
                "connected": status == "connected",
                "failure_rate_pct": failure_rate_pct,
                "message_metrics": {
                    "received": recv,
                    "sent": sent,
                    "send_failures": send_failures,
                    "processing_errors": proc_errors,
                },
                "last_activity": last_activity_iso,
                "health": health,
            }
            enriched.append(entry)
        return web.json_response({"channels": enriched})

    def _load_channel_map(self) -> dict[str, dict[str, Any]]:
        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            return {}
        return {
            _normalize_channel_type(str(item.get("type") or "")): dict(item)
            for item in channels
            if isinstance(item, dict)
        }

    def _build_channel_pair_status_payload(self, channel_type: str) -> dict[str, Any]:
        ctype = _normalize_channel_type(channel_type)
        adapter_status = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}
        channel_map = self._load_channel_map()
        config = dict(channel_map.get(ctype) or {})

        def _pack(
            *,
            mode: str,
            status: str,
            pending: bool,
            ready: bool,
            detail: str,
            instructions: list[str],
            qr_text: str = "",
            phone: str = "",
            blocking_issue: str = "",
        ) -> dict[str, Any]:
            return {
                "ok": True,
                "channel": ctype,
                "mode": mode,
                "status": status,
                "pending": pending,
                "ready": ready,
                "detail": detail,
                "instructions": instructions,
                "qr_text": qr_text,
                "phone": phone,
                "blocking_issue": blocking_issue,
            }

        if ctype == "whatsapp":
            if not config:
                return _pack(
                    mode="bridge_qr",
                    status="not_configured",
                    pending=False,
                    ready=False,
                    detail="WhatsApp pairing henüz başlatılmadı.",
                    instructions=[
                        "QR pairing başlat.",
                        "Telefonunda Bağlı Cihazlar ekranını aç.",
                        "QR görünür olduğunda tara.",
                    ],
                    blocking_issue="pairing_not_started",
                )
            bridge_url = str(
                config.get("bridge_url")
                or build_bridge_url(
                    str(config.get("bridge_host") or BRIDGE_HOST),
                    int(config.get("bridge_port") or DEFAULT_BRIDGE_PORT),
                )
            ).rstrip("/")
            bridge_token, unresolved_token = _resolve_channel_secret("bridge_token", ctype, config.get("bridge_token"))
            if unresolved_token:
                return _pack(
                    mode="bridge_qr",
                    status="needs_attention",
                    pending=False,
                    ready=False,
                    detail="WhatsApp bridge token çözümlenemedi.",
                    instructions=[
                        "WHATSAPP_BRIDGE_TOKEN secret’ını tekrar kaydet.",
                        "Pairing’i yeniden başlat.",
                    ],
                    blocking_issue="bridge_token_unresolved",
                )
            try:
                health = bridge_health(bridge_url, token=bridge_token, timeout_s=2.0)
                state = health.get("state", {}) if isinstance(health, dict) else {}
                if not isinstance(state, dict):
                    state = {}
                ready = bool(state.get("ready"))
                has_qr = bool(state.get("hasQr"))
                last_error = str(state.get("lastError") or "").strip()
                return _pack(
                    mode="bridge_qr",
                    status="ready" if ready else "waiting_for_scan" if has_qr else "starting",
                    pending=not ready,
                    ready=ready,
                    detail="WhatsApp lane hazır." if ready else "QR eşleştirmesi bekleniyor." if has_qr else "WhatsApp bridge başlıyor.",
                    instructions=[
                        "Telefonda WhatsApp > Bağlı Cihazlar > Cihaz Bağla aç.",
                        "Aşağıdaki QR’ı tara.",
                        "Eşleşme sonrası Elyan kanalı otomatik aktif olur.",
                    ],
                    qr_text=str(state.get("qrText") or ""),
                    phone=str(state.get("phone") or ""),
                    blocking_issue=last_error,
                )
            except Exception as exc:
                connected = str(adapter_status.get("whatsapp") or "").strip().lower() in {"connected", "online", "ok", "active", "healthy"}
                return _pack(
                    mode="bridge_qr",
                    status="ready" if connected else "needs_attention",
                    pending=False,
                    ready=connected,
                    detail="WhatsApp bridge erişilemiyor." if not connected else "WhatsApp adapter bağlı ama pair state okunamadı.",
                    instructions=[
                        "QR pairing’i yeniden başlat.",
                        "Node.js ve local bridge runtime’ı kontrol et.",
                    ],
                    blocking_issue=str(exc),
                )

        if ctype == "imessage":
            ready = bool(config.get("server_url")) and bool(config.get("password"))
            return _pack(
                mode="bridge_credentials",
                status="ready" if ready else "needs_credentials",
                pending=not ready,
                ready=ready,
                detail="BlueBubbles yapılandırılmış." if ready else "BlueBubbles server URL ve password gerekli.",
                instructions=[
                    "BlueBubbles server’ı macOS tarafında başlat.",
                    "Server URL ve password gir.",
                    "Sonra Messages lane otomatik hazır olur.",
                ],
                phone=str(config.get("handle") or ""),
                blocking_issue="" if ready else "bluebubbles_credentials_required",
            )

        if ctype == "telegram":
            configured = bool(config.get("token"))
            connected = str(adapter_status.get("telegram") or "").strip().lower() in {"connected", "online", "ok", "active", "healthy"}
            return _pack(
                mode="token",
                status="ready" if connected else "configured" if configured else "needs_credentials",
                pending=not connected,
                ready=connected,
                detail="Telegram bot bağlı." if connected else "Bot token kaydedildi, bağlantı testi bekliyor." if configured else "Telegram bot token gerekli.",
                instructions=[
                    "BotFather üzerinden token al.",
                    "Token’i kaydet ve test et.",
                ],
                blocking_issue="" if configured else "telegram_token_required",
            )

        if ctype == "sms":
            ready = bool(config.get("account_sid")) and bool(config.get("auth_token")) and bool(config.get("from_number"))
            return _pack(
                mode="api_credentials",
                status="ready" if ready else "needs_credentials",
                pending=not ready,
                ready=ready,
                detail="Twilio SMS lane hazır." if ready else "Twilio SID, auth token ve gönderici numara gerekli.",
                instructions=[
                    "Twilio Account SID gir.",
                    "Auth token ve gönderici numarayı kaydet.",
                    "Webhook URL’yi SMS provider tarafına tanımla.",
                ],
                blocking_issue="" if ready else "sms_credentials_required",
            )

        return _pack(
            mode="manual",
            status="unsupported",
            pending=False,
            ready=False,
            detail=f"{ctype or 'channel'} için pairing desteklenmiyor.",
            instructions=[],
            blocking_issue="pairing_unsupported",
        )

    async def _reload_channels_runtime(self) -> int:
        await self.router.stop_all()
        self.router.adapters.clear()
        self.webchat_adapter = None
        await self._init_adapters()
        await self.router.start_all()
        return len(self.router.adapters)

    async def handle_channels_catalog(self, request):
        catalog = [
            {
                "type": "telegram",
                "label": "Telegram",
                "setup_mode": "token",
                "supports_pairing": False,
                "minimal_fields": ["token"],
                "automation_hint": "Bot token kaydet, Elyan kanalı ve test akışını kendi toparlasın.",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "token", "label": "Bot Token", "required": True, "secret": True},
                ],
            },
            {
                "type": "discord",
                "label": "Discord",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "token", "label": "Bot Token", "required": True, "secret": True},
                ],
            },
            {
                "type": "slack",
                "label": "Slack",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "bot_token", "label": "Bot Token", "required": True, "secret": True},
                    {"name": "app_token", "label": "App Token", "required": False, "secret": True},
                ],
            },
            {
                "type": "whatsapp",
                "label": "WhatsApp",
                "setup_mode": "bridge_qr",
                "supports_pairing": True,
                "minimal_fields": ["mode"],
                "automation_hint": "Varsayılan bridge ayarları ve token otomatik hazırlanır; QR ile eşleştir.",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "mode", "label": "Mode (bridge/cloud)", "required": False, "secret": False},
                    {"name": "bridge_url", "label": "Bridge URL", "required": False, "secret": False},
                    {"name": "bridge_token", "label": "Bridge Token", "required": False, "secret": True},
                    {"name": "bridge_port", "label": "Bridge Port", "required": False, "secret": False},
                    {"name": "session_dir", "label": "Session Dir", "required": False, "secret": False},
                    {"name": "phone_number_id", "label": "Cloud Phone Number ID", "required": False, "secret": False},
                    {"name": "access_token", "label": "Cloud Access Token", "required": False, "secret": True},
                    {"name": "verify_token", "label": "Cloud Verify Token", "required": False, "secret": True},
                    {"name": "webhook_path", "label": "Webhook Path", "required": False, "secret": False},
                ],
                "notes": "Bridge için `elyan channels login whatsapp`; Cloud için mode=cloud + /whatsapp/webhook",
            },
            {
                "type": "imessage",
                "label": "iMessage",
                "setup_mode": "bridge_credentials",
                "supports_pairing": False,
                "minimal_fields": ["server_url", "password"],
                "automation_hint": "BlueBubbles hazırsa yalnız URL ve password yeterli.",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "server_url", "label": "BlueBubbles Server URL", "required": True, "secret": False},
                    {"name": "password", "label": "BlueBubbles Password", "required": True, "secret": True},
                    {"name": "handle", "label": "Handle", "required": False, "secret": False},
                ],
                "notes": "BlueBubbles sunucusu ile iMessage read/send lane’i açılır.",
            },
            {
                "type": "sms",
                "label": "SMS",
                "setup_mode": "api_credentials",
                "supports_pairing": False,
                "minimal_fields": ["account_sid", "auth_token", "from_number"],
                "automation_hint": "Twilio REST + webhook ile SMS lane’i bağlanır.",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "account_sid", "label": "Twilio Account SID", "required": True, "secret": False},
                    {"name": "auth_token", "label": "Twilio Auth Token", "required": True, "secret": True},
                    {"name": "from_number", "label": "Twilio From Number", "required": True, "secret": False},
                    {"name": "webhook_path", "label": "Webhook Path", "required": False, "secret": False},
                ],
                "notes": "Twilio ile SMS send/read lane’i açılır. Varsayılan webhook: /sms/webhook",
            },
            {
                "type": "signal",
                "label": "Signal",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                    {"name": "phone_number", "label": "Phone Number", "required": True, "secret": False},
                    {"name": "token", "label": "Token", "required": False, "secret": True},
                ],
            },
            {
                "type": "webchat",
                "label": "WebChat",
                "fields": [
                    {"name": "id", "label": "ID", "required": False, "secret": False},
                ],
            },
        ]
        return web.json_response({"ok": True, "catalog": catalog})

    async def handle_channel_upsert(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        incoming = data.get("channel", data)
        if not isinstance(incoming, dict):
            return web.json_response({"ok": False, "error": "channel object required"}, status=400)

        ctype = _normalize_channel_type(incoming.get("type"))
        if not ctype:
            return web.json_response({"ok": False, "error": "type required"}, status=400)

        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        cid = str(incoming.get("id") or "").strip() or ctype
        original_id = str(incoming.get("original_id") or data.get("original_id") or "").strip()
        idx = None
        existing: dict = {}
        for i, ch in enumerate(channels):
            if not isinstance(ch, dict):
                continue
            ch_id = _channel_id(ch)
            ch_type = _normalize_channel_type(ch.get("type"))
            if (original_id and original_id == ch_id) or cid == ch_id or (ch_type == ctype and not incoming.get("id")):
                idx = i
                existing = dict(ch)
                break

        merged = dict(existing)
        merged["type"] = ctype
        merged["id"] = cid
        merged["enabled"] = bool(incoming.get("enabled", existing.get("enabled", True)))
        merged["workspace_id"] = str(incoming.get("workspace_id") or existing.get("workspace_id") or "local-workspace").strip() or "local-workspace"

        clear_secret_fields = data.get("clear_secret_fields", [])
        if not isinstance(clear_secret_fields, list):
            clear_secret_fields = []
        clear_secret_fields = {str(x).strip() for x in clear_secret_fields if str(x).strip()}

        # Merge non-secret fields first.
        for k, v in incoming.items():
            key = str(k or "").strip()
            if not key or key in {"type", "id", "original_id", "original_type", "clear_secret_fields"}:
                continue
            if key in {"token", "bot_token", "app_token", "bridge_token", "access_token", "verify_token", "password"}:
                continue
            if v is None:
                continue
            merged[key] = v

        # Merge secret fields with keychain support.
        secret_fields = {"token", "bot_token", "app_token", "bridge_token", "access_token", "verify_token", "password", "auth_token"}
        for field in secret_fields:
            if field in clear_secret_fields:
                merged.pop(field, None)
                continue

            raw_val = incoming.get(field, None)
            if raw_val is None:
                continue
            value = str(raw_val).strip()
            if not value:
                # Blank means "keep existing" unless explicit clear requested.
                continue
            if value.startswith("$"):
                merged[field] = value
                continue

            env_key = _channel_secret_env(field, ctype)
            if env_key:
                keychain_key = KeychainManager.key_for_env(env_key)
                if keychain_key and KeychainManager.is_available():
                    try:
                        if KeychainManager.set_key(keychain_key, value):
                            merged[field] = f"${env_key}"
                            continue
                    except Exception:
                        pass
            merged[field] = value

        # Normalize known defaults.
        if ctype == "whatsapp":
            mode = str(merged.get("mode") or "bridge").strip().lower()
            if mode not in {"bridge", "cloud"}:
                mode = "bridge"
            merged["mode"] = mode
            if mode == "cloud":
                merged.setdefault("webhook_path", "/whatsapp/webhook")
                merged.setdefault("graph_base_url", "https://graph.facebook.com/v20.0")
                merged.setdefault("auto_start_bridge", False)
            else:
                merged.setdefault("bridge_host", "127.0.0.1")
                merged.setdefault("bridge_port", 18792)
                merged.setdefault("bridge_url", f"http://127.0.0.1:{int(merged.get('bridge_port', 18792))}")
                merged.setdefault("auto_start_bridge", True)
                merged.setdefault("client_id", cid)
                if not str(merged.get("session_dir") or "").strip():
                    merged["session_dir"] = str(default_session_dir(cid))
                if not str(merged.get("bridge_token") or "").strip():
                    bridge_secret = generate_bridge_token()
                    env_key = _channel_secret_env("bridge_token", ctype)
                    if env_key:
                        keychain_key = KeychainManager.key_for_env(env_key)
                        if keychain_key and KeychainManager.set_key(keychain_key, bridge_secret):
                            merged["bridge_token"] = f"${env_key}"
                        else:
                            merged["bridge_token"] = bridge_secret
                    else:
                        merged["bridge_token"] = bridge_secret
        if ctype == "sms":
            merged.setdefault("provider", "twilio")
            merged.setdefault("webhook_path", "/sms/webhook")

        if idx is None:
            channels.append(merged)
        else:
            channels[idx] = merged

        elyan_config.set("channels", channels)

        sync_now = bool(data.get("sync", True))
        runtime_total = len(self.router.adapters)
        if sync_now:
            try:
                runtime_total = await self._reload_channels_runtime()
            except Exception as e:
                logger.error(f"Channel upsert sync failed: {e}")

        push_activity("channel_upsert", ctype, f"{cid} saved", True)
        return web.json_response(
            {
                "ok": True,
                "channel": _mask_sensitive_fields(merged),
                "runtime_adapters": runtime_total,
            }
        )

    async def handle_channel_toggle(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"ok": False, "error": "invalid json"}, status=400)

        target = str(data.get("id") or data.get("type") or "").strip()
        if not target:
            return web.json_response({"ok": False, "error": "id required"}, status=400)
        enabled = bool(data.get("enabled", True))

        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        found = None
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            if target in {_channel_id(ch), _normalize_channel_type(ch.get("type"))}:
                ch["enabled"] = enabled
                found = ch
                break
        if not found:
            return web.json_response({"ok": False, "error": "channel not found"}, status=404)

        elyan_config.set("channels", channels)
        runtime_total = await self._reload_channels_runtime()
        push_activity("channel_toggle", str(found.get("type") or target), f"{target} -> {'on' if enabled else 'off'}", True)
        return web.json_response(
            {
                "ok": True,
                "channel": _mask_sensitive_fields(found),
                "runtime_adapters": runtime_total,
            }
        )

    async def handle_channel_delete(self, request):
        target = str(request.match_info.get("id", "")).strip()
        if not target:
            return web.json_response({"ok": False, "error": "id required"}, status=400)

        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        removed = None
        kept = []
        for ch in channels:
            if not isinstance(ch, dict):
                continue
            if target in {_channel_id(ch), _normalize_channel_type(ch.get("type"))} and removed is None:
                removed = ch
                continue
            kept.append(ch)

        if removed is None:
            return web.json_response({"ok": False, "error": "channel not found"}, status=404)

        elyan_config.set("channels", kept)
        runtime_total = await self._reload_channels_runtime()
        push_activity("channel_delete", str(removed.get("type") or target), f"{target} removed", True)
        return web.json_response(
            {
                "ok": True,
                "removed": _mask_sensitive_fields(removed),
                "runtime_adapters": runtime_total,
            }
        )

    async def handle_channels_test(self, request):
        try:
            data = await request.json()
        except Exception:
            data = {}

        requested = str(data.get("channel", "tümü") or "tümü").strip().lower()
        status_map = self.router.get_adapter_status() if hasattr(self.router, "get_adapter_status") else {}

        if requested in {"tümü", "all", "*"}:
            tested = []
            for ctype, status in status_map.items():
                tested.append({"channel": ctype, "status": status, "connected": status == "connected"})
            any_connected = any(item["connected"] for item in tested)
            return web.json_response(
                {
                    "ok": bool(tested),
                    "connected": any_connected,
                    "message": f"{len(tested)} kanal kontrol edildi.",
                    "results": tested,
                }
            )

        status = status_map.get(requested)
        if status is None:
            return web.json_response({"ok": False, "message": f"Kanal bulunamadı: {requested}"}, status=404)

        return web.json_response(
            {
                "ok": True,
                "connected": status == "connected",
                "message": f"{requested}: {status}",
                "result": {"channel": requested, "status": status, "connected": status == "connected"},
            }
        )

    async def handle_channels_sync(self, request):
        try:
            total = await self._reload_channels_runtime()
            return web.json_response({"ok": True, "message": f"Senkronizasyon tamamlandı ({total} adapter)."})
        except Exception as e:
            logger.error(f"Channels sync failed: {e}")
            return web.json_response({"ok": False, "message": f"Senkronizasyon hatası: {e}"}, status=500)

    async def handle_channel_pair_start(self, request):
        try:
            data = await request.json()
        except Exception:
            data = {}

        ctype = _normalize_channel_type(str(data.get("channel") or "whatsapp"))
        if ctype != "whatsapp":
            payload = self._build_channel_pair_status_payload(ctype)
            payload["ok"] = False
            return web.json_response(payload, status=400)

        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []
        channel_id = str(data.get("id") or "whatsapp").strip() or "whatsapp"
        existing_index = None
        existing: dict[str, Any] = {}
        for idx, item in enumerate(channels):
            if not isinstance(item, dict):
                continue
            if _normalize_channel_type(str(item.get("type") or "")) == ctype and _channel_id(item) == channel_id:
                existing_index = idx
                existing = dict(item)
                break

        bridge_host = str(existing.get("bridge_host") or BRIDGE_HOST)
        bridge_port = int(existing.get("bridge_port") or DEFAULT_BRIDGE_PORT)
        bridge_url = str(existing.get("bridge_url") or build_bridge_url(bridge_host, bridge_port)).rstrip("/")
        session_dir = Path(str(existing.get("session_dir") or default_session_dir(channel_id))).expanduser()
        bridge_secret, unresolved_token = _resolve_channel_secret("bridge_token", ctype, existing.get("bridge_token"))
        if unresolved_token:
            return web.json_response(
                {
                    "ok": False,
                    "channel": ctype,
                    "blocking_issue": "bridge_token_unresolved",
                },
                status=500,
            )
        if not bridge_secret:
            bridge_secret = generate_bridge_token()

        try:
            ensure_bridge_runtime(force_install=False)
            try:
                health = bridge_health(bridge_url, token=bridge_secret, timeout_s=1.0)
                state = health.get("state", {}) if isinstance(health, dict) else {}
                if not bool((state or {}).get("ready") or (state or {}).get("hasQr")):
                    raise BridgeRuntimeError("bridge_not_ready")
            except Exception:
                start_bridge_process(
                    session_dir=session_dir,
                    token=bridge_secret,
                    host=bridge_host,
                    port=bridge_port,
                    print_qr=False,
                    detached=True,
                    client_id=channel_id,
                )
                wait_for_bridge(
                    bridge_url=bridge_url,
                    token=bridge_secret,
                    timeout_s=15,
                    require_connected=False,
                    poll_interval_s=1.0,
                )
        except Exception as exc:
            return web.json_response(
                {
                    "ok": False,
                    "channel": ctype,
                    "blocking_issue": str(exc),
                },
                status=500,
            )

        bridge_token_ref = bridge_secret
        env_key = _channel_secret_env("bridge_token", ctype)
        if env_key:
            keychain_key = KeychainManager.key_for_env(env_key)
            if keychain_key and KeychainManager.set_key(keychain_key, bridge_secret):
                bridge_token_ref = f"${env_key}"

        merged = {
            **existing,
            "type": ctype,
            "id": channel_id,
            "enabled": True,
            "workspace_id": str(data.get("workspace_id") or existing.get("workspace_id") or "local-workspace").strip() or "local-workspace",
            "mode": "bridge",
            "bridge_host": bridge_host,
            "bridge_port": bridge_port,
            "bridge_url": bridge_url,
            "bridge_token": bridge_token_ref,
            "session_dir": str(session_dir),
            "client_id": str(existing.get("client_id") or channel_id),
            "auto_start_bridge": True,
        }
        if existing_index is None:
            channels.append(merged)
        else:
            channels[existing_index] = merged
        elyan_config.set("channels", channels)

        runtime_total = len(self.router.adapters)
        try:
            runtime_total = await self._reload_channels_runtime()
        except Exception as exc:
            logger.error(f"Channel pairing runtime sync failed: {exc}")

        payload = self._build_channel_pair_status_payload(ctype)
        payload.update(
            {
                "ok": True,
                "channel_config": _mask_sensitive_fields(merged),
                "runtime_adapters": runtime_total,
            }
        )
        push_activity("channel_pair", ctype, f"{channel_id} pairing started", True)
        return web.json_response(payload)

    async def handle_channel_pair_status(self, request):
        ctype = _normalize_channel_type(str(request.query.get("channel") or "whatsapp"))
        return web.json_response(self._build_channel_pair_status_payload(ctype))

    # ── External message ──────────────────────────────────────────────────────
    async def handle_external_message(self, request):
        try:
            data = await request.json()
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)
        text = data.get("text")
        if not text:
            return web.json_response({"error": "text required"}, status=400)
        channel = str(data.get("channel", "api") or "api")
        wait_response = bool(data.get("wait", False))
        timeout_s = data.get("timeout_s", 90)
        try:
            timeout_s = max(5, min(300, int(timeout_s)))
        except Exception:
            timeout_s = 90

        push_activity("message", channel, str(text)[:60])
        metadata = dict(data.get("metadata") or {}) if isinstance(data.get("metadata"), dict) else {}
        for key in ("user_id", "device_id", "session_id", "channel_session_id", "client_id"):
            value = data.get(key)
            if value not in (None, ""):
                metadata[key] = value

        if wait_response:
            try:
                verdict = await inspect_ingress(
                    str(text),
                    platform_origin=f"api:{channel}",
                    agent=self.agent,
                    metadata={
                        **metadata,
                        "channel_type": channel,
                        "user_id": str(metadata.get("user_id") or ""),
                    },
                )
                if not verdict.get("allowed", True):
                    return web.json_response(
                        {"status": "blocked", "error": blocked_ingress_text(verdict), "reason": verdict.get("reason", "blocked")},
                        status=403,
                    )
                out = await asyncio.wait_for(
                    self.agent.process(
                        str(text),
                        channel=channel,
                        metadata=metadata or None,
                    ),
                    timeout=timeout_s,
                )
                return web.json_response({"status": "ok", "response": str(out or "")})
            except asyncio.TimeoutError:
                return web.json_response({"status": "timeout", "error": f"message processing timed out ({timeout_s}s)"}, status=504)
            except Exception as e:
                return web.json_response({"status": "error", "error": str(e)}, status=500)

        verdict = await inspect_ingress(
            str(text),
            platform_origin=f"api:{channel}",
            agent=self.agent,
            metadata={
                **metadata,
                "channel_type": channel,
                "user_id": str(metadata.get("user_id") or ""),
            },
        )
        if not verdict.get("allowed", True):
            return web.json_response(
                {"status": "blocked", "error": blocked_ingress_text(verdict), "reason": verdict.get("reason", "blocked")},
                status=403,
            )

        asyncio.create_task(
            self.agent.process(
                str(text),
                channel=channel,
                metadata=metadata or None,
            )
        )
        return web.json_response({"status": "processing"})

    # ── Webhook ───────────────────────────────────────────────────────────────
    async def handle_webhook(self, request):
        event = request.match_info.get('event')
        try:
            data = await request.json()
            logger.info(f"Webhook received: {event}")
            verdict = await inspect_ingress(
                f"webhook_event: {event} data: {data}",
                platform_origin=f"webhook:{event}",
                agent=self.agent,
                metadata={"channel_type": "webhook", "event": str(event or "")},
            )
            if not verdict.get("allowed", True):
                return web.json_response({"status": "blocked", "error": blocked_ingress_text(verdict)}, status=403)
            asyncio.create_task(self.agent.process(f"webhook_event: {event} data: {data}"))
            push_activity("webhook", event, str(data)[:60])
            return web.json_response({"status": "ok"})
        except Exception:
            return web.json_response({"error": "invalid json"}, status=400)

    async def handle_whatsapp_webhook_verify(self, request):
        adapter = self.router.adapters.get("whatsapp")
        if not adapter:
            return web.Response(text="whatsapp adapter not active", status=404)
        handler = getattr(adapter, "handle_webhook_verification", None)
        if not callable(handler):
            return web.Response(text="whatsapp adapter webhook verify unsupported", status=400)
        return await handler(request)

    async def handle_whatsapp_webhook(self, request):
        adapter = self.router.adapters.get("whatsapp")
        if not adapter:
            return web.json_response({"ok": False, "error": "whatsapp adapter not active"}, status=404)
        handler = getattr(adapter, "handle_webhook", None)
        if not callable(handler):
            return web.json_response({"ok": False, "error": "whatsapp adapter webhook unsupported"}, status=400)
        return await handler(request)

    async def handle_sms_webhook(self, request):
        adapter = self.router.adapters.get("sms")
        if not adapter:
            return web.Response(text="sms adapter not active", status=404)
        handler = getattr(adapter, "handle_webhook", None)
        if not callable(handler):
            return web.Response(text="sms adapter webhook unsupported", status=400)
        return await handler(request)

    # ── WebChat WS ────────────────────────────────────────────────────────────
    async def handle_webchat_ws(self, request):
        if self.webchat_adapter:
            return await self.webchat_adapter.handle_ws(request)
        return web.Response(status=404, text="WebChat not enabled")

    # ── Adapter init ──────────────────────────────────────────────────────────
    async def _init_adapters(self):
        from .adapters import get_adapter_class

        channels = elyan_config.get("channels", [])
        if not isinstance(channels, list):
            channels = []

        registered_types = set()

        for ch in channels:
            if not isinstance(ch, dict) or not ch.get("enabled", True):
                continue
            ctype = str(ch.get("type") or "").strip().lower()
            try:
                adapter_cls = get_adapter_class(ctype)
                if adapter_cls is None:
                    logger.warning(f"Adapter {ctype} skipped: unsupported channel type")
                    continue

                adapter = adapter_cls(ch)
                if ctype == "webchat":
                    self.webchat_adapter = adapter
                self.router.register_adapter(str(ctype).strip().lower(), adapter)
                registered_types.add(ctype)
            except ImportError as e:
                logger.warning(f"Adapter {ctype} skipped: {e}")
            except Exception as e:
                logger.error(f"Adapter {ctype} init failed: {e}")

        # ── Auto-detect from env tokens if not already registered ──
        env_channels = {
            "telegram": "TELEGRAM_BOT_TOKEN",
            "discord": "DISCORD_BOT_TOKEN",
        }
        for ctype, env_key in env_channels.items():
            if ctype in registered_types:
                continue
            token = os.environ.get(env_key, "").strip()
            if not token:
                continue
            try:
                adapter_cls = get_adapter_class(ctype)
                if adapter_cls is None:
                    continue
                ch_cfg = {"type": ctype, "enabled": True, "token": token}
                adapter = adapter_cls(ch_cfg)
                self.router.register_adapter(ctype, adapter)
                registered_types.add(ctype)
                logger.info(f"Auto-detected {ctype} from {env_key}")
            except Exception as e:
                logger.warning(f"Auto-detect {ctype} failed: {e}")

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    async def start(self, host="127.0.0.1", port=18789):
        global _start_time
        _start_time = time.time()
        logger.info(f"Starting Gateway Server on {host}:{port}...")
        await self._init_adapters()
        await self.router.start_all()
        await self.cron.start()
        self._sync_all_routines_to_cron()
        await self.heartbeat.start()
        self.runner = web.AppRunner(self.app)
        await self.runner.setup()
        site = web.TCPSite(self.runner, host, port)
        await site.start()
        logger.info(f"Gateway server ready at http://{host}:{port}")

        try:
            await self.autopilot.start(agent=self.agent, notify_callback=self.broadcast_to_dashboard)
        except Exception as e:
            logger.error(f"Autopilot start failed: {e}")

        # Phase 20: Start Automation Scheduler
        try:
            from core.automation_registry import automation_registry
            await automation_registry.start_scheduler(self.agent)
        except Exception as e:
            logger.error(f"Automation scheduler start failed: {e}")

        # Phase 21: Start Dashboard Telemetry Broadcast
        self._telemetry_task = asyncio.create_task(self._telemetry_broadcast_loop())

        # v2: Start Mission Scheduler
        await self.scheduler.start()

        try:
            from core.persistence import RuntimeSyncWorker

            self._runtime_sync_worker = RuntimeSyncWorker()
            await self._runtime_sync_worker.start()
        except Exception as e:
            logger.error(f"Runtime sync worker start failed: {e}")

        # ── Elyan Services (Faz 1-7) ────────────────────────────────────────
        try:
            from core.elyan.elyan_startup import start_elyan_services

            def _elyan_broadcast(event_type: str, payload: dict) -> None:
                asyncio.create_task(
                    self.broadcast_to_dashboard(event_type, payload)
                )

            asyncio.create_task(start_elyan_services(broadcast=_elyan_broadcast))
            logger.info("Elyan services scheduled for startup")
        except Exception as e:
            logger.warning(f"Elyan services startup failed (non-critical): {e}")

    async def stop(self):
        logger.info("Stopping Gateway Server...")

        # ── Elyan Services shutdown ──────────────────────────────────────────
        try:
            from core.elyan.elyan_startup import stop_elyan_services
            await stop_elyan_services()
        except Exception as e:
            logger.warning(f"Elyan services stop failed: {e}")

        try:
            from core.away_mode import background_task_runner
            await background_task_runner.stop_resume_loop()
        except Exception as e:
            logger.error(f"Away resume loop stop failed: {e}")
        try:
            from core.automation_registry import automation_registry
            await automation_registry.stop_scheduler()
        except Exception as e:
            logger.error(f"Automation scheduler stop failed: {e}")
        if self._runtime_sync_worker:
            try:
                await self._runtime_sync_worker.stop()
            except Exception as e:
                logger.error(f"Runtime sync worker stop failed: {e}")
            finally:
                self._runtime_sync_worker = None
        if self._telemetry_task:
            self._telemetry_task.cancel()
            try:
                await self._telemetry_task
            except asyncio.CancelledError:
                pass
            finally:
                self._telemetry_task = None
        try:
            await self.autopilot.stop()
        except Exception as e:
            logger.error(f"Autopilot stop failed: {e}")
        await self.scheduler.stop()
        await self.heartbeat.stop()
        await self.cron.stop()
        if self.runner:
            await self.runner.cleanup()
        await self.router.stop_all()

    async def _telemetry_broadcast_loop(self):
        """Broadcast health telemetry to all dashboard clients every 5s."""
        while True:
            try:
                if _dashboard_ws_clients:
                    # Reuse handle_health_telemetry logic or call it
                    # Since handle_health_telemetry returns web.Response, we need a clean dict
                    data = await self._get_telemetry_data()
                    await self.broadcast_to_dashboard("telemetry", data)
            except Exception as e:
                logger.error(f"Telemetry broadcast error: {e}")
            await asyncio.sleep(5)

    async def handle_autopilot_status(self, request):
        autopilot = get_autopilot()
        return web.json_response(autopilot.get_status())

    async def handle_autopilot_tick(self, request):
        autopilot = get_autopilot()
        payload: dict[str, Any] = {}
        try:
            data = await request.json()
            if isinstance(data, dict):
                payload = data
        except Exception:
            payload = {}
        reason = str(payload.get("reason") or "manual_api").strip() or "manual_api"
        result = await autopilot.run_tick(agent=self.agent, reason=reason)
        return web.json_response({"ok": True, "autopilot": result})

    async def handle_autopilot_start(self, request):
        autopilot = get_autopilot()
        result = await autopilot.start(agent=self.agent, notify_callback=self.broadcast_to_dashboard)
        return web.json_response({"ok": True, "autopilot": result})

    async def handle_autopilot_stop(self, request):
        autopilot = get_autopilot()
        result = await autopilot.stop()
        return web.json_response({"ok": True, "autopilot": result})

    async def _get_telemetry_data(self) -> dict:
        """Internal helper for telemetry data."""
        from core.model_orchestrator import model_orchestrator
        from core.resilience.circuit_breaker import resilience_manager
        from core.llm.token_budget import token_budget
        from core.automation_registry import automation_registry
        from core.monitoring import get_resource_monitor, get_monitoring
        
        monitor = get_resource_monitor()
        mon = get_monitoring()
        hw = monitor.get_health_snapshot()
        orchestration = mon.get_orchestration_summary()
        pipeline_jobs = mon.get_pipeline_job_summary()
        active_automations = automation_registry.get_active()
        module_health = automation_registry.get_module_health(limit=8)
        
        return {
            "timestamp": time.time(),
            "hardware": {
                "cpu": hw.cpu_percent,
                "ram": hw.ram_percent,
                "disk": hw.disk_percent,
                "on_ac": hw.is_on_ac
            },
            "resilience": {
                "providers": model_orchestrator.get_health_report(),
                "circuits": resilience_manager.get_all_states(),
                "budget": token_budget.get_usage_summary()
            },
            "automations": {
                "active_count": len(active_automations),
                "module_health": module_health,
            },
            "orchestration": orchestration,
            "pipeline_jobs": pipeline_jobs,
            "uptime_s": int(time.time() - _start_time)
        }

    async def broadcast_to_dashboard(self, event_type: str, data: dict):
        """Send event to all active dashboard WS clients."""
        if not _dashboard_ws_clients:
            return
        
        payload = json.dumps({"type": event_type, "event": event_type, "data": data})
        for ws in list(_dashboard_ws_clients):
            try:
                await ws.send_str(payload)
            except Exception:
                _dashboard_ws_clients.remove(ws)
