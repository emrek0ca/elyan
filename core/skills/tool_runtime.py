from __future__ import annotations

from typing import Any

from core.dependencies import get_dependency_runtime, get_system_dependency_runtime
from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload
from core.task_executor import TaskExecutor
from core.skills.manager import skill_manager
from tools import AVAILABLE_TOOLS


def _error_text_from_result(result: Any) -> str:
    if isinstance(result, dict):
        for key in ("error", "message", "detail", "reason"):
            text = str(result.get(key) or "").strip()
            if text:
                return text
    return str(result or "").strip()


def _needs_dependency_retry(result: Any) -> bool:
    text = _error_text_from_result(result).lower()
    if not text:
        return False
    markers = (
        "not installed",
        "kurulu degil",
        "kurulu değil",
        "missing dependency",
        "command not found",
        "not found",
        "whisper not available",
        "pillow kurulu degil",
        "openpyxl kurulu degil",
        "playwright",
        "beautifulsoup4",
        "bs4",
        "python-docx",
        "pyttsx3",
        "pyautogui",
        "mss",
        "opencv",
        "numpy",
        "pandas",
        "aiohttp",
        "pypdf",
        "telegram",
        "httpx",
        "sounddevice",
        "ffmpeg",
        "ollama",
        "tesseract",
        "xdotool",
        "xprop",
        "wmctrl",
        "xdg-open",
        "cliclick",
    )
    return any(marker in text for marker in markers)


async def _ensure_runtime_dependencies(tool_name: str, skill_name: str, error_text: str = "") -> list[dict[str, Any]]:
    runtime = get_dependency_runtime()
    records = []
    manifest = None
    if skill_name:
        try:
            manifest = skill_manager.manifest_from_skill(skill_name)
        except Exception:
            manifest = None
    if manifest:
        skill_records = await runtime.ensure_skill_async(skill_name, manifest, allow_install=True)
        records.extend([r.to_dict() for r in skill_records])
    if tool_name:
        tool_records = await runtime.ensure_tool_async(tool_name, skill_name=skill_name, allow_install=True)
        records.extend([r.to_dict() for r in tool_records])
    if error_text:
        error_records = await runtime.ensure_from_error_async(error_text, skill_name=skill_name, tool_name=tool_name, allow_install=True)
        records.extend([r.to_dict() for r in error_records])
        system_runtime = get_system_dependency_runtime()
        system_records = await system_runtime.ensure_from_error_async(error_text, allow_install=True)
        records.extend([r.to_dict() for r in system_records])
    return records


async def execute_registered_tool(
    tool_name: str,
    params: dict[str, Any] | None = None,
    *,
    source: str = "skill",
    skill_name: str = "",
) -> dict[str, Any]:
    runtime = get_dependency_runtime()
    tool_key = str(tool_name or "").strip()

    if skill_name:
        await _ensure_runtime_dependencies(tool_key, skill_name)
    else:
        await runtime.ensure_tool_async(tool_key, allow_install=True)

    tool = AVAILABLE_TOOLS.get(tool_key)
    if not callable(tool):
        await _ensure_runtime_dependencies(tool_key, skill_name)
        tool = AVAILABLE_TOOLS.get(tool_key)
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

    executor = TaskExecutor()
    result = await executor.execute(tool, dict(params or {}))
    if _needs_dependency_retry(result):
        error_text = _error_text_from_result(result)
        dependency_records = await _ensure_runtime_dependencies(tool_key, skill_name, error_text)
        retryable = any(str(r.get("status") or "").strip().lower() in {"installed", "ready"} for r in dependency_records)
        if retryable:
            tool = AVAILABLE_TOOLS.get(tool_key)
            if callable(tool):
                retried = await executor.execute(tool, dict(params or {}))
                if isinstance(retried, dict):
                    retried.setdefault("dependency_runtime", {})
                    retried["dependency_runtime"] = {
                        "attempted": True,
                        "records": dependency_records,
                        "auto_retry": True,
                    }
                return retried
    if isinstance(result, dict):
        result.setdefault("dependency_runtime", {})
        result["dependency_runtime"] = {
            "attempted": False,
            "records": [],
            "auto_retry": False,
        }
    return result


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
