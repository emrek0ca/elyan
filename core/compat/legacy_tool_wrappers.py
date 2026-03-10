from __future__ import annotations

import inspect
from functools import wraps
from typing import Any, Callable

from core.contracts.tool_result import coerce_tool_result


_WRAPPER_CACHE: dict[tuple[str, int], Callable[..., Any]] = {}


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _legacy_success_from_status(status: str) -> bool:
    return str(status or "").strip().lower() in {"success", "partial", "noop"}


def _first_error_code(payload: dict[str, Any]) -> str:
    errors = payload.get("errors")
    if isinstance(errors, list):
        for item in errors:
            clean = str(item or "").strip()
            if clean:
                return clean
    data = payload.get("data")
    if isinstance(data, dict):
        clean = str(data.get("error_code") or "").strip()
        if clean:
            return clean
    return ""


def normalize_legacy_tool_payload(raw: Any, *, tool: str = "", source: str = "legacy_tool_wrapper") -> dict[str, Any]:
    normalized = coerce_tool_result(raw, tool=tool, source=source)
    contract_payload = normalized.to_dict()
    contract_payload["raw"] = None
    contract_payload["tool"] = str(tool or "")
    contract_payload["source"] = str(source or "")
    contract_payload["raw_type"] = type(raw).__name__

    payload = _safe_dict(raw)
    success = _legacy_success_from_status(normalized.status)
    message = str(normalized.message or "").strip()
    artifact_rows = [artifact.to_dict() for artifact in normalized.artifacts]
    error_code = _first_error_code(contract_payload)

    if not payload and isinstance(raw, str):
        payload["output"] = message

    payload["success"] = success
    payload["status"] = normalized.status
    payload["message"] = message
    if not success:
        payload["error"] = str(payload.get("error") or message or error_code or "tool_failed")
        if error_code and not str(payload.get("error_code") or "").strip():
            payload["error_code"] = error_code
    elif "error" in payload and not str(payload.get("error") or "").strip():
        payload.pop("error", None)

    if not isinstance(payload.get("artifacts"), list):
        payload["artifacts"] = artifact_rows
    payload["artifact_manifest"] = artifact_rows
    payload["evidence"] = list(normalized.evidence or [])
    payload["errors"] = list(normalized.errors or [])

    merged_metrics: dict[str, Any] = {}
    if isinstance(payload.get("metrics"), dict):
        merged_metrics.update(payload["metrics"])
    merged_metrics.update(dict(normalized.metrics or {}))
    if tool:
        merged_metrics.setdefault("tool_name", str(tool))
    merged_metrics.setdefault("wrapper_source", str(source or "legacy_tool_wrapper"))
    merged_metrics.setdefault("raw_type", type(raw).__name__)
    payload["metrics"] = merged_metrics

    merged_data: dict[str, Any] = {}
    if isinstance(payload.get("data"), dict):
        merged_data.update(payload["data"])
    merged_data.update(dict(normalized.data or {}))
    payload["data"] = merged_data

    payload["_tool_result"] = contract_payload
    return payload


def wrap_legacy_tool(tool_name: str, tool_func: Callable[..., Any]) -> Callable[..., Any]:
    if not callable(tool_func):
        return tool_func
    if getattr(tool_func, "_elyan_legacy_tool_wrapper", False):
        return tool_func

    cache_key = (str(tool_name or ""), id(tool_func))
    cached = _WRAPPER_CACHE.get(cache_key)
    if cached is not None:
        return cached

    if inspect.iscoroutinefunction(tool_func):
        @wraps(tool_func)
        async def _async_wrapped(*args, **kwargs):
            raw = await tool_func(*args, **kwargs)
            return normalize_legacy_tool_payload(raw, tool=tool_name or getattr(tool_func, "__name__", ""), source="legacy_tool_wrapper")

        wrapped = _async_wrapped
    else:
        @wraps(tool_func)
        def _sync_wrapped(*args, **kwargs):
            raw = tool_func(*args, **kwargs)
            return normalize_legacy_tool_payload(raw, tool=tool_name or getattr(tool_func, "__name__", ""), source="legacy_tool_wrapper")

        wrapped = _sync_wrapped

    try:
        wrapped.__signature__ = inspect.signature(tool_func)  # type: ignore[attr-defined]
    except Exception:
        pass
    setattr(wrapped, "_elyan_legacy_tool_wrapper", True)
    setattr(wrapped, "_elyan_legacy_tool_name", str(tool_name or getattr(tool_func, "__name__", "")))
    _WRAPPER_CACHE[cache_key] = wrapped
    return wrapped


__all__ = ["normalize_legacy_tool_payload", "wrap_legacy_tool"]
