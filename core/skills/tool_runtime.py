from __future__ import annotations

from typing import Any

from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.task_executor import TaskExecutor
from tools import AVAILABLE_TOOLS


async def execute_registered_tool(tool_name: str, params: dict[str, Any] | None = None, *, source: str = "skill") -> dict[str, Any]:
    tool = AVAILABLE_TOOLS.get(str(tool_name or "").strip())
    if not callable(tool):
        return normalize_legacy_tool_payload(
            {
                "success": False,
                "status": "failed",
                "error": f"Tool not found: {tool_name}",
                "errors": ["UNKNOWN_TOOL"],
                "data": {"error_code": "UNKNOWN_TOOL"},
            },
            tool=str(tool_name or ""),
            source=source,
        )
    return await TaskExecutor().execute(tool, dict(params or {}))


def wrap_skill_tool_result(result: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "success": bool(result.get("success", False)),
        "status": str(result.get("status") or ("success" if result.get("success") else "failed")),
        "result": result,
    }
    if payload["success"]:
        message = str(result.get("message") or "").strip()
        if message:
            payload["message"] = message
    else:
        payload["error"] = str(result.get("error") or result.get("message") or "tool_failed")
    return payload


__all__ = ["execute_registered_tool", "wrap_skill_tool_result"]
