from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.capabilities.filesystem import FilesystemCapability
from core.capabilities.terminal import TerminalCapability
from core.capabilities.browser.runtime import run_browser_runtime
from core.capabilities.file_ops.workflow import evaluate_file_ops_runtime
from core.capabilities.screen_operator.runtime import run_screen_operator
from core.execution_guard import get_execution_guard


@pytest.mark.asyncio
async def test_browser_runtime_emits_shadow_for_unsupported_action(monkeypatch):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    payload = await run_browser_runtime(
        action="unsupported_action",
        metadata={"workspace_id": "ws_browser", "session_id": "sess_browser", "run_id": "run_browser"},
    )

    assert payload["success"] is False
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert data["phase"] == "capability_runtime"
    assert data["action"] == "browser.unsupported_action"
    assert kwargs["workspace_id"] == "ws_browser"
    assert kwargs["session_id"] == "sess_browser"
    assert kwargs["run_id"] == "run_browser"
    assert level == "warning"


def test_file_ops_workflow_emits_shadow_runtime_event(monkeypatch):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    ctx = SimpleNamespace(
        action="list_files",
        intent={
            "params": {
                "path": "/tmp",
                "workspace_id": "ws_fileops",
                "session_id": "sess_fileops",
                "run_id": "run_fileops",
            }
        },
        tool_results=[],
    )

    payload = evaluate_file_ops_runtime(ctx)

    assert payload["verify"]["capability"] == "file_ops"
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert data["action"] == "file_ops.list_files"
    assert data["phase"] == "capability_runtime"
    assert kwargs["workspace_id"] == "ws_fileops"
    assert kwargs["session_id"] == "sess_fileops"
    assert kwargs["run_id"] == "run_fileops"
    assert level == "info"


class _FakeScreenServices:
    def __init__(self, screenshot_path: Path) -> None:
        self._screenshot_path = screenshot_path

    async def take_screenshot(self, filename: str = "") -> dict:
        return {"success": True, "path": str(self._screenshot_path)}

    async def capture_region(self, **kwargs) -> dict:
        return {"success": True, "path": str(self._screenshot_path)}

    async def get_window_metadata(self) -> dict:
        return {"frontmost_app": "Notes", "window_title": "Inbox", "bounds": {"x": 0, "y": 0, "width": 100, "height": 100}}

    async def get_accessibility_snapshot(self) -> dict:
        return {"frontmost_app": "Notes", "window_title": "Inbox", "elements": []}

    async def run_ocr(self, screenshot_path: str) -> dict:
        return {"text": "inbox", "lines": []}

    async def run_vision(self, screenshot_path: str, goal: str) -> dict:
        return {"summary": "Inbox visible", "elements": []}

    async def mouse_move(self, **kwargs) -> dict:
        return {"success": True}

    async def mouse_click(self, **kwargs) -> dict:
        return {"success": True}

    async def type_text(self, **kwargs) -> dict:
        return {"success": True}

    async def press_key(self, **kwargs) -> dict:
        return {"success": True}

    async def key_combo(self, **kwargs) -> dict:
        return {"success": True}

    async def sleep(self, seconds: float) -> None:
        return None


@pytest.mark.asyncio
async def test_screen_operator_inspect_emits_shadow_runtime_event(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    screenshot_path = tmp_path / "screen.png"
    screenshot_path.write_bytes(b"fake-image")
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    payload = await run_screen_operator(
        instruction="ekrana bak",
        mode="inspect",
        services=_FakeScreenServices(screenshot_path),
        metadata={"workspace_id": "ws_screen", "session_id": "sess_screen", "run_id": "run_screen"},
    )

    assert payload["success"] is True
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert data["action"] == "screen_operator.inspect"
    assert data["phase"] == "capability_runtime"
    assert kwargs["workspace_id"] == "ws_screen"
    assert kwargs["session_id"] == "sess_screen"
    assert kwargs["run_id"] == "run_screen"
    assert level == "info"


@pytest.mark.asyncio
async def test_filesystem_capability_emits_shadow_runtime_event(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    target = tmp_path / "note.txt"
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    capability = FilesystemCapability(allowed_roots=[str(tmp_path)])
    payload = await capability.write_file(
        str(target),
        "hello",
        metadata={"workspace_id": "ws_fs", "session_id": "sess_fs", "run_id": "run_fs"},
    )

    assert payload["status"] == "success"
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert data["action"] == "filesystem.write_file"
    assert data["phase"] == "capability_runtime"
    assert kwargs["workspace_id"] == "ws_fs"
    assert kwargs["session_id"] == "sess_fs"
    assert kwargs["run_id"] == "run_fs"
    assert level == "info"


@pytest.mark.asyncio
async def test_terminal_capability_emits_shadow_runtime_event(monkeypatch, tmp_path):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    capability = TerminalCapability(allowed_cwd=[str(tmp_path)])
    payload = await capability.execute(
        "printf ok",
        cwd=str(tmp_path),
        metadata={"workspace_id": "ws_term", "session_id": "sess_term", "run_id": "run_term"},
    )

    assert payload["exit_code"] == 0
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert data["action"] == "terminal.execute"
    assert data["phase"] == "capability_runtime"
    assert kwargs["workspace_id"] == "ws_term"
    assert kwargs["session_id"] == "sess_term"
    assert kwargs["run_id"] == "run_term"
    assert level == "info"
