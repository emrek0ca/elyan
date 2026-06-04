from __future__ import annotations

from typing import Any

from runtime import mcp_runtime


def mcp_tool_status() -> dict[str, Any]:
    status = mcp_runtime.runtime_mcp_status()
    return {
        "available": bool(status.get("sdkAvailable", False)),
        "lastErrorCode": "" if bool(status.get("sdkAvailable", False)) else "DEPENDENCY_UNAVAILABLE",
        "lastErrorMessage": "" if bool(status.get("sdkAvailable", False)) else "MCP Python SDK bu kurulumda hazır değil.",
    }


def mcp_call_tool(
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return mcp_runtime.call_tool(server_id, tool_name, arguments if isinstance(arguments, dict) else {})
