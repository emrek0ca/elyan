from __future__ import annotations

import asyncio
import copy
import contextvars
import ipaddress
import json
import os
import re
import socket
import sys
import time
import uuid
from importlib import import_module
from pathlib import Path
from threading import Event, RLock, Thread, Timer
from typing import Any, Callable
from urllib.parse import urlsplit

from runtime.capability_registry import SafeCapabilityError
from runtime import state_store


_LOCAL_SERVER_LIMIT = 12
_REMOTE_SERVER_LIMIT = 12
_TOTAL_SERVER_LIMIT = _LOCAL_SERVER_LIMIT + _REMOTE_SERVER_LIMIT
# Keep the callable inventory broad enough for several curated apps while still
# bounding memory and untrusted server responses. Prompt exposure is a separate,
# deliberately smaller budget so inventory tools remain addressable by exact id.
_TOOL_INVENTORY_LIMIT = 256
_PLANNER_TOOL_LIMIT = 12
_REMOTE_SERVER_PROVIDER: Callable[[], list[dict[str, Any]] | dict[str, Any]] | None = None
_REMOTE_PROVIDER_LOCK = RLock()
_REMOTE_PROVIDER_GENERATION = 0
_REMOTE_REFRESH_TTL_SECONDS = 5.0
_REFRESH_DISCOVERY_CONCURRENCY = 4
_REFRESH_DISCOVERY_DEADLINE_SECONDS = 20.0
_CONTROL_PLANE_DNS_TIMEOUT_SECONDS = 3.0
_MAX_TASK_SCOPES = 128
_MAX_CALLS_PER_TASK_SCOPE = 8
_OWNER_ENDED_SCOPE_RETENTION_SECONDS = 30.0

# Control-plane inventory is not user configuration: every URL must match the
# reviewed app/provider endpoint exactly before an ephemeral bearer token can
# be attached. Local user-managed streamable HTTP and stdio configs continue
# through the existing, deliberately separate normalization path.
_CONTROL_PLANE_MCP_ENDPOINTS: dict[tuple[str, str], str] = {
    ("gmail", "google"): "https://gmailmcp.googleapis.com/mcp/v1",
    ("google-drive", "google"): "https://drivemcp.googleapis.com/mcp/v1",
    ("google-calendar", "google"): "https://calendarmcp.googleapis.com/mcp/v1",
    ("notion", "notion"): "https://mcp.notion.com/mcp",
    ("linear", "linear"): "https://mcp.linear.app/mcp",
    ("github", "github"): "https://api.githubcopilot.com/mcp/",
    ("slack", "slack"): "https://mcp.slack.com/mcp",
}


class _TaskCancellationScope:
    def __init__(self, task_id: str) -> None:
        self.task_id = task_id
        self.scope_id = uuid.uuid4().hex
        self.cancelled = Event()
        self.reason = ""
        self._lock = RLock()
        self._calls: dict[int, tuple[asyncio.AbstractEventLoop, asyncio.Task[Any]]] = {}
        self._owner_ended = False
        self._owner_cleanup_generation = 0
        self._owner_cleanup_deadline = 0.0

    def register_call(
        self,
        loop: asyncio.AbstractEventLoop,
        task: asyncio.Task[Any],
    ) -> int:
        with self._lock:
            if self.cancelled.is_set():
                raise SafeCapabilityError("TASK_CANCELLED", "Görev iptal edildi.")
            if len(self._calls) >= _MAX_CALLS_PER_TASK_SCOPE:
                raise SafeCapabilityError("MCP_BUSY", "Bu görev için çok fazla MCP işlemi çalışıyor.")
            call_id = id(task)
            self._calls[call_id] = (loop, task)
            return call_id

    def unregister_call(self, call_id: int, task: asyncio.Task[Any]) -> bool:
        with self._lock:
            current = self._calls.get(call_id)
            if current is not None and current[1] is task:
                self._calls.pop(call_id, None)
            return self._owner_ended and not self._calls

    def end_owner(self) -> tuple[bool, int, bool]:
        with self._lock:
            newly_ended = not self._owner_ended
            if newly_ended:
                self._owner_ended = True
                self._owner_cleanup_generation += 1
                self._owner_cleanup_deadline = (
                    time.monotonic() + max(0.01, float(_OWNER_ENDED_SCOPE_RETENTION_SECONDS))
                )
            return not self._calls, self._owner_cleanup_generation, newly_ended

    def cleanup_due(self, generation: int) -> bool:
        with self._lock:
            return bool(
                self._owner_ended
                and generation == self._owner_cleanup_generation
                and self._owner_cleanup_deadline > 0.0
                and time.monotonic() >= self._owner_cleanup_deadline
            )

    def cancel(self, reason: str) -> int:
        normalized_reason = str(reason or "task_cancelled").strip() or "task_cancelled"
        with self._lock:
            if not self.reason or normalized_reason == "task_cancelled":
                self.reason = normalized_reason
            self.cancelled.set()
            calls = list(self._calls.values())
        scheduled = 0
        for loop, task in calls:
            try:
                # Task state is owned by its event-loop thread. Schedule the
                # cancellation directly instead of reading task.done() here.
                loop.call_soon_threadsafe(task.cancel)
                scheduled += 1
            except (RuntimeError, AttributeError):
                continue
        return scheduled


class _TaskScopeToken:
    def __init__(
        self,
        scope: _TaskCancellationScope,
        context_token: contextvars.Token[_TaskCancellationScope | None],
    ) -> None:
        self.scope = scope
        self.context_token = context_token


_TASK_SCOPE_CONTEXT: contextvars.ContextVar[_TaskCancellationScope | None] = contextvars.ContextVar(
    "elyan_mcp_task_scope",
    default=None,
)
_TASK_SCOPES_LOCK = RLock()
_TASK_SCOPES: dict[str, dict[str, _TaskCancellationScope]] = {}


def _remove_task_scope(scope: _TaskCancellationScope) -> None:
    with _TASK_SCOPES_LOCK:
        task_scopes = _TASK_SCOPES.get(scope.task_id, {})
        if task_scopes.get(scope.scope_id) is scope:
            task_scopes.pop(scope.scope_id, None)
        if not task_scopes:
            _TASK_SCOPES.pop(scope.task_id, None)


def _force_remove_task_scope(scope: _TaskCancellationScope, generation: int) -> None:
    # Timers are generation- and identity-fenced: a delayed callback can never
    # remove a newer scope that happens to reuse the same task id.
    if scope.cleanup_due(generation):
        _remove_task_scope(scope)


def begin_task_scope(task_id: str) -> _TaskScopeToken:
    normalized = str(task_id or "").strip()[:160]
    if not normalized:
        raise SafeCapabilityError("TASK_ID_REQUIRED", "Görev kimliği gerekli.")
    scope = _TaskCancellationScope(normalized)
    with _TASK_SCOPES_LOCK:
        active_count = sum(len(scopes) for scopes in _TASK_SCOPES.values())
        if active_count >= _MAX_TASK_SCOPES:
            raise SafeCapabilityError("TASK_SCOPE_LIMIT", "Çok fazla görev aynı anda çalışıyor.")
        _TASK_SCOPES.setdefault(normalized, {})[scope.scope_id] = scope
    try:
        context_token = _TASK_SCOPE_CONTEXT.set(scope)
    except BaseException:
        with _TASK_SCOPES_LOCK:
            task_scopes = _TASK_SCOPES.get(normalized, {})
            task_scopes.pop(scope.scope_id, None)
            if not task_scopes:
                _TASK_SCOPES.pop(normalized, None)
        raise
    return _TaskScopeToken(scope, context_token)


def end_task_scope(token: _TaskScopeToken | None) -> None:
    if not isinstance(token, _TaskScopeToken):
        return
    try:
        _TASK_SCOPE_CONTEXT.reset(token.context_token)
    except (ValueError, LookupError):
        pass
    # The owner may time out while the async session is still unwinding.
    # Retain the bounded registry entry until the final call unregisters so a
    # repeated cancel can still reach that loop/task; then clean it exactly once.
    empty, generation, newly_ended = token.scope.end_owner()
    if empty:
        _remove_task_scope(token.scope)
    elif newly_ended:
        cleanup_timer = Timer(
            max(0.01, float(_OWNER_ENDED_SCOPE_RETENTION_SECONDS)),
            _force_remove_task_scope,
            args=(token.scope, generation),
        )
        cleanup_timer.daemon = True
        cleanup_timer.start()


def current_task_id() -> str:
    scope = _TASK_SCOPE_CONTEXT.get()
    return scope.task_id if isinstance(scope, _TaskCancellationScope) else ""


def task_cancellation_reason(task_id: str) -> str:
    normalized = str(task_id or "").strip()
    current = _TASK_SCOPE_CONTEXT.get()
    if isinstance(current, _TaskCancellationScope) and current.task_id == normalized and current.cancelled.is_set():
        return current.reason or "task_cancelled"
    with _TASK_SCOPES_LOCK:
        scopes = list(_TASK_SCOPES.get(normalized, {}).values())
    for scope in scopes:
        if scope.cancelled.is_set():
            return scope.reason or "task_cancelled"
    return ""


def cancel_task(task_id: str, *, reason: str = "task_cancelled") -> int:
    normalized = str(task_id or "").strip()
    if not normalized:
        return 0
    with _TASK_SCOPES_LOCK:
        scopes = list(_TASK_SCOPES.get(normalized, {}).values())
    return sum(scope.cancel(reason) for scope in scopes)


def _utc_now_iso() -> str:
    import datetime as dt

    return dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _module_available(module_name: str) -> bool:
    try:
        import_module(module_name)
        return True
    except Exception:
        return False


def _safe_json(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except Exception:
        return value


def _string(value: Any, *, limit: int = 400) -> str:
    return " ".join(str(value or "").split()).strip()[:limit]


def _slug(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", _string(value, limit=120).lower())
    return normalized.strip("-") or "server"


def _as_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _as_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [_string(item, limit=500) for item in value if _string(item, limit=500)]
    if isinstance(value, str):
        parts = [part.strip() for part in value.splitlines()]
        return [part for part in parts if part]
    return []


def _stdio_command(value: Any) -> str:
    command = str(value or "").strip()
    if not command:
        return command
    # Generic Python commands often resolve to the OS Python instead of the
    # packaged/runtime interpreter that has Elyan optional deps installed.
    # Absolute commands remain user-controlled.
    if os.path.isabs(command):
        return command
    if Path(command).name.lower() in {"python", "python3", "python.exe"} and sys.executable:
        return sys.executable
    return command


def _base_status() -> dict[str, Any]:
    sdk_available = _module_available("mcp")
    return {
        "available": True,
        "sdkAvailable": sdk_available,
        "lastRefreshAt": "",
        "serverCount": 0,
        "servers": [],
        "tools": [],
        "toolCount": 0,
        "lastErrorCode": "",
        "lastErrorMessage": "",
        "degraded": False,
        "remoteRevision": "",
    }


def _resolve_cwd(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    resolved = Path(raw).expanduser()
    if not resolved.is_absolute():
        resolved = (Path.cwd() / resolved).resolve()
    else:
        resolved = resolved.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP çalışma dizini geçerli değil.")
    return str(resolved)


def _remote_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlsplit(raw)
    if parsed.scheme == "https" and parsed.hostname:
        return raw
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return raw
    raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu adresi güvenli değil.")


def _control_plane_remote_url(value: Any, *, app_id: str, provider: str) -> str:
    expected = _CONTROL_PLANE_MCP_ENDPOINTS.get((app_id, provider))
    if not expected:
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP uygulaması güvenilir katalogda değil.")
    raw = str(value or "").strip()
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu adresi güvenli değil.") from exc
    expected_url = urlsplit(expected)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != expected_url.hostname
        or port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.query
        or parsed.path != expected_url.path
    ):
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu adresi güvenilir katalogla eşleşmiyor.")
    return expected


async def _control_plane_address_info(hostname: str) -> list[Any]:
    loop = asyncio.get_running_loop()
    future: asyncio.Future[list[Any]] = loop.create_future()

    def resolve() -> None:
        try:
            result = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
            error: OSError | None = None
        except OSError as exc:
            result = []
            error = exc

        def deliver() -> None:
            if future.done():
                return
            if error is not None:
                future.set_exception(error)
            else:
                future.set_result(result)

        try:
            loop.call_soon_threadsafe(deliver)
        except RuntimeError:
            return

    resolver = Thread(target=resolve, name="elyan-mcp-dns", daemon=True)
    resolver.start()
    return await asyncio.wait_for(
        future,
        timeout=max(0.1, float(_CONTROL_PLANE_DNS_TIMEOUT_SECONDS)),
    )


async def _validate_control_plane_resolution(server: dict[str, Any]) -> None:
    if not bool(server.get("_controlPlaneRemote", False)):
        return
    app_id = _string(server.get("appId"), limit=80).lower()
    provider = _string(server.get("provider"), limit=80).lower()
    trusted_url = _control_plane_remote_url(server.get("url"), app_id=app_id, provider=provider)
    hostname = str(urlsplit(trusted_url).hostname or "").strip()
    try:
        address_info = await _control_plane_address_info(hostname)
    except (OSError, asyncio.TimeoutError) as exc:
        raise SafeCapabilityError("MCP_SERVER_UNAVAILABLE", "MCP sunucu adresi çözümlenemedi.") from exc
    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for item in address_info:
        try:
            raw_address = str(item[4][0]).split("%", 1)[0]
            addresses.add(ipaddress.ip_address(raw_address))
        except (IndexError, TypeError, ValueError):
            continue
    if not addresses or any(
        not address.is_global
        or address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
        for address in addresses
    ):
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu adresi güvenli bir genel ağa çözülmedi.")


def _validate_control_plane_provider_generation(server: dict[str, Any]) -> None:
    if not bool(server.get("_controlPlaneRemote", False)):
        return
    try:
        snapshot_generation = int(server.get("_remoteProviderGeneration", -1))
    except (TypeError, ValueError):
        snapshot_generation = -1
    if snapshot_generation < 0 or snapshot_generation != _remote_provider_generation():
        raise SafeCapabilityError(
            "MCP_CONTROL_PLANE_CHANGED",
            "Bağlı uygulama oturumu değişti; araç çağrısını yeniden başlat.",
        )


def normalize_server_config(
    raw: dict[str, Any],
    *,
    existing_id: str = "",
    source: str = "local",
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu yapılandırması geçerli değil.")
    normalized_source = str(source or "local").strip().lower()
    if normalized_source not in {"local", "control_plane"}:
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu kaynağı geçerli değil.")
    server_id = _string(raw.get("id") or existing_id, limit=80)
    name = _string(raw.get("name"), limit=120)
    command = str(raw.get("command", "") or "").strip()
    if not server_id:
        server_id = f"mcp_{_slug(name or command or uuid.uuid4().hex[:8])}_{uuid.uuid4().hex[:6]}"
    if not name:
        name = command or server_id
    transport = _string(raw.get("transport") or "stdio", limit=32).lower() or "stdio"
    if transport not in {"stdio", "streamable_http"}:
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP taşıma türü desteklenmiyor.")
    if transport == "stdio" and not command:
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP komutu gerekli.")
    app_id = _string(raw.get("appId"), limit=80).lower()
    provider = _string(raw.get("provider"), limit=80).lower()
    if transport == "streamable_http":
        if normalized_source == "control_plane":
            url = _control_plane_remote_url(
                raw.get("url") or raw.get("baseUrl"),
                app_id=app_id,
                provider=provider,
            )
        else:
            url = _remote_url(raw.get("url") or raw.get("baseUrl"))
    else:
        url = ""
    config = {
        "id": server_id,
        "name": name,
        "transport": transport,
        "command": command,
        "args": _as_string_list(raw.get("args")),
        "cwd": _resolve_cwd(str(raw.get("cwd", "") or "")) if transport == "stdio" else "",
        "url": url,
        "enabled": bool(raw.get("enabled", True)),
        "startupTimeoutSec": _as_int(raw.get("startupTimeoutSec", 15), 15, minimum=3, maximum=120),
        "callTimeoutSec": _as_int(raw.get("callTimeoutSec", 45), 45, minimum=5, maximum=180),
    }
    if transport == "streamable_http":
        config.update(
            {
                "appId": app_id,
                "provider": provider,
                "authType": _string(raw.get("authType") or "none", limit=32).lower(),
                "accessToken": str(raw.get("accessToken", "") or "").strip(),
                "authErrorCode": _string(raw.get("authErrorCode"), limit=80),
            }
        )
        if normalized_source == "control_plane":
            config["_controlPlaneRemote"] = True
    return config


def _server_configs_from_state(state: dict[str, Any]) -> list[dict[str, Any]]:
    skills = state.get("skills", {})
    if not isinstance(skills, dict):
        return []
    servers = skills.get("mcpServers", [])
    if not isinstance(servers, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for item in servers:
        if not isinstance(item, dict):
            continue
        try:
            config = normalize_server_config(item, existing_id=str(item.get("id", "") or ""))
        except SafeCapabilityError:
            fallback_id = _string(item.get("id"), limit=80) or f"mcp_invalid_{uuid.uuid4().hex[:6]}"
            config = {
                "id": fallback_id,
                "name": _string(item.get("name") or fallback_id, limit=120),
                "transport": "stdio",
                "command": str(item.get("command", "") or "").strip(),
                "args": _as_string_list(item.get("args")),
                "cwd": str(item.get("cwd", "") or "").strip(),
                "enabled": bool(item.get("enabled", True)),
                "startupTimeoutSec": _as_int(item.get("startupTimeoutSec", 15), 15, minimum=3, maximum=120),
                "callTimeoutSec": _as_int(item.get("callTimeoutSec", 45), 45, minimum=5, maximum=180),
                "_invalid": True,
            }
        server_id = str(config.get("id", "") or "").strip()
        if not server_id or server_id in seen_ids:
            continue
        seen_ids.add(server_id)
        normalized.append(config)
        if len(normalized) >= _LOCAL_SERVER_LIMIT:
            break
    return normalized


def set_remote_server_provider(
    provider: Callable[[], list[dict[str, Any]] | dict[str, Any]] | None,
) -> None:
    global _REMOTE_SERVER_PROVIDER, _REMOTE_PROVIDER_GENERATION
    with _REMOTE_PROVIDER_LOCK:
        _REMOTE_SERVER_PROVIDER = provider
        _REMOTE_PROVIDER_GENERATION += 1
    manager = globals().get("_MANAGER")
    if manager is not None:
        manager.invalidate_remote()


def _remote_provider_generation() -> int:
    with _REMOTE_PROVIDER_LOCK:
        return _REMOTE_PROVIDER_GENERATION


def _remote_provider_configured() -> bool:
    with _REMOTE_PROVIDER_LOCK:
        return callable(_REMOTE_SERVER_PROVIDER)


def _remote_server_snapshot() -> tuple[list[dict[str, Any]], dict[str, str], int]:
    with _REMOTE_PROVIDER_LOCK:
        provider = _REMOTE_SERVER_PROVIDER
        generation = _REMOTE_PROVIDER_GENERATION
    status = {"errorCode": "", "errorMessage": "", "revision": ""}
    if not callable(provider):
        return [], status, generation
    try:
        payload = provider()
    except Exception:
        status = {
            "errorCode": "MCP_CONTROL_PLANE_UNAVAILABLE",
            "errorMessage": "Bağlı uygulamalar şu anda yenilenemiyor.",
            "revision": "",
        }
        return [], status, generation
    if isinstance(payload, dict):
        raw_servers = payload.get("servers", [])
        status = {
            "errorCode": _string(payload.get("errorCode"), limit=80),
            "errorMessage": _string(payload.get("errorMessage"), limit=240),
            "revision": _string(payload.get("revision"), limit=128),
        }
    else:
        raw_servers = payload
    if not isinstance(raw_servers, list):
        status = {
            "errorCode": "MCP_CONTROL_PLANE_UNAVAILABLE",
            "errorMessage": "Bağlı uygulama yanıtı geçerli değil.",
            "revision": "",
        }
        return [], status, generation
    normalized: list[dict[str, Any]] = []
    rejected = 0
    for raw in raw_servers:
        if not isinstance(raw, dict):
            rejected += 1
            continue
        if len(normalized) >= _REMOTE_SERVER_LIMIT:
            break
        try:
            config = normalize_server_config(
                raw,
                existing_id=str(raw.get("id", "") or ""),
                source="control_plane",
            )
            config["_remoteProviderGeneration"] = generation
            normalized.append(config)
        except SafeCapabilityError:
            rejected += 1
            continue
    if rejected and not status["errorCode"]:
        status = {
            **status,
            "errorCode": "MCP_CONTROL_PLANE_INVALID",
            "errorMessage": "Bağlı uygulama kataloğunda güvenilir olmayan bir sunucu reddedildi.",
        }
    return normalized, status, generation


def _remote_server_configs() -> list[dict[str, Any]]:
    servers, _status, _generation = _remote_server_snapshot()
    return servers


def _merge_server_configs(
    local_servers: list[dict[str, Any]],
    remote_servers: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    combined: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for server in [*local_servers, *remote_servers]:
        server_id = str(server.get("id", "") or "").strip()
        if not server_id or server_id in seen_ids:
            continue
        seen_ids.add(server_id)
        combined.append(server)
        if len(combined) >= _TOTAL_SERVER_LIMIT:
            break
    return combined


def _configured_servers(state: dict[str, Any]) -> list[dict[str, Any]]:
    return _merge_server_configs(_server_configs_from_state(state), _remote_server_configs())


def _extract_text_block(content_block: Any) -> str:
    text = getattr(content_block, "text", None)
    if text:
        return _string(text, limit=4000)
    try:
        dumped = content_block.model_dump(exclude_none=True)
    except Exception:
        dumped = None
    if isinstance(dumped, dict):
        if isinstance(dumped.get("text"), str):
            return _string(dumped["text"], limit=4000)
        return _string(json.dumps(dumped, ensure_ascii=False), limit=4000)
    return _string(content_block, limit=4000)


def _normalize_schema(schema: Any) -> dict[str, Any]:
    if isinstance(schema, dict):
        payload = _safe_json(schema)
        return payload if isinstance(payload, dict) else {}
    try:
        dumped = schema.model_dump(exclude_none=True)
    except Exception:
        dumped = None
    return dumped if isinstance(dumped, dict) else {}


def _scan_artifacts(value: Any, *, limit: int = 3) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []

    def visit(candidate: Any) -> None:
        if len(artifacts) >= limit:
            return
        if isinstance(candidate, dict):
            for key, nested in candidate.items():
                key_name = str(key or "").lower()
                if key_name.endswith("path") or key_name in {"path", "file", "file_path", "output", "output_path"}:
                    if isinstance(nested, str) and ("/" in nested or "\\" in nested or Path(nested).suffix):
                        path = nested.strip()
                        if path:
                            artifacts.append(
                                {
                                    "kind": "file",
                                    "path": path,
                                    "label": Path(path).name or path,
                                }
                            )
                            if len(artifacts) >= limit:
                                return
                visit(nested)
        elif isinstance(candidate, list):
            for nested in candidate:
                visit(nested)
                if len(artifacts) >= limit:
                    return

    visit(value)
    deduped: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for item in artifacts:
        path = str(item.get("path", "") or "").strip()
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        deduped.append(item)
    return deduped[:limit]


class MCPRuntimeManager:
    def __init__(self) -> None:
        self._lock = RLock()
        self._refresh_lock = RLock()
        self._status = _base_status()
        self._last_refresh_monotonic = 0.0

    def invalidate_remote(self) -> None:
        with self._lock:
            self._last_refresh_monotonic = 0.0

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = copy.deepcopy(self._status)
            payload["sdkAvailable"] = _module_available("mcp")
            payload["available"] = True
            return payload

    async def _discover_tools_bounded(
        self,
        server_configs: list[dict[str, Any]],
    ) -> list[tuple[list[dict[str, Any]], tuple[str, str] | None]]:
        semaphore = asyncio.Semaphore(max(1, int(_REFRESH_DISCOVERY_CONCURRENCY)))

        async def discover(server: dict[str, Any]) -> tuple[list[dict[str, Any]], tuple[str, str] | None]:
            async with semaphore:
                try:
                    return await self._list_tools_for_server(server), None
                except SafeCapabilityError as exc:
                    return [], (exc.code, exc.message)
                except Exception:
                    return [], ("MCP_SERVER_UNAVAILABLE", "MCP sunucusuna bağlanılamadı.")

        tasks = [asyncio.create_task(discover(server)) for server in server_configs]
        if not tasks:
            return []
        try:
            done, pending = await asyncio.wait(
                tasks,
                timeout=max(0.1, float(_REFRESH_DISCOVERY_DEADLINE_SECONDS)),
            )
        except BaseException:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        outcomes: list[tuple[list[dict[str, Any]], tuple[str, str] | None]] = []
        for task in tasks:
            if task not in done:
                outcomes.append(([], ("MCP_TOOL_TIMEOUT", "MCP keşfi zaman aşımına uğradı.")))
                continue
            try:
                outcomes.append(task.result())
            except (asyncio.CancelledError, RuntimeError):
                outcomes.append(([], ("MCP_TOOL_TIMEOUT", "MCP keşfi zaman aşımına uğradı.")))
        return outcomes

    def _build_refresh_status(
        self,
        current_state: dict[str, Any],
    ) -> tuple[dict[str, Any], int]:
        status = _base_status()
        status["lastRefreshAt"] = _utc_now_iso()
        tools: list[dict[str, Any]] = []
        servers: list[dict[str, Any]] = []
        remote_servers, remote_status, provider_generation = _remote_server_snapshot()
        configured_servers = _merge_server_configs(
            _server_configs_from_state(current_state),
            remote_servers,
        )
        entries: list[tuple[dict[str, Any], dict[str, Any] | None]] = []
        discovery_servers: list[dict[str, Any]] = []

        for server in configured_servers:
            server_payload = {
                "id": str(server.get("id", "") or ""),
                "name": str(server.get("name", "") or ""),
                "transport": str(server.get("transport", "stdio") or "stdio"),
                "appId": str(server.get("appId", "") or ""),
                "enabled": bool(server.get("enabled", True)),
                "connected": False,
                "toolCount": 0,
                "startupTimeoutSec": _as_int(server.get("startupTimeoutSec", 15), 15, minimum=3, maximum=120),
                "callTimeoutSec": _as_int(server.get("callTimeoutSec", 45), 45, minimum=5, maximum=180),
                "sdkAvailable": bool(status["sdkAvailable"]),
                "lastErrorCode": "",
                "lastErrorMessage": "",
                "lastRefreshAt": status["lastRefreshAt"],
            }
            if server.get("_invalid"):
                server_payload["lastErrorCode"] = "MCP_SERVER_INVALID"
                server_payload["lastErrorMessage"] = "MCP sunucu yapılandırması geçerli değil."
                entries.append((server_payload, None))
                continue
            if not server_payload["enabled"]:
                server_payload["lastErrorCode"] = "MCP_SERVER_DISABLED"
                server_payload["lastErrorMessage"] = "MCP sunucusu kapalı."
                entries.append((server_payload, None))
                continue
            if not status["sdkAvailable"]:
                server_payload["lastErrorCode"] = "DEPENDENCY_UNAVAILABLE"
                server_payload["lastErrorMessage"] = "MCP Python SDK bu kurulumda hazır değil."
                entries.append((server_payload, None))
                continue
            if str(server.get("authErrorCode", "") or "").strip():
                server_payload["lastErrorCode"] = "MCP_AUTH_REQUIRED"
                server_payload["lastErrorMessage"] = "Uygulama bağlantısının yeniden yetkilendirilmesi gerekiyor."
                entries.append((server_payload, None))
                continue
            entries.append((server_payload, server))
            discovery_servers.append(server)

        discovery_outcomes = (
            asyncio.run(self._discover_tools_bounded(discovery_servers))
            if discovery_servers
            else []
        )
        discovery_index = 0
        for server_payload, discovery_server in entries:
            if discovery_server is not None:
                discovered, error = discovery_outcomes[discovery_index]
                discovery_index += 1
                if error is None:
                    server_payload["connected"] = True
                    server_payload["toolCount"] = len(discovered)
                    tools.extend(discovered)
                else:
                    server_payload["lastErrorCode"] = error[0]
                    server_payload["lastErrorMessage"] = error[1]
            servers.append(server_payload)

        status["servers"] = servers[:_TOTAL_SERVER_LIMIT]
        status["serverCount"] = len(status["servers"])
        status["tools"] = tools[:_TOOL_INVENTORY_LIMIT]
        status["toolCount"] = len(status["tools"])
        first_failure = next(
            (
                item
                for item in status["servers"]
                if isinstance(item, dict) and str(item.get("lastErrorCode", "") or "").strip()
            ),
            {},
        )
        status["lastErrorCode"] = str(first_failure.get("lastErrorCode", "") or "").strip()
        status["lastErrorMessage"] = str(first_failure.get("lastErrorMessage", "") or "").strip()
        remote_error_code = str(remote_status.get("errorCode", "") or "").strip()
        if remote_error_code:
            status["degraded"] = True
            if not status["lastErrorCode"]:
                status["lastErrorCode"] = remote_error_code
                status["lastErrorMessage"] = str(
                    remote_status.get("errorMessage", "")
                    or "Bağlı uygulamalar şu anda yenilenemiyor."
                ).strip()
        status["remoteRevision"] = str(remote_status.get("revision", "") or "").strip()
        return status, provider_generation

    def refresh(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        # Discovery can run network sessions and is intentionally serialized.
        # This keeps each published server/tool inventory paired with the exact
        # control-plane revision that produced it.
        with self._refresh_lock:
            status: dict[str, Any] = _base_status()
            provider_generation = -1
            for _attempt in range(2):
                status, provider_generation = self._build_refresh_status(current_state)
                if provider_generation == _remote_provider_generation():
                    break
            # Compare and publish while the provider generation is fenced. A
            # concurrent setter either happens before this block (mismatch) or
            # afterwards and invalidates the freshly published cache.
            with _REMOTE_PROVIDER_LOCK:
                generation_stable = provider_generation == _REMOTE_PROVIDER_GENERATION
                if not generation_stable:
                    status["degraded"] = True
                    status["lastErrorCode"] = "MCP_CONTROL_PLANE_CHANGED"
                    status["lastErrorMessage"] = "Bağlı uygulama kataloğu yenileme sırasında değişti."
                with self._lock:
                    if generation_stable:
                        self._status = copy.deepcopy(status)
                        self._last_refresh_monotonic = time.monotonic()
                    else:
                        # Keep the cache invalidated; the next bounded read retries.
                        self._last_refresh_monotonic = 0.0
            return copy.deepcopy(status)

    def list_tools(self, state: dict[str, Any] | None = None, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            return self.refresh(state)
        status = self.status()
        remote_provider_configured = _remote_provider_configured()
        with self._lock:
            remote_refresh_due = remote_provider_configured and (
                time.monotonic() - self._last_refresh_monotonic >= _REMOTE_REFRESH_TTL_SECONDS
            )
        if status.get("lastRefreshAt") and not remote_refresh_due:
            return status
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        if remote_refresh_due:
            return self.refresh(current_state)
        if any(server.get("enabled", True) for server in _configured_servers(current_state)):
            return self.refresh(current_state)
        return status

    def planner_prompt_context(self, state: dict[str, Any] | None = None) -> str:
        status = self.list_tools(state, refresh=False)
        tools = status.get("tools", [])
        if not isinstance(tools, list) or not tools:
            return ""
        lines = [
            "Discovered MCP tools. Use capability=mcp_call_tool only with one of these exact tools.",
        ]
        for item in tools[:_PLANNER_TOOL_LIMIT]:
            if not isinstance(item, dict):
                continue
            schema = item.get("inputSchema", {})
            schema_summary = ""
            if isinstance(schema, dict):
                properties = schema.get("properties", {})
                if isinstance(properties, dict) and properties:
                    schema_summary = ", ".join(
                        f"{key}:{str((value or {}).get('type', 'any')).lower()}"
                        for key, value in list(properties.items())[:6]
                        if isinstance(value, dict)
                    )
            lines.append(
                f"- serverId={item.get('serverId', '')} toolName={item.get('name', '')} "
                f"readOnly={bool(item.get('readOnly', False))} "
                f"description={_string(item.get('description', ''), limit=160)} "
                f"schema={schema_summary or 'none'}"
            )
        lines.append(
            "If you choose mcp_call_tool, args must contain serverId, toolName, and arguments."
        )
        return "\n".join(lines)

    def tool_metadata(
        self,
        server_id: str,
        tool_name: str,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        status = self.list_tools(state, refresh=False)
        tools = status.get("tools", [])
        if not isinstance(tools, list):
            tools = []
        target_server_id = str(server_id or "").strip()
        target_tool_name = str(tool_name or "").strip()
        for item in tools:
            if not isinstance(item, dict):
                continue
            if str(item.get("serverId", "") or "").strip() != target_server_id:
                continue
            if str(item.get("name", "") or "").strip() != target_tool_name:
                continue
            return copy.deepcopy(item)
        if state is not None:
            refreshed = self.refresh(state)
            for item in refreshed.get("tools", []):
                if not isinstance(item, dict):
                    continue
                if str(item.get("serverId", "") or "").strip() != target_server_id:
                    continue
                if str(item.get("name", "") or "").strip() != target_tool_name:
                    continue
                return copy.deepcopy(item)
        return None

    def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        *,
        state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        if not _module_available("mcp"):
            raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "MCP Python SDK bu kurulumda hazır değil.")
        target_server = None
        for server in _configured_servers(current_state):
            if str(server.get("id", "") or "").strip() == str(server_id or "").strip():
                target_server = server
                break
        if not isinstance(target_server, dict) or target_server.get("_invalid"):
            raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu yapılandırması geçerli değil.")
        if not bool(target_server.get("enabled", True)):
            raise SafeCapabilityError("MCP_SERVER_UNAVAILABLE", "MCP sunucusu etkin değil.")
        metadata = self.tool_metadata(str(server_id or ""), str(tool_name or ""), current_state)
        if metadata is None:
            raise SafeCapabilityError("MCP_TOOL_NOT_FOUND", "İstenen MCP aracı bulunamadı.")
        scope = _TASK_SCOPE_CONTEXT.get()
        try:
            # Direct CLI/local calls deliberately retain the original one-shot
            # asyncio.run path. Remote tasks carry a copied ContextVar scope so
            # task.cancel can reach the exact loop/task from another thread.
            if isinstance(scope, _TaskCancellationScope):
                return asyncio.run(
                    self._call_tool_for_task_scope(
                        scope,
                        target_server,
                        str(tool_name or "").strip(),
                        arguments if isinstance(arguments, dict) else {},
                    )
                )
            return asyncio.run(
                self._call_tool_for_server(
                    target_server,
                    str(tool_name or "").strip(),
                    arguments if isinstance(arguments, dict) else {},
                )
            )
        except SafeCapabilityError:
            raise
        except Exception:
            raise SafeCapabilityError("MCP_SERVER_UNAVAILABLE", "MCP aracı güvenli şekilde çağrılamadı.")

    async def _call_tool_for_task_scope(
        self,
        scope: _TaskCancellationScope,
        server: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        if task is None:  # pragma: no cover - asyncio always owns this coroutine
            raise SafeCapabilityError("MCP_SERVER_UNAVAILABLE", "MCP aracı güvenli şekilde çağrılamadı.")
        call_id = scope.register_call(loop, task)
        try:
            result = await self._call_tool_for_server(server, tool_name, arguments)
            # Cancellation may race with a successful response before the
            # event loop runs task.cancel. Never release that late success.
            if scope.cancelled.is_set():
                raise asyncio.CancelledError
            return result
        except asyncio.CancelledError as exc:
            # _call_tool_for_server has already unwound its async session
            # contexts at this point; only the stable safe error crosses IPC.
            raise SafeCapabilityError("TASK_CANCELLED", "Görev iptal edildi.") from exc
        finally:
            if scope.unregister_call(call_id, task):
                _remove_task_scope(scope)

    async def _list_tools_for_server(self, server: dict[str, Any]) -> list[dict[str, Any]]:
        session, _types = _mcp_client_components()
        if session is None or _types is None:
            raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "MCP Python SDK bu kurulumda hazır değil.")
        result = await self._with_session(
            server,
            lambda session_obj: asyncio.wait_for(
                session_obj.list_tools(),
                timeout=float(server.get("callTimeoutSec", 45) or 45),
            ),
        )
        tools = getattr(result, "tools", None)
        if not isinstance(tools, list):
            return []
        discovered: list[dict[str, Any]] = []
        for tool in tools:
            annotations = getattr(tool, "annotations", None)
            reported_read_only = bool(getattr(annotations, "readOnlyHint", False))
            # Remote annotations are controlled by a third party and cannot
            # authorize an action. Until Elyan has a reviewed per-tool policy,
            # every remote MCP call remains confirmation-gated.
            read_only = reported_read_only and str(server.get("transport", "stdio")) == "stdio"
            discovered.append(
                {
                    "serverId": str(server.get("id", "") or ""),
                    "serverName": str(server.get("name", "") or ""),
                    "name": str(getattr(tool, "name", "") or ""),
                    "description": _string(getattr(tool, "description", "") or getattr(tool, "title", "") or "", limit=240),
                    "readOnly": read_only,
                    "reportedReadOnly": reported_read_only,
                    "inputSchema": _normalize_schema(getattr(tool, "inputSchema", None)),
                    "available": True,
                    "availabilityReason": "",
                }
            )
            if len(discovered) >= _TOOL_INVENTORY_LIMIT:
                break
        return discovered

    async def _call_tool_for_server(
        self,
        server: dict[str, Any],
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        result = await self._with_session(
            server,
            lambda session_obj: asyncio.wait_for(
                session_obj.call_tool(tool_name, arguments=arguments),
                timeout=float(server.get("callTimeoutSec", 45) or 45),
            ),
        )
        if bool(getattr(result, "isError", False)):
            message = ""
            content = getattr(result, "content", None)
            if isinstance(content, list):
                parts = [_extract_text_block(item) for item in content]
                message = "\n".join(part for part in parts if part).strip()
            raise SafeCapabilityError("MCP_TOOL_NOT_FOUND", message or "MCP aracı hata döndürdü.")
        content_blocks = getattr(result, "content", None)
        content_text = ""
        if isinstance(content_blocks, list):
            text_parts = [_extract_text_block(item) for item in content_blocks]
            content_text = "\n".join(part for part in text_parts if part).strip()
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            structured_result: dict[str, Any] | None = dict(structured)
        elif structured is not None:
            structured_result = {"result": _safe_json(structured)}
        else:
            structured_result = None
        artifacts = _scan_artifacts(structured_result if structured_result is not None else content_text)
        if structured_result is None:
            structured_result = {}
        structured_result.update(
            {
                "kind": "mcp_call_tool",
                "serverId": str(server.get("id", "") or ""),
                "toolName": tool_name,
            }
        )
        output = content_text or _string(json.dumps(structured_result, ensure_ascii=False), limit=4000)
        # Kanıt sözleşmesi ("prove it"): MCP aracının gerçekten çalıştığı
        # makine-okur alanla işaretlenir — work-order doğrulaması bunu
        # stateReadback kanıtı sayar (extract_state_readback: mcpToolExecuted).
        readback_result: dict[str, Any] = (
            dict(structured_result) if isinstance(structured_result, dict) else {}
        )
        readback_result.setdefault("mcpToolExecuted", True)
        readback_result.setdefault("mcpServerId", str(server.get("id", "") or ""))
        readback_result.setdefault("mcpToolName", tool_name)
        return {
            "output": output,
            "result": readback_result,
            "artifacts": artifacts,
        }

    async def _with_session(self, server: dict[str, Any], operation: Any) -> Any:
        session_cls, _types = _mcp_client_components()
        if session_cls is None:
            raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "MCP Python SDK bu kurulumda hazır değil.")
        from mcp import ClientSession

        try:
            if str(server.get("transport", "stdio") or "stdio") == "streamable_http":
                if str(server.get("authErrorCode", "") or "").strip():
                    raise SafeCapabilityError(
                        "MCP_AUTH_REQUIRED",
                        "Uygulama bağlantısının yeniden yetkilendirilmesi gerekiyor.",
                    )
                _validate_control_plane_provider_generation(server)
                await _validate_control_plane_resolution(server)
                import httpx
                from mcp.client.streamable_http import streamable_http_client

                access_token = str(server.get("accessToken", "") or "").strip()
                auth_type = str(server.get("authType", "none") or "none").strip().lower()
                if auth_type == "bearer" and not access_token:
                    raise SafeCapabilityError(
                        "MCP_AUTH_REQUIRED",
                        "Bu uygulamayı kullanmak için hesabını yeniden bağla.",
                    )
                headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}
                timeout = float(server.get("callTimeoutSec", 45) or 45)
                async with httpx.AsyncClient(
                    headers=headers,
                    # A control-plane redirect could turn an otherwise trusted
                    # catalog URL into SSRF. MCP endpoints must be final URLs.
                    follow_redirects=False,
                    timeout=timeout,
                ) as http_client:
                    async with streamable_http_client(
                        str(server.get("url", "") or ""),
                        http_client=http_client,
                    ) as (read, write, _session_id):
                        async with ClientSession(read, write) as session:
                            await asyncio.wait_for(
                                session.initialize(),
                                timeout=float(server.get("startupTimeoutSec", 15) or 15),
                            )
                            return await operation(session)

            from mcp import StdioServerParameters
            from mcp.client.stdio import stdio_client

            params = StdioServerParameters(
                command=_stdio_command(server.get("command", "")),
                args=list(server.get("args", []) or []),
                env=dict(os.environ),
                cwd=str(server.get("cwd", "") or "") or None,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await asyncio.wait_for(
                        session.initialize(),
                        timeout=float(server.get("startupTimeoutSec", 15) or 15),
                    )
                    return await operation(session)
        except asyncio.TimeoutError as exc:
            raise SafeCapabilityError("MCP_TOOL_TIMEOUT", "MCP işlemi zaman aşımına uğradı.") from exc
        except SafeCapabilityError:
            raise
        except FileNotFoundError as exc:
            raise SafeCapabilityError("MCP_SERVER_UNAVAILABLE", "MCP komutu bu cihazda bulunamadı.") from exc
        except Exception as exc:
            message = _string(exc, limit=300).lower()
            if "not found" in message and "tool" in message:
                raise SafeCapabilityError("MCP_TOOL_NOT_FOUND", "İstenen MCP aracı bulunamadı.") from exc
            raise SafeCapabilityError("MCP_SERVER_UNAVAILABLE", "MCP sunucusuna bağlanılamadı.") from exc


def _mcp_client_components() -> tuple[Any | None, Any | None]:
    try:
        from mcp import ClientSession, types

        return ClientSession, types
    except Exception:
        return None, None


_MANAGER = MCPRuntimeManager()


def runtime_mcp_status() -> dict[str, Any]:
    return _MANAGER.status()


def refresh_mcp_runtime(state: dict[str, Any] | None = None) -> dict[str, Any]:
    return _MANAGER.refresh(state)


def list_mcp_tools(state: dict[str, Any] | None = None, *, refresh: bool = False) -> dict[str, Any]:
    return _MANAGER.list_tools(state, refresh=refresh)


def planner_mcp_context(state: dict[str, Any] | None = None) -> str:
    return _MANAGER.planner_prompt_context(state)


def mcp_tool_metadata(server_id: str, tool_name: str, state: dict[str, Any] | None = None) -> dict[str, Any] | None:
    return _MANAGER.tool_metadata(server_id, tool_name, state)


def call_tool(server_id: str, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
    return _MANAGER.call_tool(server_id, tool_name, arguments)
