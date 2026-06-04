from __future__ import annotations

import json
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
            "accessibility": {"required": True, "granted": None, "status": "required"},
            "screenRecording": {"required": True, "granted": None, "status": "required"},
            "inputMonitoring": {"required": True, "granted": None, "status": "required"},
            "automation": {"required": True, "granted": None, "status": "required"},
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
    assert result["result"] == {
        "available": True,
        "appName": "Elyan",
        "windowTitle": "Yeni Konuşma",
        "processId": 202,
        "executablePath": "/Applications/Elyan.app",
        "bundleId": "com.elyan.desktop",
    }
