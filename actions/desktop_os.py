from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from runtime.capability_registry import SafeCapabilityError


def _snapshot_path() -> Path | None:
    raw = str(os.environ.get("ELYAN_DESKTOP_NATIVE_STATE_PATH", "") or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def _default_snapshot() -> dict[str, Any]:
    return {
        "available": False,
        "source": "fallback",
        "collectedAt": "",
        "platform": "",
        "osPermissionModel": "",
        "processInspectionAvailable": False,
        "activeWindowAvailable": False,
        "permissionProbeAvailable": False,
        "globalShortcutsAvailable": False,
        "screenCaptureAvailable": False,
        "permissions": {},
        "processes": {
            "available": False,
            "total": 0,
            "items": [],
        },
        "activeWindow": {
            "available": False,
            "appName": "",
            "windowTitle": "",
            "processId": None,
            "executablePath": "",
            "bundleId": "",
        },
        "lastErrorCode": "native_snapshot_unavailable",
    }


def _load_snapshot() -> dict[str, Any]:
    path = _snapshot_path()
    if path is None or not path.exists():
        return _default_snapshot()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        fallback = _default_snapshot()
        fallback["lastErrorCode"] = "native_snapshot_invalid"
        return fallback
    if not isinstance(payload, dict):
        fallback = _default_snapshot()
        fallback["lastErrorCode"] = "native_snapshot_invalid"
        return fallback
    snapshot = _default_snapshot()
    snapshot.update(payload)
    if not isinstance(snapshot.get("permissions"), dict):
        snapshot["permissions"] = {}
    processes = snapshot.get("processes")
    if not isinstance(processes, dict):
        processes = {"available": False, "total": 0, "items": []}
    normalized_items: list[dict[str, Any]] = []
    for item in processes.get("items", []):
        if not isinstance(item, dict):
            continue
        normalized_items.append(
            {
                "pid": item.get("pid"),
                "name": str(item.get("name", "") or ""),
                "executablePath": str(item.get("executablePath", "") or ""),
                "bundleId": str(item.get("bundleId", "") or ""),
                "frontmost": bool(item.get("frontmost", False)),
            }
        )
    processes["items"] = normalized_items[:128]
    snapshot["processes"] = processes
    active_window = snapshot.get("activeWindow")
    if not isinstance(active_window, dict):
        active_window = {
            "available": False,
            "appName": "",
            "windowTitle": "",
            "processId": None,
            "executablePath": "",
            "bundleId": "",
        }
    else:
        active_window = {
            "available": bool(active_window.get("available", False)),
            "appName": str(active_window.get("appName", "") or ""),
            "windowTitle": str(active_window.get("windowTitle", "") or ""),
            "processId": active_window.get("processId"),
            "executablePath": str(active_window.get("executablePath", "") or ""),
            "bundleId": str(active_window.get("bundleId", "") or ""),
        }
    snapshot["activeWindow"] = active_window
    return snapshot


def desktop_os_runtime_status() -> dict[str, Any]:
    snapshot = _load_snapshot()
    return {
        "available": bool(snapshot.get("available", False)),
        "lastErrorCode": str(snapshot.get("lastErrorCode", "") or ""),
        "lastErrorMessage": "Yerel native desktop snapshot hazır değil."
        if not bool(snapshot.get("available", False))
        else "",
        "detail": {
            "platform": str(snapshot.get("platform", "") or ""),
            "source": str(snapshot.get("source", "") or ""),
            "collectedAt": str(snapshot.get("collectedAt", "") or ""),
            "processInspectionAvailable": bool(snapshot.get("processInspectionAvailable", False)),
            "activeWindowAvailable": bool(snapshot.get("activeWindowAvailable", False)),
            "permissionProbeAvailable": bool(snapshot.get("permissionProbeAvailable", False)),
        },
    }


def _status_result(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": "Yerel desktop OS durumu hazır."
        if bool(snapshot.get("available", False))
        else "Yerel desktop OS durumu hazır değil.",
        "result": {
            "platform": str(snapshot.get("platform", "") or ""),
            "source": str(snapshot.get("source", "") or ""),
            "collectedAt": str(snapshot.get("collectedAt", "") or ""),
            "osPermissionModel": str(snapshot.get("osPermissionModel", "") or ""),
            "processInspectionAvailable": bool(snapshot.get("processInspectionAvailable", False)),
            "activeWindowAvailable": bool(snapshot.get("activeWindowAvailable", False)),
            "permissionProbeAvailable": bool(snapshot.get("permissionProbeAvailable", False)),
            "globalShortcutsAvailable": bool(snapshot.get("globalShortcutsAvailable", False)),
            "screenCaptureAvailable": bool(snapshot.get("screenCaptureAvailable", False)),
            "lastErrorCode": str(snapshot.get("lastErrorCode", "") or ""),
        },
    }


def desktop_os_status() -> dict[str, Any]:
    return _status_result(_load_snapshot())


def desktop_os_permissions() -> dict[str, Any]:
    snapshot = _load_snapshot()
    permissions = snapshot.get("permissions", {})
    permissions = permissions if isinstance(permissions, dict) else {}
    return {
        "text": "Yerel desktop izin durumu hazır."
        if bool(snapshot.get("permissionProbeAvailable", False))
        else "Yerel desktop izin durumu hazır değil.",
        "result": {
            "platform": str(snapshot.get("platform", "") or ""),
            "osPermissionModel": str(snapshot.get("osPermissionModel", "") or ""),
            "permissions": permissions,
            "available": bool(snapshot.get("permissionProbeAvailable", False)),
            "lastErrorCode": str(snapshot.get("lastErrorCode", "") or ""),
        },
    }


def desktop_os_processes(query: str = "", limit: int = 20) -> dict[str, Any]:
    snapshot = _load_snapshot()
    processes = snapshot.get("processes", {})
    processes = processes if isinstance(processes, dict) else {}
    if not bool(processes.get("available", False)):
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Yerel proses görünürlüğü bu cihazda hazır değil.")
    normalized_query = " ".join(str(query or "").strip().lower().split())
    items = [dict(item) for item in processes.get("items", []) if isinstance(item, dict)]
    if normalized_query:
        filtered: list[dict[str, Any]] = []
        for item in items:
            haystacks = {
                str(item.get("name", "") or "").lower(),
                str(item.get("executablePath", "") or "").lower(),
                str(item.get("bundleId", "") or "").lower(),
                str(item.get("pid", "") or "").lower(),
            }
            if any(normalized_query in value for value in haystacks if value):
                filtered.append(item)
        items = filtered
    safe_limit = max(1, min(int(limit or 20), 50))
    selected = items[:safe_limit]
    return {
        "text": f"{len(selected)} proses bulundu.",
        "result": {
            "available": True,
            "total": int(processes.get("total", len(items)) or len(items)),
            "items": selected,
            "query": normalized_query,
        },
    }


def desktop_os_active_window() -> dict[str, Any]:
    snapshot = _load_snapshot()
    active_window = snapshot.get("activeWindow", {})
    active_window = active_window if isinstance(active_window, dict) else {}
    if not bool(active_window.get("available", False)):
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Aktif pencere görünürlüğü bu cihazda hazır değil.")
    return {
        "text": "Aktif pencere bilgisi alındı.",
        "result": {
            "available": True,
            "appName": str(active_window.get("appName", "") or ""),
            "windowTitle": str(active_window.get("windowTitle", "") or ""),
            "processId": active_window.get("processId"),
            "executablePath": str(active_window.get("executablePath", "") or ""),
            "bundleId": str(active_window.get("bundleId", "") or ""),
        },
    }
