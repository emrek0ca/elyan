from __future__ import annotations

import asyncio
import copy
import json
import os
import re
import sys
import uuid
from importlib import import_module
from pathlib import Path
from threading import RLock
from typing import Any

from runtime.capability_registry import SafeCapabilityError
from runtime import state_store


_SERVER_LIMIT = 12
_TOOL_LIMIT = 24


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


def normalize_server_config(raw: dict[str, Any], *, existing_id: str = "") -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP sunucu yapılandırması geçerli değil.")
    server_id = _string(raw.get("id") or existing_id, limit=80)
    name = _string(raw.get("name"), limit=120)
    command = str(raw.get("command", "") or "").strip()
    if not server_id:
        server_id = f"mcp_{_slug(name or command or uuid.uuid4().hex[:8])}_{uuid.uuid4().hex[:6]}"
    if not name:
        name = command or server_id
    transport = _string(raw.get("transport") or "stdio", limit=32).lower() or "stdio"
    if transport != "stdio":
        raise SafeCapabilityError("MCP_SERVER_INVALID", "Bu sürüm yalnız stdio MCP sunucularını destekliyor.")
    if not command:
        raise SafeCapabilityError("MCP_SERVER_INVALID", "MCP komutu gerekli.")
    return {
        "id": server_id,
        "name": name,
        "transport": "stdio",
        "command": command,
        "args": _as_string_list(raw.get("args")),
        "cwd": _resolve_cwd(str(raw.get("cwd", "") or "")),
        "enabled": bool(raw.get("enabled", True)),
        "startupTimeoutSec": _as_int(raw.get("startupTimeoutSec", 15), 15, minimum=3, maximum=120),
        "callTimeoutSec": _as_int(raw.get("callTimeoutSec", 45), 45, minimum=5, maximum=180),
    }


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
        if len(normalized) >= _SERVER_LIMIT:
            break
    return normalized


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
        self._status = _base_status()

    def status(self) -> dict[str, Any]:
        with self._lock:
            payload = copy.deepcopy(self._status)
            payload["sdkAvailable"] = _module_available("mcp")
            payload["available"] = True
            return payload

    def refresh(self, state: dict[str, Any] | None = None) -> dict[str, Any]:
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        status = _base_status()
        status["lastRefreshAt"] = _utc_now_iso()
        tools: list[dict[str, Any]] = []
        servers: list[dict[str, Any]] = []

        for server in _server_configs_from_state(current_state):
            server_payload = {
                "id": str(server.get("id", "") or ""),
                "name": str(server.get("name", "") or ""),
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
                servers.append(server_payload)
                continue
            if not server_payload["enabled"]:
                server_payload["lastErrorCode"] = "MCP_SERVER_DISABLED"
                server_payload["lastErrorMessage"] = "MCP sunucusu kapalı."
                servers.append(server_payload)
                continue
            if not status["sdkAvailable"]:
                server_payload["lastErrorCode"] = "DEPENDENCY_UNAVAILABLE"
                server_payload["lastErrorMessage"] = "MCP Python SDK bu kurulumda hazır değil."
                servers.append(server_payload)
                continue
            try:
                discovered = asyncio.run(self._list_tools_for_server(server))
                server_payload["connected"] = True
                server_payload["toolCount"] = len(discovered)
                servers.append(server_payload)
                tools.extend(discovered)
            except SafeCapabilityError as exc:
                server_payload["lastErrorCode"] = exc.code
                server_payload["lastErrorMessage"] = exc.message
                servers.append(server_payload)
            except Exception:
                server_payload["lastErrorCode"] = "MCP_SERVER_UNAVAILABLE"
                server_payload["lastErrorMessage"] = "MCP sunucusuna bağlanılamadı."
                servers.append(server_payload)

        status["servers"] = servers[:_SERVER_LIMIT]
        status["serverCount"] = len(status["servers"])
        status["tools"] = tools[:_TOOL_LIMIT]
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
        with self._lock:
            self._status = copy.deepcopy(status)
        return copy.deepcopy(status)

    def list_tools(self, state: dict[str, Any] | None = None, *, refresh: bool = False) -> dict[str, Any]:
        if refresh:
            return self.refresh(state)
        status = self.status()
        if status.get("lastRefreshAt"):
            return status
        current_state = state if isinstance(state, dict) else state_store.snapshot()
        if any(server.get("enabled", True) for server in _server_configs_from_state(current_state)):
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
        for item in tools[:12]:
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
        for server in _server_configs_from_state(current_state):
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
        try:
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
            read_only = bool(getattr(annotations, "readOnlyHint", False))
            discovered.append(
                {
                    "serverId": str(server.get("id", "") or ""),
                    "serverName": str(server.get("name", "") or ""),
                    "name": str(getattr(tool, "name", "") or ""),
                    "description": _string(getattr(tool, "description", "") or getattr(tool, "title", "") or "", limit=240),
                    "readOnly": read_only,
                    "inputSchema": _normalize_schema(getattr(tool, "inputSchema", None)),
                    "available": True,
                    "availabilityReason": "",
                }
            )
            if len(discovered) >= _TOOL_LIMIT:
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
        return {
            "output": output,
            "result": structured_result,
            "artifacts": artifacts,
        }

    async def _with_session(self, server: dict[str, Any], operation: Any) -> Any:
        session_cls, _types = _mcp_client_components()
        if session_cls is None:
            raise SafeCapabilityError("DEPENDENCY_UNAVAILABLE", "MCP Python SDK bu kurulumda hazır değil.")
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        params = StdioServerParameters(
            command=_stdio_command(server.get("command", "")),
            args=list(server.get("args", []) or []),
            env=dict(os.environ),
            cwd=str(server.get("cwd", "") or "") or None,
        )
        try:
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
