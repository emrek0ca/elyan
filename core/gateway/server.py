import asyncio
import importlib.util
import inspect
import time
import json
import os
import secrets
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse
from aiohttp import web, WSMsgType
from types import SimpleNamespace
from typing import Any, Optional, Set
from cli.onboard import _check_macos_permissions, is_setup_complete
from .router import GatewayRouter
from .response import UnifiedResponse
from core.scheduler.cron_engine import CronEngine
from core.scheduler.heartbeat import HeartbeatManager
from core.scheduler.routine_engine import routine_engine
from core.skills.manager import skill_manager
from core.subscription import subscription_manager
from core.quota import quota_manager
from core.task_brain import task_brain
from core.away_mode import away_task_registry
from core.proactive.intervention import get_intervention_manager
from core.model_catalog import default_model_for_provider
from core.tool_usage import get_tool_usage_snapshot
from core.runtime_policy import get_runtime_policy_resolver
from core.runtime import (
    EMRE_WORKFLOW_PRESETS,
    list_emre_workflow_reports,
    load_latest_benchmark_summary,
    run_emre_workflow_preset,
)
from core.storage_paths import resolve_elyan_data_dir, resolve_runs_root
from core.version import APP_VERSION
from core.compliance.audit_trail import audit_trail
from config.elyan_config import elyan_config
from security.tool_policy import tool_policy
from security.keychain import KeychainManager
from tools import AVAILABLE_TOOLS
from utils.logger import get_logger

logger = get_logger("gateway_server")

# Global WebSocket client registry for dashboard push
_dashboard_ws_clients: Set[web.WebSocketResponse] = set()
_activity_log: list = []  # Rolling buffer of last 50 events
_tool_event_log: list = []  # Rolling buffer of last 200 tool events
_start_time: float = time.time()
_tool_health_cache: dict = {
    "ts": 0.0,
    "probe": False,
    "items": {},
    "summary": {},
}
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "::ffff:127.0.0.1", "localhost"}
_ADMIN_READ_PATHS = {
    "/api/config",
    "/api/logs",
    "/api/security/events",
    "/api/security/pending",
    "/api/privacy/export",
    "/api/interventions",
    "/api/tool-requests",
    "/api/tool-requests/stats",
    "/api/tool-events",
}


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
    except Exception:
        pass
    return generated


def push_activity(event_type: str, channel: str, detail: str, success: bool = True):
    """Push an activity event to all connected dashboard WebSocket clients."""
    entry = {
        "ts": time.strftime("%H:%M:%S"),
        "type": event_type,
        "channel": channel,
        "detail": detail[:80],
        "ok": success,
    }
    _activity_log.append(entry)
    if len(_activity_log) > 50:
        _activity_log.pop(0)
    _schedule_background(_broadcast_activity, entry)


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


class ElyanGatewayServer:
    """Main HTTP/WebSocket server for the Elyan Gateway."""

    def __init__(self, agent):
        self.agent = agent
        self.router = GatewayRouter(agent)
        self.app = web.Application(middlewares=[self._cors_middleware, self._api_security_middleware])
        self.webchat_adapter: Optional[object] = None
        self.cron = CronEngine(agent)
        self.heartbeat = HeartbeatManager(agent)
        self.cron.set_report_callback(self._on_cron_report)
        self._setup_routes()
        self.runner: Optional[web.AppRunner] = None
        self._telemetry_task: Optional[asyncio.Task] = None

    def _configured_cors_origins(self) -> set[str]:
        configured = elyan_config.get("gateway.cors.origins", []) or []
        if isinstance(configured, str):
            configured = [item.strip() for item in configured.split(",") if item.strip()]
        normalized: set[str] = set()
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
        if path == "/api/message":
            return True
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            return True
        if method == "GET" and path in _ADMIN_READ_PATHS:
            return True
        return False

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
            resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,PATCH,DELETE,OPTIONS"
            resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Elyan-Admin-Token"
            resp.headers["Vary"] = "Origin"
            return resp
        resp = await handler(request)
        if allowed_origin:
            resp.headers["Access-Control-Allow-Origin"] = allowed_origin
            resp.headers["Access-Control-Allow-Credentials"] = "true"
            resp.headers["Vary"] = "Origin"
        return resp

    @web.middleware
    async def _api_security_middleware(self, request, handler):
        if self._request_requires_admin(request):
            allowed, error = self._require_admin_access(request, allow_cookie=True)
            if not allowed:
                return web.json_response({"ok": False, "error": error}, status=403)
        return await handler(request)

    def _require_admin_access(self, request, *, allow_cookie: bool = True) -> tuple[bool, str]:
        if not _is_loopback_request(request):
            return False, "admin access is restricted to localhost"
        expected = _ensure_admin_access_token()
        query = getattr(request, "query", None)
        if query is None:
            query = getattr(getattr(request, "rel_url", None), "query", {}) or {}
        candidate = str(
            request.headers.get("X-Elyan-Admin-Token", "")
            or query.get("token", "")
            or query.get("admin_token", "")
            or (request.cookies.get("elyan_admin_session", "") if allow_cookie else "")
            or ""
        ).strip()
        if not candidate or candidate != expected:
            return False, "admin token required"
        return True, ""

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
        self.app.router.add_get('/api/memory/stats', self.handle_memory_stats)
        self.app.router.add_get('/api/memory/profile', self.handle_get_profile)
        self.app.router.add_get('/api/activity', self.handle_activity_log)
        self.app.router.add_get('/api/runs/recent', self.handle_recent_runs)
        self.app.router.add_get('/api/product/home', self.handle_product_home)
        self.app.router.add_get('/api/product/workflows', self.handle_product_workflows)
        self.app.router.add_get('/api/product/workflows/reports', self.handle_product_workflow_reports)
        self.app.router.add_post('/api/product/workflows/run', self.handle_product_workflow_run)
        self.app.router.add_get('/api/routines', self.handle_routines)
        self.app.router.add_get('/api/routines/templates', self.handle_routine_templates)
        self.app.router.add_post('/api/routines/suggest', self.handle_routine_suggest)
        self.app.router.add_post('/api/routines/from-text', self.handle_routine_from_text)
        self.app.router.add_post('/api/routines', self.handle_routine_create)
        self.app.router.add_post('/api/routines/from-template', self.handle_routine_from_template)
        self.app.router.add_post('/api/routines/toggle', self.handle_routine_toggle)
        self.app.router.add_post('/api/routines/run', self.handle_routine_run)
        self.app.router.add_get('/api/routines/history', self.handle_routine_history)
        self.app.router.add_delete('/api/routines/{id}', self.handle_routine_remove)
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
        self.app.router.add_post('/api/skills/install', self.handle_skill_install)
        self.app.router.add_post('/api/skills/toggle', self.handle_skill_toggle)
        self.app.router.add_post('/api/skills/remove', self.handle_skill_remove)
        self.app.router.add_post('/api/skills/update', self.handle_skill_update)
        self.app.router.add_get('/api/skills/check', self.handle_skill_check)
        self.app.router.add_get('/api/skills/workflows', self.handle_skill_workflows)
        self.app.router.add_post('/api/skills/workflows/toggle', self.handle_skill_workflow_toggle)

        # ── Dashboard & Web UI ────────────────────────────────────────────────
        self.app.router.add_get('/', self.handle_dashboard_page)
        self.app.router.add_get('/product', self.handle_dashboard_page)
        self.app.router.add_get('/dashboard', self.handle_dashboard_page)
        self.app.router.add_get('/healthz', self.handle_product_health)
        self.app.router.add_get('/ops', self.handle_ops_console_page)
        self.app.router.add_get('/ui/web/{filename}', self.handle_web_asset)
        self.app.router.add_get('/canvas', self.handle_canvas_page)
        self.app.router.add_get('/ws/chat', self.handle_webchat_ws)
        self.app.router.add_get('/ws/dashboard', self.handle_dashboard_ws)

        # ── Webhook ───────────────────────────────────────────────────────────
        self.app.router.add_post('/hook/{event}', self.handle_webhook)
        self.app.router.add_get('/whatsapp/webhook', self.handle_whatsapp_webhook_verify)
        self.app.router.add_post('/whatsapp/webhook', self.handle_whatsapp_webhook)

        # ── Security API ─────────────────────────────────────────────────────
        self.app.router.add_get('/api/security/events', self.handle_security_events)
        self.app.router.add_get('/api/security/pending', self.handle_pending_approvals)
        self.app.router.add_post('/api/security/approve', self.handle_approve_action)
        self.app.router.add_get('/api/privacy/export', self.handle_privacy_export)
        self.app.router.add_post('/api/privacy/delete', self.handle_privacy_delete)
        self.app.router.add_get('/api/interventions', self.handle_interventions_get)
        self.app.router.add_post('/api/interventions/resolve', self.handle_interventions_resolve)
        self.app.router.add_get('/api/health/telemetry', self.handle_health_telemetry)

    # ── Page handlers ─────────────────────────────────────────────────────────
    async def handle_dashboard_page(self, request):
        base = Path(__file__).resolve().parent.parent.parent
        p = base / 'ui' / 'web' / 'dashboard.html'
        if not p.exists():
            return web.Response(text="Dashboard file not found", status=404)
        response = web.FileResponse(p)
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
        filename = str(request.match_info.get("filename", "")).strip()
        if not filename or "/" in filename or "\\" in filename or ".." in filename:
            return web.Response(text="Invalid asset path", status=400)
        base = (Path(__file__).resolve().parent.parent.parent / "ui" / "web").resolve()
        asset_path = (base / filename).resolve()
        if asset_path.parent != base or not asset_path.exists() or not asset_path.is_file():
            return web.Response(text="Asset file not found", status=404)
        return web.FileResponse(asset_path)

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
        orchestration_data = data.get("orchestration", {}) if isinstance(data.get("orchestration"), dict) else {}
        flags_data = data.get("flags", {}) if isinstance(data.get("flags"), dict) else {}
        skills_data = data.get("skills", {}) if isinstance(data.get("skills"), dict) else {}
        runtime_policy_data = data.get("runtime_policy", {}) if isinstance(data.get("runtime_policy"), dict) else {}

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
        for _name, st in (adapter_status.items() if isinstance(adapter_status, dict) else []):
            low = str(st or "").lower()
            if low in {"connected", "online", "ok", "active", "healthy"}:
                adapter_healthy += 1
            elif isinstance(st, dict):
                inner = str(st.get("status", "")).lower()
                if inner in {"connected", "online", "ok", "active", "healthy"}:
                    adapter_healthy += 1
        adapter_degraded = max(0, adapter_total - adapter_healthy)

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
            },
        }

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
            "adapters": adapter_status,
            "adapter_health": adapter_health,
            "cron_jobs": len(self.cron.scheduler.get_jobs()),
            "tool_count": tools_total,
            "tools_total": tools_total,
            "runtime_health": runtime_health,
            "runtime": {
                "uptime_seconds": uptime_s,
                "cpu_pct": health.cpu_percent,
                "ram_pct": health.ram_percent,
                "disk_pct": health.disk_percent,
                "tools_total": tools_total,
                "tool_load_errors": load_error_count,
                "channels_total": adapter_total,
                "channels_healthy": adapter_healthy,
                "channels_degraded": adapter_degraded,
                "health_status": runtime_health["status"],
                "orchestration": orchestration_summary,
                "pipeline_jobs": pipeline_jobs_summary,
            },
            "orchestration_telemetry": orchestration_summary,
            "pipeline_jobs_telemetry": pipeline_jobs_summary,
            "action_lock": {
                "is_locked": action_lock.is_locked,
                "progress": action_lock.progress,
                "message": action_lock.status_message,
                "task_id": action_lock.current_task_id
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
        desktop_state_path = resolve_elyan_data_dir() / "desktop_host" / "state.json"
        playwright_ready = importlib.util.find_spec("playwright") is not None
        telegram_status = str(adapter_status.get("telegram") or "").strip().lower()
        telegram_ready = telegram_status in {"connected", "online", "ok", "active", "healthy"}
        desktop_ready = bool(permissions.get("osascript_available")) and bool(permissions.get("screencapture_available"))
        browser_ready = bool(playwright_ready or desktop_ready)
        provider = str(model_info.get("active_provider") or "—").strip()
        model = str(model_info.get("active_model") or "—").strip()
        provider_ready = provider not in {"", "—"} and model not in {"", "—"}
        benchmark_green = int(benchmark.get("pass_count") or 0) == int(benchmark.get("total") or 0) and int(benchmark.get("total") or 0) > 0
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
                "key": "telegram",
                "label": "Telegram connection readiness",
                "ready": telegram_ready,
                "detail": telegram_status or "not_connected",
            },
            {
                "key": "browser",
                "label": "Browser readiness",
                "ready": browser_ready,
                "detail": "playwright" if playwright_ready else "screen-operator fallback",
            },
            {
                "key": "demo_workflow",
                "label": "First demo workflow execution",
                "ready": bool(recent_reports),
                "detail": str(recent_reports[0].get("workflow_name") or first_demo or "not_run") if recent_reports else (first_demo or "not_run"),
            },
        ]
        return {
            "ok": True,
            "readiness": {
                "elyan_ready": bool(status_payload.get("status") == "online" and benchmark_green and provider_ready),
                "desktop_operator_ready": desktop_ready,
                "browser_ready": browser_ready,
                "telegram_ready": telegram_ready,
                "connected_provider": provider,
                "connected_model": model,
                "runtime_health": str(((status_payload.get("runtime_health") if isinstance(status_payload.get("runtime_health"), dict) else {}) or {}).get("status") or ""),
                "desktop_state_available": desktop_state_path.exists(),
                "setup_complete": bool(is_setup_complete()),
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
                    {"label": "Telegram baglantisini kontrol et", "ready": telegram_ready},
                    {"label": "Browser hazirligini kontrol et", "ready": browser_ready},
                    {"label": "Ilk demo workflow'u calistir", "ready": bool(recent_reports)},
                ],
            },
            "release": {
                "version": str(status_payload.get("version") or ""),
                "entrypoint": "/product",
                "entrypoint_aliases": ["/", "/dashboard", "/product"],
                "health_endpoint": "/healthz",
                "health_status": str(status_payload.get("health_status") or ""),
                "benchmark_green": benchmark_green,
                "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
                "quickstart_checks": [
                    {"label": "Gateway status", "value": str(status_payload.get("status") or "unknown")},
                    {"label": "Dashboard entrypoint", "value": "/product"},
                    {"label": "Health page", "value": "/healthz"},
                    {"label": "CLI quickstart", "value": f"{cli_mod} dashboard"},
                    {"label": "Product start script", "value": "bash scripts/start_product.sh"},
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
        return web.json_response(
            {
                "ok": bool(readiness.get("elyan_ready")),
                "status": "ready" if readiness.get("elyan_ready") else "degraded",
                "version": str(release.get("version") or ""),
                "health_status": str(release.get("health_status") or ""),
                "entrypoint": str(release.get("entrypoint") or "/product"),
                "benchmark": benchmark,
                "readiness": readiness,
            }
        )

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
                return web.json_response({"ok": False, "error": "file field required"}, status=400)
            
            filename = str(field.filename or f"upload_{int(time.time())}")
            upload_dir = resolve_elyan_data_dir() / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            filepath = upload_dir / filename
            
            size = 0
            with open(filepath, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk:
                        break
                    size += len(chunk)
                    f.write(chunk)
            
            logger.info(f"File uploaded via Dashboard: {filename} ({size} bytes)")
            push_activity("upload", "dashboard", f"{filename} ({round(size/1024, 1)} KB)")
            
            # Analyze intent based on file type
            prompt = f"Dropped file: {filepath}. Lütfen bu dosyayı analiz et."
            asyncio.create_task(self.agent.process(prompt))
            
            return web.json_response({
                "ok": True, 
                "filename": filename, 
                "path": str(filepath),
                "size": size
            })
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_voice_upload(self, request):
        """POST /api/voice — Voice command upload."""
        try:
            reader = await request.multipart()
            field = await reader.next()
            if not field or field.name != 'file':
                return web.json_response({"ok": False, "error": "file field required"}, status=400)
            
            filename = f"voice_{int(time.time())}.webm"
            temp_dir = resolve_elyan_data_dir() / "tmp" / "voice"
            temp_dir.mkdir(parents=True, exist_ok=True)
            filepath = temp_dir / filename
            
            with open(filepath, 'wb') as f:
                while True:
                    chunk = await field.read_chunk()
                    if not chunk: break
                    f.write(chunk)
            
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
                
        except Exception as e:
            logger.error(f"Voice upload failed: {e}")
            return web.json_response({"ok": False, "error": str(e)}, status=500)

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

        asyncio.create_task(self.agent.process(text))
        push_activity("task_created", "dashboard", text[:60])
        return web.json_response({"status": "queued", "text": text, "intent": intent})

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

    async def handle_health_telemetry(self, request):
        """Aggregate all health and performance metrics for the live dashboard."""
        try:
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
                    "active_count": len(automation_registry.get_active()),
                    "tasks": automation_registry.get_active()[:10]
                },
                "orchestration": orchestration,
                "pipeline_jobs": pipeline_jobs,
                "uptime_s": int(time.time() - _start_time)
            })
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    # ── Activity log (new) ────────────────────────────────────────────────────
    async def handle_activity_log(self, request):
        return web.json_response({"events": list(reversed(_activity_log))})

    async def handle_recent_runs(self, request):
        """Return recent run summaries from the resolved runs root."""
        try:
            limit = int(request.rel_url.query.get("limit", 10))
        except Exception:
            limit = 10
        limit = max(1, min(50, limit))

        runs_root = resolve_runs_root().expanduser()
        if not runs_root.exists():
            return web.json_response({"runs": [], "count": 0})

        run_dirs = [p for p in runs_root.iterdir() if p.is_dir()]
        run_dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

        items = []
        for run_dir in run_dirs[:limit]:
            evidence_path = run_dir / "evidence.json"
            task_path = run_dir / "task.json"
            summary_path = run_dir / "summary.md"
            status = "unknown"
            action = ""
            error_code = ""
            duration_ms = 0
            artifacts = 0

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
                    "summary_path": str(summary_path),
                    "evidence_path": str(evidence_path),
                    "created_at": int(run_dir.stat().st_mtime),
                }
            )

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
            confidence = float(suggestion.get("confidence", 0.0) or 0.0)
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
            active_ids.add(self._routine_job_id(rid))
            self.cron.sync_job(self._routine_to_job(routine))

        # Cleanup deleted routines from cron runtime jobs.
        for job in self.cron.list_jobs():
            jid = str(job.get("id", "")).strip()
            if jid.startswith("routine:") and jid not in active_ids:
                self.cron.remove_job(jid)

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
        items = skill_manager.list_skills(available=available, enabled_only=enabled_only, query=q)
        installed = [s for s in items if s.get("installed")]
        enabled = [s for s in installed if s.get("enabled")]
        unhealthy = [s for s in installed if not s.get("health_ok")]
        runtime_ready = [s for s in installed if s.get("runtime_ready")]
        workflows = skill_manager.list_workflows()
        workflows_enabled = [w for w in workflows if w.get("enabled")]
        return web.json_response({
            "skills": items,
            "summary": {
                "total": len(items),
                "installed": len(installed),
                "enabled": len(enabled),
                "issues": len(unhealthy),
                "runtime_ready": len(runtime_ready),
                "workflows_total": len(workflows),
                "workflows_enabled": len(workflows_enabled),
            },
        })

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
        push_activity("skill_update", "dashboard", f"updated={len(result.get('updated', []))}", success=True)
        return web.json_response({"ok": True, **result})

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
        push_activity("workflow_toggle", "dashboard", f"{workflow_id}: {'on' if enabled else 'off'}", success=ok)
        return web.json_response({"ok": ok, "message": msg, "workflow": info}, status=200 if ok else 400)

    # ── WebSocket: Dashboard push (new) ───────────────────────────────────────
    async def handle_dashboard_ws(self, request):
        ws = web.WebSocketResponse(heartbeat=30)
        await ws.prepare(request)
        _dashboard_ws_clients.add(ws)
        logger.info(f"Dashboard WS connected ({len(_dashboard_ws_clients)} clients)")
        # Send recent activity on connect
        await ws.send_json({"event": "history", "data": list(reversed(_activity_log[-10:]))})
        await ws.send_json({"event": "tool_history", "data": list(reversed(_tool_event_log[-40:]))})
        try:
            async for msg in ws:
                if msg.type == WSMsgType.ERROR:
                    break
        finally:
            _dashboard_ws_clients.discard(ws)
            logger.info(f"Dashboard WS disconnected ({len(_dashboard_ws_clients)} clients)")
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
                audit_path = Path(".wiqo_audit/audit.db")
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
        """Pending approval requests."""
        pending = []
        try:
            from security.approval import approval_manager
            if hasattr(approval_manager, "pending_requests"):
                for rid, req in approval_manager.pending_requests.items():
                    pending.append({
                        "id": rid,
                        "action": str(req.action) if hasattr(req, "action") else str(req),
                        "user_id": str(req.user_id) if hasattr(req, "user_id") else "?",
                        "ts": str(req.timestamp) if hasattr(req, "timestamp") else "",
                    })
        except Exception:
            pass
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
        """Approve or reject a pending action."""
        try:
            data = await request.json()
            request_id = data.get("id")
            approved = bool(data.get("approved", False))
            from security.approval import approval_manager
            if hasattr(approval_manager, "resolve"):
                approval_manager.resolve(request_id, approved)
            return web.json_response({"ok": True})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=400)

    async def handle_privacy_export(self, request):
        """KVKK/GDPR: export user audit footprint."""
        user_id = str(request.rel_url.query.get("user_id", "") or "").strip()
        if not user_id:
            return web.json_response({"ok": False, "error": "user_id required"}, status=400)
        try:
            data = audit_trail.export_for_user(user_id)
            return web.json_response({"ok": True, "export": data})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

    async def handle_privacy_delete(self, request):
        """KVKK/GDPR: right to be forgotten (audit trail scope)."""
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        user_id = str(payload.get("user_id", "") or "").strip()
        if not user_id:
            return web.json_response({"ok": False, "error": "user_id required"}, status=400)
        try:
            result = audit_trail.delete_user_data(user_id)
            push_activity("privacy", "dashboard", f"user_data_deleted:{user_id}", True)
            return web.json_response({"ok": True, "result": result})
        except Exception as e:
            return web.json_response({"ok": False, "error": str(e)}, status=500)

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
        idx = None
        existing: dict = {}
        for i, ch in enumerate(channels):
            if not isinstance(ch, dict):
                continue
            ch_id = _channel_id(ch)
            ch_type = _normalize_channel_type(ch.get("type"))
            if cid == ch_id or (ch_type == ctype and not incoming.get("id")):
                idx = i
                existing = dict(ch)
                break

        merged = dict(existing)
        merged["type"] = ctype
        merged["id"] = cid
        merged["enabled"] = bool(incoming.get("enabled", existing.get("enabled", True)))

        clear_secret_fields = data.get("clear_secret_fields", [])
        if not isinstance(clear_secret_fields, list):
            clear_secret_fields = []
        clear_secret_fields = {str(x).strip() for x in clear_secret_fields if str(x).strip()}

        # Merge non-secret fields first.
        for k, v in incoming.items():
            key = str(k or "").strip()
            if not key or key in {"type", "id"}:
                continue
            if key in {"token", "bot_token", "app_token", "bridge_token", "access_token", "verify_token", "password"}:
                continue
            if v is None:
                continue
            merged[key] = v

        # Merge secret fields with keychain support.
        secret_fields = {"token", "bot_token", "app_token", "bridge_token", "access_token", "verify_token", "password"}
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

        if wait_response:
            try:
                out = await asyncio.wait_for(
                    self.agent.process(
                        str(text),
                        channel=channel,
                        metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
                    ),
                    timeout=timeout_s,
                )
                return web.json_response({"status": "ok", "response": str(out or "")})
            except asyncio.TimeoutError:
                return web.json_response({"status": "timeout", "error": f"message processing timed out ({timeout_s}s)"}, status=504)
            except Exception as e:
                return web.json_response({"status": "error", "error": str(e)}, status=500)

        asyncio.create_task(
            self.agent.process(
                str(text),
                channel=channel,
                metadata=data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
            )
        )
        return web.json_response({"status": "processing"})

    # ── Webhook ───────────────────────────────────────────────────────────────
    async def handle_webhook(self, request):
        event = request.match_info.get('event')
        try:
            data = await request.json()
            logger.info(f"Webhook received: {event}")
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

        # Phase 20: Start Automation Scheduler
        try:
            from core.automation_registry import automation_registry
            asyncio.create_task(automation_registry.start_scheduler(self.agent))
        except Exception as e:
            logger.error(f"Automation scheduler start failed: {e}")

        # Phase 21: Start Dashboard Telemetry Broadcast
        self._telemetry_task = asyncio.create_task(self._telemetry_broadcast_loop())

    async def stop(self):
        logger.info("Stopping Gateway Server...")
        if self._telemetry_task:
            self._telemetry_task.cancel()
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
                "active_count": len(automation_registry.get_active())
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
