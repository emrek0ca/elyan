from __future__ import annotations

import pytest

from tools import system_tools


class _FakeDesktopHost:
    def __init__(self, payload: dict):
        self.payload = dict(payload)

    async def run_screen_operator(self, **kwargs):
        _ = kwargs
        return dict(self.payload)


@pytest.mark.asyncio
async def test_screen_workflow_inspect_maps_runtime_result(monkeypatch):
    monkeypatch.setattr(
        "core.runtime.hosts.get_desktop_host",
        lambda: _FakeDesktopHost(
            {
                "success": True,
                "message": "Screen inspected.",
                "summary": "Screen inspected.",
                "ui_state": {"frontmost_app": "Cursor", "summary": "Cursor acik."},
                "initial_observation": {
                    "success": True,
                    "summary": "Cursor acik.",
                    "screenshot": {"path": "/tmp/before.png"},
                    "vision": {"provider": "fake-vision"},
                    "ocr": {"text": "main.py"},
                    "ui_state": {"frontmost_app": "Cursor", "summary": "Cursor acik."},
                },
                "final_observation": {
                    "success": True,
                    "summary": "Cursor acik.",
                    "screenshot": {"path": "/tmp/before.png"},
                    "vision": {"provider": "fake-vision"},
                    "ocr": {"text": "main.py"},
                    "ui_state": {"frontmost_app": "Cursor", "summary": "Cursor acik."},
                },
                "artifacts": [
                    {"path": "/tmp/ui_state.json", "type": "json"},
                    {"path": "/tmp/before.png", "type": "image"},
                ],
                "screenshots": ["/tmp/before.png"],
                "task_state": {"current_step": 0},
                "verifier_outcomes": [],
            }
        ),
    )

    result = await system_tools.screen_workflow(instruction="ekrana bak", mode="inspect")

    assert result["success"] is True
    assert result["artifacts"][0]["type"] == "image"
    assert result["observations"][0]["stage"] == "before"
    assert result["observations"][0]["provider"] == "fake-vision"
    assert result["ui_state"]["frontmost_app"] == "Cursor"


@pytest.mark.asyncio
async def test_screen_workflow_control_maps_runtime_control_state(monkeypatch):
    monkeypatch.setattr(
        "core.runtime.hosts.get_desktop_host",
        lambda: _FakeDesktopHost(
            {
                "success": True,
                "message": "Search paneli acildi.",
                "summary": "Search paneli acildi.",
                "goal_achieved": True,
                "ui_state": {"frontmost_app": "Safari", "summary": "Search paneli acildi."},
                "initial_observation": {
                    "success": True,
                    "summary": "Search butonu gorunuyor.",
                    "screenshot": {"path": "/tmp/before.png"},
                    "vision": {"provider": "fake-vision"},
                    "ocr": {"text": "Search"},
                    "ui_state": {"frontmost_app": "Safari", "summary": "Search butonu gorunuyor."},
                },
                "final_observation": {
                    "success": True,
                    "summary": "Search paneli acildi.",
                    "screenshot": {"path": "/tmp/after.png"},
                    "vision": {"provider": "fake-vision"},
                    "ocr": {"text": "Search field"},
                    "ui_state": {"frontmost_app": "Safari", "summary": "Search paneli acildi."},
                },
                "artifacts": [
                    {"path": "/tmp/before.png", "type": "image"},
                    {"path": "/tmp/after.png", "type": "image"},
                ],
                "screenshots": ["/tmp/before.png", "/tmp/after.png"],
                "action_logs": [{"step": 1, "planned_action": {"kind": "click"}}],
                "verifier_outcomes": [{"ok": True}],
                "task_state": {"current_step": 1, "attempts": 1},
            }
        ),
    )

    result = await system_tools.screen_workflow(
        instruction="ekrana bak ve safariyi aç",
        mode="inspect_and_control",
        action_goal="safariyi aç",
    )

    assert result["success"] is True
    assert result["control"]["goal_achieved"] is True
    assert result["control"]["action_logs"][0]["planned_action"]["kind"] == "click"
    assert len(result["observations"]) == 2
    assert result["observations"][1]["stage"] == "after"


@pytest.mark.asyncio
async def test_vision_operator_loop_maps_read_only_runtime(monkeypatch):
    monkeypatch.setattr(system_tools, "_build_operator_goal_profile", lambda _goal: {"read_only": True})
    monkeypatch.setattr(
        "core.runtime.hosts.get_desktop_host",
        lambda: _FakeDesktopHost(
            {
                "success": True,
                "goal_achieved": True,
                "message": "Cursor acik.",
                "summary": "Cursor acik.",
                "ui_state": {"frontmost_app": "Cursor", "summary": "Cursor acik."},
                "initial_observation": {
                    "success": True,
                    "summary": "Cursor acik.",
                    "vision": {"provider": "fake-vision"},
                    "ui_state": {"frontmost_app": "Cursor", "summary": "Cursor acik."},
                },
                "final_observation": {
                    "success": True,
                    "summary": "Cursor acik.",
                    "vision": {"provider": "fake-vision"},
                    "ui_state": {"frontmost_app": "Cursor", "summary": "Cursor acik."},
                },
                "plan": [{"kind": "noop"}],
                "operator_budget": {"elapsed_s": 0.01},
                "artifacts": [{"path": "/tmp/before.png", "type": "image"}],
                "screenshots": ["/tmp/before.png"],
                "task_state": {"current_step": 0},
            }
        ),
    )

    result = await system_tools.vision_operator_loop("ekrana bak ve durumu soyle")

    assert result["success"] is True
    assert result["goal_achieved"] is True
    assert result["iterations"][0]["result"] == "inspection_only"
    assert result["operator_budget"]["elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_vision_operator_loop_maps_control_runtime(monkeypatch):
    monkeypatch.setattr(system_tools, "_build_operator_goal_profile", lambda _goal: {"read_only": False})
    monkeypatch.setattr(
        "core.runtime.hosts.get_desktop_host",
        lambda: _FakeDesktopHost(
            {
                "success": True,
                "goal_achieved": True,
                "message": "Safari acildi.",
                "summary": "Safari acildi.",
                "ui_state": {"frontmost_app": "Safari", "summary": "Safari acildi."},
                "initial_observation": {
                    "success": True,
                    "summary": "Finder acik.",
                    "vision": {"provider": "fake-vision"},
                    "ui_state": {"frontmost_app": "Finder", "summary": "Finder acik."},
                },
                "final_observation": {
                    "success": True,
                    "summary": "Safari acildi.",
                    "vision": {"provider": "fake-vision"},
                    "ui_state": {"frontmost_app": "Safari", "summary": "Safari acildi."},
                },
                "plan": [{"kind": "click"}],
                "action_logs": [
                    {
                        "execution_result": {"success": True},
                        "verification": {"ok": True},
                    }
                ],
                "operator_budget": {"elapsed_s": 0.02},
                "artifacts": [{"path": "/tmp/after.png", "type": "image"}],
                "screenshots": ["/tmp/after.png"],
                "task_state": {"current_step": 1},
            }
        ),
    )

    result = await system_tools.vision_operator_loop("safari ac")

    assert result["success"] is True
    assert result["goal_achieved"] is True
    assert result["iterations"][0]["action"]["success"] is True
    assert result["iterations"][0]["result"] == "goal_achieved"


@pytest.mark.asyncio
async def test_vision_operator_loop_uses_legacy_analysis_bridge_when_analyze_screen_is_patched(monkeypatch):
    async def _fake_analyze_screen(prompt=""):
        _ = prompt
        return {
            "success": True,
            "summary": "On planda Safari acik gorunuyor.",
            "provider": "legacy-mock",
            "ui_map": {"frontmost_app": "Safari", "running_apps": ["Safari"], "coordinates_detected": False},
            "path": "/tmp/legacy-safari.png",
        }

    async def _unexpected_run_screen_operator(**kwargs):
        raise AssertionError(f"run_screen_operator should not run when legacy analyze_screen is patched: {kwargs}")

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr("core.capabilities.screen_operator.run_screen_operator", _unexpected_run_screen_operator)

    result = await system_tools.vision_operator_loop("safari ac")

    assert result["success"] is True
    assert result["goal_achieved"] is True
    assert result["operator_budget"]["elapsed_s"] >= 0
    assert result["iterations"][0]["result"] == "goal_already_visible"


@pytest.mark.asyncio
async def test_screen_workflow_uses_legacy_analysis_bridge_for_inspect_mode(monkeypatch):
    async def _fake_analyze_screen(prompt=""):
        _ = prompt
        return {
            "success": True,
            "summary": "Cursor acik.",
            "provider": "legacy-mock",
            "ui_map": {"frontmost_app": "Cursor", "elements": [{"label": "Run", "kind": "button"}]},
            "path": "/tmp/legacy-cursor.png",
            "ocr": "main.py",
        }

    async def _unexpected_run_screen_operator(**kwargs):
        raise AssertionError(f"run_screen_operator should not run when legacy analyze_screen is patched: {kwargs}")

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr("core.capabilities.screen_operator.run_screen_operator", _unexpected_run_screen_operator)

    result = await system_tools.screen_workflow(instruction="ekrana bak", mode="inspect")

    assert result["success"] is True
    assert result["ui_state"]["frontmost_app"] == "Cursor"
    assert result["observations"][0]["provider"] == "legacy-mock"
    assert result["screenshots"] == ["/tmp/legacy-cursor.png"]


@pytest.mark.asyncio
async def test_screen_workflow_uses_legacy_control_bridge_when_computer_use_is_patched(monkeypatch):
    calls = {"analyze": 0, "computer_use": 0}

    async def _fake_analyze_screen(prompt=""):
        calls["analyze"] += 1
        if calls["analyze"] == 1:
            return {
                "success": True,
                "summary": "Finder acik.",
                "provider": "legacy-mock",
                "ui_map": {"frontmost_app": "Finder", "running_apps": ["Finder"]},
                "path": "/tmp/finder-before.png",
            }
        return {
            "success": True,
            "summary": "Safari acildi.",
            "provider": "legacy-mock",
            "ui_map": {"frontmost_app": "Safari", "running_apps": ["Safari"]},
            "path": "/tmp/safari-after.png",
        }

    async def _fake_computer_use(**kwargs):
        calls["computer_use"] += 1
        _ = kwargs
        return {
            "success": True,
            "goal_achieved": True,
            "message": "Safari acildi.",
            "steps": [{"step": 1, "action": "open_app", "result": {"success": True}}],
            "screenshots": ["/tmp/safari-after.png"],
        }

    async def _unexpected_run_screen_operator(**kwargs):
        raise AssertionError(f"run_screen_operator should not run when legacy computer_use is patched: {kwargs}")

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr(system_tools, "computer_use", _fake_computer_use)
    monkeypatch.setattr("core.capabilities.screen_operator.run_screen_operator", _unexpected_run_screen_operator)

    result = await system_tools.screen_workflow(instruction="safari ac", mode="control")

    assert result["success"] is True
    assert result["control"]["goal_achieved"] is True
    assert result["control"]["action_logs"][0]["planned_action"]["kind"] == "open_app"
    assert calls["computer_use"] == 1


@pytest.mark.asyncio
async def test_desktop_operator_state_tools_expose_and_reset_live_state(monkeypatch):
    class _FakeHost:
        async def get_live_state(self):
            return {
                "frontmost_app": "Safari",
                "active_window": {"title": "Search"},
                "last_screenshot": "/tmp/after.png",
                "target_cache": {"search": {"label": "Search"}},
                "recent_action_logs": [{"step": 1}],
                "verifier_outcomes": [{"ok": True}],
            }

        async def clear_live_state(self):
            return {
                "frontmost_app": "",
                "active_window": {},
                "last_screenshot": "",
                "last_ui_state": {},
                "current_task_state": {},
                "target_cache": {},
                "recent_action_logs": [],
                "verifier_outcomes": [],
            }

    monkeypatch.setattr("core.runtime.hosts.get_desktop_host", lambda: _FakeHost())

    state_result = await system_tools.desktop_operator_state()
    reset_result = await system_tools.reset_desktop_operator_state()

    assert state_result["success"] is True
    assert state_result["frontmost_app"] == "Safari"
    assert state_result["target_cache_size"] == 1
    assert reset_result["success"] is True
    assert reset_result["state"]["target_cache"] == {}
