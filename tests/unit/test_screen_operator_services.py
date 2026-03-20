from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest

from core.capabilities.screen_operator import services


class _FakeWinUser32:
    def GetForegroundWindow(self):
        return 101

    def GetWindowTextLengthW(self, hwnd):
        _ = hwnd
        return len("Notes")

    def GetWindowTextW(self, hwnd, buffer, size):
        _ = (hwnd, size)
        buffer.value = "Notes"
        return 1

    def GetWindowRect(self, hwnd, rect):
        _ = (hwnd, rect)
        return 0


class _FakePyatspiNode:
    def __init__(self, name: str, role: str, children: list["_FakePyatspiNode"] | None = None):
        self.name = name
        self._role = role
        self._children = list(children or [])
        self.childCount = len(self._children)

    def getRoleName(self):
        return self._role

    def getChildAtIndex(self, idx):
        return self._children[idx]


class _FakePyatspiRegistry:
    @staticmethod
    def getDesktop(index=0):
        _ = index
        return _FakePyatspiNode("Desktop", "frame", [_FakePyatspiNode("Save", "push button")])


@pytest.mark.asyncio
async def test_default_window_metadata_windows_uses_ctypes(monkeypatch):
    monkeypatch.setattr(services.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        services.ctypes,
        "windll",
        SimpleNamespace(user32=_FakeWinUser32()),
        raising=False,
    )

    result = await services._default_window_metadata()

    assert result["success"] is True
    assert result["frontmost_app"] == "Notes"
    assert result["window_title"] == "Notes"


@pytest.mark.asyncio
async def test_default_accessibility_snapshot_linux_uses_pyatspi(monkeypatch):
    monkeypatch.setattr(services.platform, "system", lambda: "Linux")
    monkeypatch.setattr(services, "_module_available", lambda name: name == "pyatspi")

    async def _fake_window_metadata():
        return {"success": True, "frontmost_app": "Desktop", "window_title": "Desktop", "bounds": {}}

    monkeypatch.setattr(services, "_default_window_metadata", _fake_window_metadata)

    fake_module = SimpleNamespace(Registry=_FakePyatspiRegistry())
    monkeypatch.setitem(sys.modules, "pyatspi", fake_module)

    result = await services._default_accessibility_snapshot()

    assert result["success"] is True
    assert result["frontmost_app"] == "Desktop"
    assert result["window_title"] == "Desktop"
    assert any(item["label"] == "Save" for item in result["elements"])
