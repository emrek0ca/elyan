from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import datetime as dt
import importlib.util
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
            "source": "fallback",
            "confidence": 0,
        },
        "operator": {
            "available": False,
            "mode": "scaffold_only",
            "screenObservationReady": False,
            "accessibilityReady": False,
            "inputControlReady": False,
            "emergencyStopAvailable": False,
            "failSafeCornerAbort": True,
            "playwrightReady": False,
            "browserFirstReady": False,
            "operatorResolutionMode": "",
            "lastTargetSource": "",
            "lastVerificationSource": "",
            "lastTargetConfidence": 0.0,
            "activeRunSummary": {},
            "lastErrorCode": "native_snapshot_unavailable",
        },
        "lastErrorCode": "native_snapshot_unavailable",
    }


def _utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _permission_record(
    *,
    granted: bool | None,
    source: str,
    required: bool = True,
) -> dict[str, Any]:
    return {
        "required": required,
        "granted": granted,
        "status": "granted" if granted is True else "denied" if granted is False else "unknown",
        "source": source,
        "settingsDeepLinkAvailable": sys.platform == "darwin",
        "lastCheckedAt": _utc_now_iso(),
    }


def _macos_permission_value(framework: str, symbol: str) -> bool | None:
    try:
        import ctypes

        library = ctypes.CDLL(framework)
        probe = getattr(library, symbol)
        probe.argtypes = []
        probe.restype = ctypes.c_bool
        return bool(probe())
    except Exception:
        return None


def _fallback_permissions() -> tuple[str, dict[str, Any], bool, bool]:
    if sys.platform != "darwin":
        model = "windows_desktop" if os.name == "nt" else "linux_desktop"
        return model, {}, True, False
    application_services = "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
    core_graphics = "/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics"
    accessibility = _macos_permission_value(application_services, "AXIsProcessTrusted")
    screen_recording = _macos_permission_value(core_graphics, "CGPreflightScreenCaptureAccess")
    input_monitoring = _macos_permission_value(core_graphics, "CGPreflightListenEventAccess")
    permissions = {
        "accessibility": _permission_record(granted=accessibility, source="python_ctypes_ax"),
        "screenRecording": _permission_record(granted=screen_recording, source="python_ctypes_cg"),
        "inputMonitoring": _permission_record(granted=input_monitoring, source="python_ctypes_cg"),
        "automation": _permission_record(granted=None, source="probe_unavailable"),
    }
    return "macos_privacy_tcc", permissions, True, bool(screen_recording)


def _fallback_processes(*, limit: int = 128) -> dict[str, Any]:
    try:
        import psutil  # type: ignore[reportMissingImports]
    except Exception:
        return {"available": False, "total": 0, "items": []}
    items: list[dict[str, Any]] = []
    for process in psutil.process_iter(["pid", "name", "exe"]):
        try:
            info = process.info
            items.append(
                {
                    "pid": int(info.get("pid") or 0),
                    "name": str(info.get("name") or ""),
                    "executablePath": str(info.get("exe") or ""),
                    "bundleId": "",
                    "frontmost": False,
                }
            )
        except (psutil.AccessDenied, psutil.NoSuchProcess, OSError):
            continue
        if len(items) >= max(1, min(limit, 256)):
            break
    items.sort(key=lambda item: int(item.get("pid", 0) or 0))
    return {"available": True, "total": len(items), "items": items}


def _macos_active_application() -> dict[str, Any]:
    executable = Path("/usr/bin/lsappinfo")
    if not executable.exists():
        return {"available": False}
    try:
        front = subprocess.run(
            [str(executable), "front"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        asn = str(front.stdout or "").strip()
        if front.returncode != 0 or not asn:
            return {"available": False}
        info = subprocess.run(
            [str(executable), "info", "-only", "name,pid,bundleid", asn],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        payload = str(info.stdout or "")
        name_match = re.search(r'"LSDisplayName"="([^"]*)"', payload)
        pid_match = re.search(r'"pid"=(\d+)', payload)
        bundle_match = re.search(r'"CFBundleIdentifier"="([^"]*)"', payload)
        pid = int(pid_match.group(1)) if pid_match else None
        executable_path = ""
        if pid:
            try:
                import psutil  # type: ignore[reportMissingImports]

                executable_path = str(psutil.Process(pid).exe() or "")
            except Exception:
                executable_path = ""
        return {
            "available": bool(name_match),
            "appName": name_match.group(1) if name_match else "",
            "windowTitle": "",
            "processId": pid,
            "executablePath": executable_path,
            "bundleId": bundle_match.group(1) if bundle_match else "",
            "source": "lsappinfo_frontmost",
            "confidence": 0.82 if name_match else 0.0,
        }
    except Exception:
        return {"available": False}


def _windows_active_window() -> dict[str, Any]:
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return {"available": False}
        length = user32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        import psutil  # type: ignore[reportMissingImports]

        process = psutil.Process(int(pid.value))
        return {
            "available": True,
            "appName": process.name(),
            "windowTitle": buffer.value,
            "processId": int(pid.value),
            "executablePath": process.exe(),
            "bundleId": "",
            "source": "win32_foreground_window",
            "confidence": 0.95,
        }
    except Exception:
        return {"available": False}


def _linux_active_window() -> dict[str, Any]:
    executable = shutil.which("xdotool")
    if not executable or not os.environ.get("DISPLAY"):
        return {"available": False}
    try:
        window = subprocess.run(
            [executable, "getactivewindow"], capture_output=True, text=True, timeout=3, check=False
        )
        window_id = str(window.stdout or "").strip()
        if window.returncode != 0 or not window_id:
            return {"available": False}
        title = subprocess.run(
            [executable, "getwindowname", window_id], capture_output=True, text=True, timeout=3, check=False
        )
        pid_result = subprocess.run(
            [executable, "getwindowpid", window_id], capture_output=True, text=True, timeout=3, check=False
        )
        pid_text = str(pid_result.stdout or "").strip()
        pid = int(pid_text) if pid_text.isdigit() else None
        app_name = ""
        executable_path = ""
        if pid:
            try:
                import psutil  # type: ignore[reportMissingImports]

                process = psutil.Process(pid)
                app_name = process.name()
                executable_path = process.exe()
            except Exception:
                pass
        return {
            "available": True,
            "appName": app_name,
            "windowTitle": str(title.stdout or "").strip(),
            "processId": pid,
            "executablePath": executable_path,
            "bundleId": "",
            "source": "xdotool_active_window",
            "confidence": 0.85,
        }
    except Exception:
        return {"available": False}


def _fallback_active_window() -> dict[str, Any]:
    if sys.platform == "darwin":
        return _macos_active_application()
    if os.name == "nt":
        return _windows_active_window()
    return _linux_active_window()


def _fallback_snapshot() -> dict[str, Any]:
    os_model, permissions, permission_probe, screen_capture = _fallback_permissions()
    process_probe_available = importlib.util.find_spec("psutil") is not None
    active_probe_available = (
        (sys.platform == "darwin" and Path("/usr/bin/lsappinfo").exists())
        or os.name == "nt"
        or bool(shutil.which("xdotool") and os.environ.get("DISPLAY"))
    )
    snapshot = _default_snapshot()
    snapshot.update(
        {
            "available": bool(process_probe_available or active_probe_available),
            "source": "python_fallback",
            "collectedAt": _utc_now_iso(),
            "platform": "darwin" if sys.platform == "darwin" else "windows" if os.name == "nt" else "linux",
            "osPermissionModel": os_model,
            "processInspectionAvailable": process_probe_available,
            "activeWindowAvailable": active_probe_available,
            "permissionProbeAvailable": permission_probe,
            "screenCaptureAvailable": screen_capture,
            "permissions": permissions,
            "processes": {"available": process_probe_available, "total": 0, "items": []},
            "lastErrorCode": "",
        }
    )
    return snapshot


def _load_snapshot() -> dict[str, Any]:
    path = _snapshot_path()
    if path is None or not path.exists():
        return _fallback_snapshot()
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
            "source": "fallback",
            "confidence": 0,
        }
    else:
        active_window = {
            "available": bool(active_window.get("available", False)),
            "appName": str(active_window.get("appName", "") or ""),
            "windowTitle": str(active_window.get("windowTitle", "") or ""),
            "processId": active_window.get("processId"),
            "executablePath": str(active_window.get("executablePath", "") or ""),
            "bundleId": str(active_window.get("bundleId", "") or ""),
            "source": str(active_window.get("source", "") or ""),
            "confidence": float(active_window.get("confidence", 0) or 0),
        }
    snapshot["activeWindow"] = active_window
    operator = snapshot.get("operator")
    if not isinstance(operator, dict):
        operator = {
            "available": False,
            "mode": "scaffold_only",
            "screenObservationReady": False,
            "accessibilityReady": False,
            "inputControlReady": False,
            "emergencyStopAvailable": False,
            "failSafeCornerAbort": True,
            "playwrightReady": False,
            "browserFirstReady": False,
            "operatorResolutionMode": "",
            "lastTargetSource": "",
            "lastVerificationSource": "",
            "lastTargetConfidence": 0.0,
            "activeRunSummary": {},
            "lastErrorCode": str(snapshot.get("lastErrorCode", "") or "native_snapshot_unavailable"),
        }
    else:
        operator = {
            "available": bool(operator.get("available", False)),
            "mode": str(operator.get("mode", "") or "scaffold_only"),
            "screenObservationReady": bool(operator.get("screenObservationReady", False)),
            "accessibilityReady": bool(operator.get("accessibilityReady", False)),
            "inputControlReady": bool(operator.get("inputControlReady", False)),
            "emergencyStopAvailable": bool(operator.get("emergencyStopAvailable", False)),
            "failSafeCornerAbort": bool(operator.get("failSafeCornerAbort", True)),
            "playwrightReady": bool(operator.get("playwrightReady", False)),
            "browserFirstReady": bool(operator.get("browserFirstReady", False)),
            "operatorResolutionMode": str(operator.get("operatorResolutionMode", "") or ""),
            "lastTargetSource": str(operator.get("lastTargetSource", "") or ""),
            "lastVerificationSource": str(operator.get("lastVerificationSource", "") or ""),
            "lastTargetConfidence": float(operator.get("lastTargetConfidence", 0) or 0),
            "activeRunSummary": dict(operator.get("activeRunSummary", {}) or {})
            if isinstance(operator.get("activeRunSummary", {}), dict)
            else {},
            "lastErrorCode": str(operator.get("lastErrorCode", "") or ""),
        }
    snapshot["operator"] = operator
    normalized_permissions: dict[str, Any] = {}
    for key, value in snapshot.get("permissions", {}).items():
        if not isinstance(key, str) or not isinstance(value, dict):
            continue
        normalized_permissions[key] = {
            "required": bool(value.get("required", False)),
            "granted": value.get("granted") if value.get("granted") in {True, False, None} else None,
            "status": str(value.get("status", "unknown") or "unknown"),
            "source": str(value.get("source", "") or ""),
            "settingsDeepLinkAvailable": bool(value.get("settingsDeepLinkAvailable", False)),
            "lastCheckedAt": str(value.get("lastCheckedAt", "") or ""),
        }
    snapshot["permissions"] = normalized_permissions
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
            "operator": snapshot.get("operator", {}),
            "lastErrorCode": str(snapshot.get("lastErrorCode", "") or ""),
        },
    }


def desktop_os_status() -> dict[str, Any]:
    return _status_result(_load_snapshot())


def desktop_os_snapshot() -> dict[str, Any]:
    snapshot = _load_snapshot()
    return {
        "text": "Yerel desktop snapshot hazır."
        if bool(snapshot.get("available", False))
        else "Yerel desktop snapshot hazır değil.",
        "result": snapshot,
    }


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
            "operatorEmergencyStopAvailable": bool(
                isinstance(snapshot.get("operator"), dict)
                and snapshot["operator"].get("emergencyStopAvailable", False)
            ),
            "lastErrorCode": str(snapshot.get("lastErrorCode", "") or ""),
        },
    }


_MACOS_PERMISSION_URIS = {
    "accessibility": "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility",
    "screenrecording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "screen_recording": "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture",
    "inputmonitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "input_monitoring": "x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent",
    "automation": "x-apple.systempreferences:com.apple.preference.security?Privacy_Automation",
    "privacy": "x-apple.systempreferences:com.apple.preference.security?Privacy",
}


def _normalise_permission_name(value: str) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def desktop_os_open_permission_settings(permission: str = "privacy") -> dict[str, Any]:
    normalized = _normalise_permission_name(permission)
    if not normalized:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Acilacak izin belirtilmedi.")

    # Native snapshot'ın platform alanına güvenme (boş olabilir) — gerçek OS'a bak.
    # Aksi halde macOS'ta bile "İzin ver" kartı ayar panelini açamıyordu.
    import sys as _sys
    platform = "darwin" if _sys.platform == "darwin" else _sys.platform
    if platform != "darwin":
        raise SafeCapabilityError("UNSUPPORTED_PLATFORM", "Sistem izinlerini buradan açma akışı şu anda yalnız macOS'ta hazır.")

    target_uri = _MACOS_PERMISSION_URIS.get(normalized, _MACOS_PERMISSION_URIS["privacy"])
    try:
        result = subprocess.run(["open", target_uri], capture_output=True, text=True, timeout=10)
    except Exception as exc:
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Sistem izinleri ekranı güvenli şekilde açılamadı.") from exc
    if result.returncode != 0:
        raise SafeCapabilityError("CAPABILITY_UNAVAILABLE", "Sistem izinleri ekranı güvenli şekilde açılamadı.")
    return {
        "text": "Sistem izinleri ekranı açıldı.",
        "result": {
            "opened": True,
            "platform": platform,
            "permission": normalized,
            "target": target_uri,
        },
    }


def desktop_os_processes(query: str = "", limit: int = 20) -> dict[str, Any]:
    snapshot = _load_snapshot()
    processes = (
        _fallback_processes(limit=256)
        if str(snapshot.get("source", "") or "") == "python_fallback"
        else snapshot.get("processes", {})
    )
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
    # Kullanıcıya OKUNAKLI liste: yalnız "N proses bulundu" işe yaramaz —
    # uygulama/proses ADLARINI göster (tekilleştirilmiş, sıralı).
    seen: set[str] = set()
    names: list[str] = []
    for item in selected:
        raw_name = str(item.get("name", "") or item.get("bundleId", "") or "").strip()
        # Yol/uzantı gürültüsünü temizle (…/Foo.app → Foo).
        display = raw_name.rsplit("/", 1)[-1]
        for suffix in (".app", ".exe"):
            if display.lower().endswith(suffix):
                display = display[: -len(suffix)]
        display = display.strip()
        key = display.lower()
        if display and key not in seen:
            seen.add(key)
            names.append(display)
    if names:
        preview = ", ".join(names[:15])
        more = len(names) - 15
        if more > 0:
            preview += f" ve {more} tane daha"
        text = f"Açık uygulamalar ({len(names)}): {preview}."
    else:
        text = f"{len(selected)} proses bulundu."
    return {
        "text": text,
        "result": {
            "available": True,
            "total": int(processes.get("total", len(items)) or len(items)),
            "items": selected,
            "names": names,
            "query": normalized_query,
        },
    }


def desktop_os_active_window() -> dict[str, Any]:
    snapshot = _load_snapshot()
    active_window = (
        _fallback_active_window()
        if str(snapshot.get("source", "") or "") == "python_fallback"
        else snapshot.get("activeWindow", {})
    )
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
            "source": str(active_window.get("source", "") or ""),
            "confidence": float(active_window.get("confidence", 0) or 0),
        },
    }
