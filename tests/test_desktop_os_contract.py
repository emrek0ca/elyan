from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime import capability_registry, state_store


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def _dangerous_state(**permissions: bool) -> dict[str, object]:
    return state_store._ensure_defaults(
        {
            "account": {"dangerousAreaEnabled": True},
            "permissions": permissions,
        }
    )


def _write_snapshot(tmp_path: Path) -> Path:
    payload = {
        "available": True,
        "source": "native_addon",
        "collectedAt": "2026-06-03T12:00:00Z",
        "platform": "darwin",
        "osPermissionModel": "macos_privacy_tcc",
        "processInspectionAvailable": True,
        "activeWindowAvailable": True,
        "permissionProbeAvailable": True,
        "globalShortcutsAvailable": True,
        "screenCaptureAvailable": True,
        "permissions": {
            "accessibility": {"required": True, "granted": None, "status": "required", "source": "ax_api", "lastCheckedAt": "2026-06-03T12:00:00Z", "settingsDeepLinkAvailable": True},
            "screenRecording": {"required": True, "granted": None, "status": "required", "source": "cg_preflight", "lastCheckedAt": "2026-06-03T12:00:00Z", "settingsDeepLinkAvailable": True},
            "inputMonitoring": {"required": True, "granted": None, "status": "unknown", "source": "unknown_unavailable_probe", "lastCheckedAt": "2026-06-03T12:00:00Z", "settingsDeepLinkAvailable": True},
            "automation": {"required": True, "granted": None, "status": "unknown", "source": "ae_probe_unavailable", "lastCheckedAt": "2026-06-03T12:00:00Z", "settingsDeepLinkAvailable": True},
        },
        "processes": {
            "available": True,
            "total": 2,
            "items": [
                {"pid": 101, "name": "Finder", "executablePath": "/System/Library/CoreServices/Finder.app"},
                {
                    "pid": 202,
                    "name": "Elyan",
                    "executablePath": "/Applications/Elyan.app",
                    "bundleId": "com.elyan.desktop",
                    "frontmost": True,
                },
            ],
        },
        "activeWindow": {
            "available": True,
            "appName": "Elyan",
            "windowTitle": "Yeni Konuşma",
            "processId": 202,
            "executablePath": "/Applications/Elyan.app",
            "bundleId": "com.elyan.desktop",
            "source": "cg_window_list+nsworkspace_frontmost",
            "confidence": 0.98,
        },
        "lastErrorCode": "",
    }
    path = tmp_path / "desktop-runtime.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_desktop_os_status_returns_structured_native_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    result = capability_registry.run_capability("desktop_os.status", {}, state_store._ensure_defaults({}))

    assert result["ok"] is True
    assert result["result"]["platform"] == "darwin"
    assert result["result"]["processInspectionAvailable"] is True


def test_desktop_os_permissions_preserve_additive_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    result = capability_registry.run_capability(
        "desktop_os.permissions",
        {},
        _dangerous_state(allow_system_inspection=True),
    )

    assert result["ok"] is True
    permissions = result["result"]["permissions"]
    assert permissions["inputMonitoring"]["source"] == "unknown_unavailable_probe"
    assert permissions["automation"]["source"] == "ae_probe_unavailable"
    assert permissions["automation"]["settingsDeepLinkAvailable"] is True


def test_desktop_os_processes_requires_permission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    result = capability_registry.run_capability("desktop_os.processes", {}, state_store._ensure_defaults({}))

    assert result["ok"] is False
    assert result["error"]["code"] == "PERMISSION_REQUIRED"


def test_desktop_os_processes_filters_when_permission_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    result = capability_registry.run_capability(
        "desktop_os.processes",
        {"query": "elyan"},
        _dangerous_state(allow_system_inspection=True),
    )

    assert result["ok"] is True
    assert result["result"]["total"] == 2
    assert result["result"]["items"] == [
        {
            "pid": 202,
            "name": "Elyan",
            "executablePath": "/Applications/Elyan.app",
            "bundleId": "com.elyan.desktop",
            "frontmost": True,
        }
    ]


def test_desktop_os_processes_filters_by_bundle_id_when_permission_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    result = capability_registry.run_capability(
        "desktop_os.processes",
        {"query": "com.elyan.desktop"},
        _dangerous_state(allow_system_inspection=True),
    )

    assert result["ok"] is True
    assert result["result"]["items"][0]["bundleId"] == "com.elyan.desktop"


def test_desktop_os_active_window_returns_snapshot_when_permission_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    result = capability_registry.run_capability(
        "desktop_os.active_window",
        {},
        _dangerous_state(allow_system_inspection=True),
    )

    assert result["ok"] is True
    assert result["result"]["available"] is True
    assert result["result"]["appName"] == "Elyan"
    assert result["result"]["windowTitle"] == "Yeni Konuşma"
    assert result["result"]["processId"] == 202
    assert result["result"]["executablePath"] == "/Applications/Elyan.app"
    assert result["result"]["bundleId"] == "com.elyan.desktop"


def test_desktop_os_open_permission_settings_opens_macos_privacy_uri(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    snapshot_path = _write_snapshot(tmp_path)
    monkeypatch.setenv("ELYAN_DESKTOP_NATIVE_STATE_PATH", str(snapshot_path))

    opened: list[list[str]] = []

    def fake_run(args: list[str], capture_output: bool, text: bool, timeout: int) -> subprocess.CompletedProcess[str]:
        opened.append(args)
        return subprocess.CompletedProcess(args=args, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = capability_registry.run_capability(
        "desktop_os.open_permission_settings",
        {"permission": "screenRecording"},
        state_store._ensure_defaults({}),
    )

    assert result["ok"] is True
    assert opened == [["open", "x-apple.systempreferences:com.apple.preference.security?Privacy_ScreenCapture"]]
