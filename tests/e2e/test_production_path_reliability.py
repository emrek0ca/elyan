from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from core.runtime import DesktopHost, LiveOperatorTaskPlanner, OperatorTaskRuntime, run_production_benchmarks
from tests.e2e.test_operator_task_runtime import _PageState, _ScreenState, _TaskBrowserServices, _TaskScreenServices


class _DelayedTypeScreenServices(_TaskScreenServices):
    def __init__(self, tmp_path: Path, states: list[_ScreenState]) -> None:
        super().__init__(tmp_path, states)
        self._type_calls = 0

    async def type_text(self, text: str, press_enter: bool = False) -> dict[str, Any]:
        self._type_calls += 1
        self.type_events.append(text)
        if self._type_calls >= 2:
            self.index = max(0, len(self.states) - 1)
        return {"success": True, "typed_chars": len(text), "press_enter": bool(press_enter)}


class _CoupledDialogScreenServices(_TaskScreenServices):
    def __init__(self, tmp_path: Path, states: list[_ScreenState], *, on_confirm: Any = None) -> None:
        super().__init__(tmp_path, states, click_transitions={(360, 106): max(0, len(states) - 1)})
        self.on_confirm = on_confirm

    async def mouse_click(self, x: int, y: int, button: str = "left", double: bool = False) -> dict[str, Any]:
        result = await super().mouse_click(x, y, button=button, double=double)
        if self.on_confirm is not None and (int(x), int(y)) == (360, 106):
            self.on_confirm()
        return result


def _mkdir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _artifact(path: Path, artifact_type: str) -> dict[str, str]:
    return {"path": str(path), "type": artifact_type}


@pytest.mark.asyncio
async def test_runtime_replans_suffix_after_verified_step_already_advanced_state(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    browser = _TaskBrowserServices(
        tmp_path,
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(
                url="https://search.local?q=kittens",
                title="Results",
                visible_text="Results for kittens",
                html="<html><body>Results for kittens</body></html>",
                selectors={"#q": {"text": "kittens"}},
                links=[],
                table={},
            ),
        ],
        url_map={"https://search.local": 1},
    )
    runtime = OperatorTaskRuntime(desktop_host=host, tasks_root=tmp_path / "tasks")
    result = await runtime.start_task(
        goal="Open results directly",
        name="skip-obsolete-suffix",
        steps=[
            {
                "kind": "browser",
                "name": "open_page",
                "action": "open",
                "url": "https://search.local",
                "verify": {"url_contains": "search.local"},
            },
            {
                "kind": "browser",
                "name": "submit_query",
                "action": "submit",
                "selector": "#q",
                "expected_text": "Results for kittens",
                "verify": {"url_contains": "kittens", "title_contains": "Results", "text_contains": "Results for kittens"},
                "repair_policy": {"max_retries": 0},
            },
        ],
        browser_services=browser.build(),
        clear_live_state=True,
    )

    assert result["success"] is True
    assert result["task_state"]["completed_steps"] == [1]
    assert result["task_state"]["replan_count"] == 1
    assert browser.submit_calls == 0


@pytest.mark.asyncio
async def test_runtime_replans_failed_screen_step_from_latest_observation_without_rerunning_prefix(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _TaskScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Continue butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Checkout",
                accessibility=[{"label": "Continue", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}],
                vision=[],
                ocr_text="Continue",
                ocr_lines=[],
            ),
            _ScreenState(summary="Next ekran acildi.", frontmost_app="Safari", window_title="Next", accessibility=[], vision=[], ocr_text="Next", ocr_lines=[]),
        ],
        delayed_click_transitions={(360, 106): {"after": 1, "to": 1}},
    )
    open_calls = {"count": 0}

    async def _system_runner(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            open_calls["count"] += 1
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    runtime = OperatorTaskRuntime(desktop_host=host, system_tool_runner=_system_runner, tasks_root=tmp_path / "tasks", default_max_step_retries=0)
    result = await runtime.start_task(
        goal="Continue",
        name="screen-replan",
        steps=[
            {"kind": "system", "name": "open_safari", "tool": "open_app", "params": {"app_name": "Safari"}, "verify": {"frontmost_app": "Safari"}},
            {
                "kind": "screen",
                "name": "continue_step",
                "instruction": "Continue butonuna tikla",
                "verify": {"window_title_contains": "Next"},
                "max_retries_per_action": 0,
                "repair_policy": {"max_retries": 0},
            },
        ],
        screen_services=screen.build(),
        clear_live_state=True,
    )

    assert result["success"] is True
    assert open_calls["count"] == 1
    assert result["task_state"]["replan_count"] == 1
    assert result["task_state"]["steps"][0]["attempts"] == 1
    assert result["task_state"]["replan_history"][0]["step_index"] == 2


@pytest.mark.asyncio
async def test_runtime_rewrites_dom_unavailable_browser_step_to_screen_fallback(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _TaskScreenServices(
        tmp_path,
        [
            _ScreenState(summary="Search penceresi acik.", frontmost_app="Safari", window_title="Search", accessibility=[], vision=[], ocr_text="Search", ocr_lines=[]),
        ],
    )

    async def _browser_runner(**kwargs):
        _ = kwargs
        return {
            "success": False,
            "status": "failed",
            "error": "dom unavailable",
            "error_code": "DOM_UNAVAILABLE",
            "message": "dom unavailable",
            "browser_state": {"dom_available": False, "url": "", "title": ""},
            "artifacts": [],
            "screenshots": [],
            "action_logs": [],
            "verifier_outcomes": [{"ok": False, "failed_codes": ["DOM_UNAVAILABLE"]}],
            "recovery_hints": {"dom_available": False, "failed_codes": ["DOM_UNAVAILABLE"]},
        }

    runtime = OperatorTaskRuntime(desktop_host=host, browser_runner=_browser_runner, tasks_root=tmp_path / "tasks")
    result = await runtime.start_task(
        goal="Open browser page",
        name="browser-to-screen-fallback",
        steps=[
            {
                "kind": "browser",
                "name": "open_page",
                "action": "open",
                "url": "https://search.local",
                "expected_title_contains": "Search",
                "verify": {"title_contains": "Search"},
                "repair_policy": {"max_retries": 0},
            }
        ],
        screen_services=screen.build(),
        clear_live_state=True,
    )

    assert result["success"] is True
    assert result["task_state"]["replan_count"] == 1
    assert result["task_state"]["replan_history"][0]["new_step_names"][0].startswith("screen_fallback_")


@pytest.mark.asyncio
async def test_runtime_recovers_wrong_app_context_before_retrying_screen_step(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _TaskScreenServices(
        tmp_path,
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(
                summary="Continue butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Checkout",
                accessibility=[{"label": "Continue", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}],
                vision=[],
                ocr_text="Continue",
                ocr_lines=[],
            ),
            _ScreenState(summary="Next ekran acildi.", frontmost_app="Safari", window_title="Next", accessibility=[], vision=[], ocr_text="Next", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 2},
    )
    open_calls = {"count": 0}

    async def _system_runner(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            open_calls["count"] += 1
            screen.set_index(1)
            return {"success": True, "status": "success", "message": "Safari focused."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    runtime = OperatorTaskRuntime(desktop_host=host, system_tool_runner=_system_runner, tasks_root=tmp_path / "tasks", default_max_step_retries=0)
    result = await runtime.start_task(
        goal="Recover wrong app context",
        name="wrong-app-recovery",
        steps=[
            {
                "kind": "screen",
                "name": "continue_step",
                "instruction": "Continue butonuna tikla",
                "verify": {"frontmost_app": "Safari", "window_title_contains": "Next"},
                "repair_policy": {"max_retries": 0},
            }
        ],
        screen_services=screen.build(),
        clear_live_state=True,
    )

    assert result["success"] is True
    assert open_calls["count"] == 1
    assert result["task_state"]["replan_count"] == 1
    assert result["task_state"]["replan_history"][0]["new_step_names"][0].startswith("recover_focus_safari")


@pytest.mark.asyncio
async def test_screen_type_recovery_refocuses_retypes_and_verifies(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _DelayedTypeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Search field hazir.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}],
                vision=[],
                ocr_text="",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search field icinde kittens yaziyor.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}],
                vision=[],
                ocr_text="kittens",
                ocr_lines=[{"text": "kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}],
            ),
        ],
    )
    runtime = OperatorTaskRuntime(desktop_host=host, tasks_root=tmp_path / "tasks", default_max_step_retries=0)
    result = await runtime.start_task(
        goal="Type kittens",
        name="type-recovery",
        steps=[
            {
                "kind": "screen",
                "name": "type_query",
                "instruction": 'Search field icine "kittens" yaz',
                "verify": {"text_contains": "kittens"},
                "max_retries_per_action": 1,
                "repair_policy": {"max_retries": 0},
            }
        ],
        screen_services=screen.build(),
        clear_live_state=True,
    )

    assert result["success"] is True
    assert screen.type_events == ["kittens", "kittens"]
    assert result["task_state"]["replan_count"] == 0


def _benchmark_cases(tmp_path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []

    host1 = DesktopHost(state_path=tmp_path / "desktop1.json")
    screen1 = _TaskScreenServices(
        _mkdir(tmp_path / "screen1"),
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(summary="Safari frontmost.", frontmost_app="Safari", window_title="Start", accessibility=[], vision=[], ocr_text="Safari", ocr_lines=[]),
        ],
    )

    async def _sys1(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            screen1.set_index(1)
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner1 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host1, system_tool_runner=_sys1, tasks_root=tmp_path / "tasks1"))
    cases.append({"name": "open_app_frontmost", "request": "Safari'yi aç ve ekrana bak", "planner": planner1, "screen_services": screen1.build()})

    host2 = DesktopHost(state_path=tmp_path / "desktop2.json")
    screen2 = _DelayedTypeScreenServices(
        _mkdir(tmp_path / "screen2"),
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(summary="Search field hazir.", frontmost_app="Safari", window_title="Search", accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}], vision=[], ocr_text="", ocr_lines=[]),
            _ScreenState(summary="Search field icinde kittens yaziyor.", frontmost_app="Safari", window_title="Search", accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}], vision=[], ocr_text="kittens", ocr_lines=[{"text": "kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}]),
        ],
    )

    async def _sys2(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            screen2.set_index(1)
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner2 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host2, system_tool_runner=_sys2, tasks_root=tmp_path / "tasks2"))
    cases.append({"name": "type_visible_field", "request": "Safari'yi aç ve arama kutusuna kittens yaz", "planner": planner2, "screen_services": screen2.build()})

    host3 = DesktopHost(state_path=tmp_path / "desktop3.json")
    screen3 = _TaskScreenServices(
        _mkdir(tmp_path / "screen3"),
        [
            _ScreenState(summary="Continue butonu gorunuyor.", frontmost_app="Safari", window_title="Checkout", accessibility=[{"label": "Continue", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Continue", ocr_lines=[]),
            _ScreenState(summary="Next ekran acildi.", frontmost_app="Safari", window_title="Next", accessibility=[], vision=[], ocr_text="Next", ocr_lines=[]),
        ],
        delayed_click_transitions={(360, 106): {"after": 1, "to": 1}},
    )

    async def _sys3(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner3 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host3, system_tool_runner=_sys3, tasks_root=tmp_path / "tasks3"))
    cases.append({"name": "click_button_transition", "request": "Safari'yi aç ve Continue butonuna tıkla", "planner": planner3, "screen_services": screen3.build()})

    host4 = DesktopHost(state_path=tmp_path / "desktop4.json")
    browser4 = _TaskBrowserServices(
        tmp_path / "browser4",
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(url="https://search.local", title="Search", visible_text="Search", html="<html><body><input id='q'/></body></html>", selectors={"#q": {"text": ""}}, links=[], table={}),
            _PageState(url="https://search.local?q=kittens", title="Results", visible_text="Results for kittens", html="<html><body>Results for kittens</body></html>", selectors={"#results": {"text": "Results for kittens"}}, links=[], table={}),
        ],
        url_map={"https://search.local": 1},
        submit_transitions={(1, "#q"): 2},
        block_submit_attempts=2,
    )
    planner4 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host4, tasks_root=tmp_path / "tasks4"))
    cases.append({"name": "browser_fill_submit", "request": 'https://search.local aç ve arama kutusuna "kittens" yaz ve submit et', "planner": planner4, "browser_services": browser4.build()})

    host5 = DesktopHost(state_path=tmp_path / "desktop5.json")
    browser5 = _TaskBrowserServices(
        tmp_path / "browser5",
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={}),
        ],
        url_map={"https://upload.local": 0},
    )
    screen5 = _TaskScreenServices(
        _mkdir(tmp_path / "screen5"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Upload tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 1},
    )

    async def _sys5(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner5 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host5, system_tool_runner=_sys5, tasks_root=tmp_path / "tasks5"))
    cases.append({"name": "native_dialog_fallback", "request": "https://upload.local aç ve yükleme diyaloğunu onayla", "planner": planner5, "browser_services": browser5.build(), "screen_services": screen5.build()})

    host6 = DesktopHost(state_path=tmp_path / "desktop6.json")
    browser6 = _TaskBrowserServices(
        tmp_path / "browser6",
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(
                url="https://login.local",
                title="Login",
                visible_text="Email Password Login",
                html="<html><body><input id='email'/><input id='password'/><button id='login'>Login</button></body></html>",
                selectors={"#email": {"text": ""}, "#password": {"text": ""}, "#login": {"text": "Login"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://login.local/dashboard",
                title="Dashboard",
                visible_text="Welcome back",
                html="<html><body>Welcome back</body></html>",
                selectors={"#dashboard": {"text": "Welcome back"}},
                links=[],
                table={},
            ),
        ],
        url_map={"https://login.local": 1},
        click_transitions={(1, "#login"): 2},
    )
    planner6 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host6, tasks_root=tmp_path / "tasks6"))
    cases.append(
        {
            "name": "login_form_fill",
            "request": 'https://login.local aç ve email alanına "user@example.com" yaz, şifre alanına "secret123" yaz ve giriş yap',
            "planner": planner6,
            "browser_services": browser6.build(),
        }
    )

    host7 = DesktopHost(state_path=tmp_path / "desktop7.json")
    browser7 = _TaskBrowserServices(
        tmp_path / "browser7",
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={}),
        ],
        url_map={"https://upload.local": 0},
    )
    screen7 = _TaskScreenServices(
        _mkdir(tmp_path / "screen7"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Upload tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 1},
    )

    async def _sys7(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner7 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host7, system_tool_runner=_sys7, tasks_root=tmp_path / "tasks7"))
    cases.append(
        {
            "name": "upload_flow",
            "request": "Safari'yi aç ve https://upload.local adresini aç ve yükleme diyaloğunu onayla",
            "planner": planner7,
            "browser_services": browser7.build(),
            "screen_services": screen7.build(),
        }
    )

    host8 = DesktopHost(state_path=tmp_path / "desktop8.json")
    browser8 = _TaskBrowserServices(
        tmp_path / "browser8",
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(
                url="https://wizard.local",
                title="Wizard Start",
                visible_text="Continue",
                html="<html><body><button id='continue'>Continue</button></body></html>",
                selectors={"#continue": {"text": "Continue"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://wizard.local/step-2",
                title="Wizard Step 2",
                visible_text="Next",
                html="<html><body><button id='next'>Next</button></body></html>",
                selectors={"#next": {"text": "Next"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://wizard.local/complete",
                title="Wizard Complete",
                visible_text="All steps complete",
                html="<html><body>All steps complete</body></html>",
                selectors={"#done": {"text": "All steps complete"}},
                links=[],
                table={},
            ),
        ],
        url_map={"https://wizard.local": 1},
        click_transitions={(1, "#continue"): 2, (2, "#next"): 3},
    )
    planner8 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host8, tasks_root=tmp_path / "tasks8"))
    cases.append(
        {
            "name": "multi_step_browser_navigation",
            "request": "https://wizard.local aç ve Continue butonuna tıkla sonra Next butonuna tıkla",
            "planner": planner8,
            "browser_services": browser8.build(),
        }
    )

    host9 = DesktopHost(state_path=tmp_path / "desktop9.json")
    screen9 = _TaskScreenServices(
        _mkdir(tmp_path / "screen9"),
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(summary="Continue butonu gorunuyor.", frontmost_app="Safari", window_title="Checkout", accessibility=[{"label": "Continue", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Continue", ocr_lines=[]),
            _ScreenState(summary="Next ekran acildi.", frontmost_app="Safari", window_title="Next", accessibility=[], vision=[], ocr_text="Next", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 2},
    )
    wrong_focus_calls = {"count": 0}

    async def _sys9(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            wrong_focus_calls["count"] += 1
            if wrong_focus_calls["count"] >= 2:
                screen9.set_index(1)
            return {"success": True, "status": "success", "message": "Safari focus attempted."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner9 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host9, system_tool_runner=_sys9, tasks_root=tmp_path / "tasks9", default_max_step_retries=0))
    cases.append(
        {
            "name": "wrong_window_recovery",
            "request": "Safari'yi aç ve Continue butonuna tıkla",
            "planner": planner9,
            "screen_services": screen9.build(),
        }
    )

    host10 = DesktopHost(state_path=tmp_path / "desktop10.json")
    browser10 = _TaskBrowserServices(
        tmp_path / "browser10",
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={}),
            _PageState(url="https://upload.local/complete", title="Upload Complete", visible_text="Upload Complete", html="<html><body>Upload Complete</body></html>", selectors={"#complete": {"text": "Upload Complete"}}, links=[], table={}),
        ],
        url_map={"https://upload.local": 0},
    )
    screen10 = _CoupledDialogScreenServices(
        _mkdir(tmp_path / "screen10"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Upload tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        on_confirm=lambda: browser10.__setattr__("index", 1),
    )
    planner10 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host10, tasks_root=tmp_path / "tasks10"))
    cases.append(
        {
            "name": "dom_screen_dom_continuation",
            "request": "https://upload.local aç ve yükleme diyaloğunu onayla ve upload tamamlandı durumunu doğrula",
            "planner": planner10,
            "browser_services": browser10.build(),
            "screen_services": screen10.build(),
        }
    )

    host11 = DesktopHost(state_path=tmp_path / "desktop11.json")
    browser11 = _TaskBrowserServices(
        tmp_path / "browser11",
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={}),
            _PageState(url="https://upload.local/complete", title="Upload Complete", visible_text="Upload Complete", html="<html><body>Upload Complete</body></html>", selectors={"#complete": {"text": "Upload Complete"}}, links=[], table={}),
        ],
        url_map={"https://upload.local": 0},
    )
    screen11 = _CoupledDialogScreenServices(
        _mkdir(tmp_path / "screen11"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Upload tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        on_confirm=lambda: setattr(browser11, "index", 1),
    )
    planner11 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host11, tasks_root=tmp_path / "tasks11"))
    cases.append(
        {
            "name": "upload_flow_with_confirmation",
            "request": "Safari'yi aç ve https://upload.local adresini aç ve yükleme diyaloğunu onayla ve tamamlandığını doğrula",
            "planner": planner11,
            "browser_services": browser11.build(),
            "screen_services": screen11.build(),
        }
    )

    host12 = DesktopHost(state_path=tmp_path / "desktop12.json")
    screen12 = _TaskScreenServices(
        _mkdir(tmp_path / "screen12"),
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(summary="Finder acik.", frontmost_app="Finder", window_title="Finder", accessibility=[], vision=[], ocr_text="Finder", ocr_lines=[]),
            _ScreenState(summary="Search field hazir.", frontmost_app="Safari", window_title="Search", accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}], vision=[], ocr_text="", ocr_lines=[]),
            _ScreenState(summary="Search field icinde kittens yaziyor.", frontmost_app="Safari", window_title="Search", accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}], vision=[], ocr_text="kittens", ocr_lines=[{"text": "kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}]),
        ],
        type_transitions={2: 3},
    )

    async def _sys12(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name != "open_app":
            return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}
        app = str(params.get("app_name") or "")
        if app == "Finder":
            screen12.set_index(1)
        elif app == "Safari":
            screen12.set_index(2)
        return {"success": True, "status": "success", "message": f"{app} opened."}

    planner12 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host12, system_tool_runner=_sys12, tasks_root=tmp_path / "tasks12"))
    cases.append(
        {
            "name": "app_switch_focused_field_typing",
            "request": "Finder'ı aç sonra Safari'ye geç ve arama kutusuna kittens yaz",
            "planner": planner12,
            "screen_services": screen12.build(),
        }
    )

    host13 = DesktopHost(state_path=tmp_path / "desktop13.json")
    screen13 = _TaskScreenServices(
        _mkdir(tmp_path / "screen13"),
        [
            _ScreenState(summary="Safari frontmost.", frontmost_app="Safari", window_title="Login", accessibility=[], vision=[], ocr_text="Safari", ocr_lines=[]),
        ],
    )
    browser13 = _TaskBrowserServices(
        tmp_path / "browser13",
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(
                url="https://login.local",
                title="Login",
                visible_text="Email Password Login",
                html="<html><body><input id='email'/><input id='password'/><button id='login'>Login</button></body></html>",
                selectors={"#email": {"text": ""}, "#password": {"text": ""}, "#login": {"text": "Login"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://login.local/review",
                title="Review",
                visible_text="Continue",
                html="<html><body><button id='continue'>Continue</button></body></html>",
                selectors={"#continue": {"text": "Continue"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://login.local/dashboard",
                title="Dashboard",
                visible_text="Welcome back",
                html="<html><body>Welcome back</body></html>",
                selectors={"#dashboard": {"text": "Welcome back"}},
                links=[],
                table={},
            ),
        ],
        url_map={"https://login.local": 1},
        click_transitions={(1, "#login"): 2, (2, "#continue"): 3},
    )

    async def _sys13(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner13 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host13, system_tool_runner=_sys13, tasks_root=tmp_path / "tasks13"))
    cases.append(
        {
            "name": "long_mixed_login_continue",
            "request": 'Safari\'yi aç ve https://login.local aç ve email alanına "user@example.com" yaz, şifre alanına "secret123" yaz ve giriş yap sonra Continue butonuna tıkla',
            "planner": planner13,
            "browser_services": browser13.build(),
            "screen_services": screen13.build(),
        }
    )

    host14 = DesktopHost(state_path=tmp_path / "desktop14.json")
    browser14 = _TaskBrowserServices(
        tmp_path / "browser14",
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={}),
            _PageState(url="https://upload.local/review", title="Review Upload", visible_text="Save", html="<html><body><button id='save'>Save</button></body></html>", selectors={"#save": {"text": "Save"}}, links=[], table={}),
            _PageState(url="https://upload.local/complete", title="Upload Complete", visible_text="Upload Complete", html="<html><body>Upload Complete</body></html>", selectors={"#complete": {"text": "Upload Complete"}}, links=[], table={}),
        ],
        url_map={"https://upload.local": 0},
        click_transitions={(1, "#save"): 2},
    )
    screen14 = _CoupledDialogScreenServices(
        _mkdir(tmp_path / "screen14"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Review upload ekrani acildi.", frontmost_app="Safari", window_title="Review Upload", accessibility=[], vision=[], ocr_text="Save", ocr_lines=[]),
        ],
        on_confirm=lambda: setattr(browser14, "index", 1),
    )

    async def _sys14(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner14 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host14, system_tool_runner=_sys14, tasks_root=tmp_path / "tasks14"))
    cases.append(
        {
            "name": "browser_desktop_browser_continuation",
            "request": "Safari'yi aç ve https://upload.local adresini aç ve yükleme diyaloğunu onayla sonra Save butonuna tıkla",
            "planner": planner14,
            "browser_services": browser14.build(),
            "screen_services": screen14.build(),
        }
    )

    host15 = DesktopHost(state_path=tmp_path / "desktop15.json")
    browser15 = _TaskBrowserServices(
        tmp_path / "browser15",
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(url="https://search.local", title="Search", visible_text="Search", html="<html><body><input id='q'/></body></html>", selectors={"#q": {"text": ""}}, links=[], table={}),
            _PageState(url="https://search.local?q=kittens", title="Results", visible_text="Results for kittens", html="<html><body>Results for kittens</body></html>", selectors={"#results": {"text": "Results for kittens"}}, links=[], table={}),
        ],
        url_map={"https://search.local": 1},
        submit_transitions={(1, "#q"): 2},
    )
    planner15 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host15, tasks_root=tmp_path / "tasks15"))
    cases.append(
        {
            "name": "telegram_triggered_operator_flow",
            "request": '@ElyanBot /run https://search.local aç ve arama kutusuna "kittens" yaz ve submit et',
            "planner": planner15,
            "browser_services": browser15.build(),
        }
    )

    host16 = DesktopHost(state_path=tmp_path / "desktop16.json")
    screen16 = _TaskScreenServices(
        _mkdir(tmp_path / "screen16"),
        [
            _ScreenState(summary="Continue butonu gorunuyor.", frontmost_app="Safari", window_title="Checkout", accessibility=[{"label": "Continue", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Continue", ocr_lines=[]),
            _ScreenState(summary="Next ekran acildi.", frontmost_app="Safari", window_title="Next", accessibility=[], vision=[], ocr_text="Next", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 1},
    )

    async def _sys16(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner16 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host16, system_tool_runner=_sys16, tasks_root=tmp_path / "tasks16"))
    cases.append(
        {
            "name": "telegram_desktop_task_completion",
            "request": "@ElyanBot /run Safari'yi aç ve Continue butonuna tıkla",
            "planner": planner16,
            "screen_services": screen16.build(),
        }
    )

    host17 = DesktopHost(state_path=tmp_path / "desktop17.json")

    async def _sys17(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name != "research_document_delivery":
            return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}
        topic = str(params.get("topic") or "Research Topic").strip()
        out_dir = _mkdir(tmp_path / "research17")
        report_path = out_dir / "research_report.md"
        sources_path = out_dir / "sources.json"
        report_path.write_text(f"# {topic}\n\n- Finding 1\n- Finding 2\n", encoding="utf-8")
        sources_path.write_text(json.dumps([{"title": "Source 1", "url": "https://example.com"}], indent=2), encoding="utf-8")
        return {
            "success": True,
            "status": "success",
            "message": f"{topic} report ready.",
            "summary": f"{topic} report ready.",
            "artifacts": [_artifact(report_path, "text"), _artifact(sources_path, "json")],
        }

    planner17 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host17, system_tool_runner=_sys17, tasks_root=tmp_path / "tasks17"))
    cases.append(
        {
            "name": "research_document_creation_verification",
            "request": "AI agents hakkında araştırma yap ve rapor oluştur",
            "planner": planner17,
        }
    )

    host18 = DesktopHost(state_path=tmp_path / "desktop18.json")
    screen18 = _TaskScreenServices(
        _mkdir(tmp_path / "screen18"),
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(summary="Finder acik.", frontmost_app="Finder", window_title="Finder", accessibility=[], vision=[], ocr_text="Finder", ocr_lines=[]),
            _ScreenState(summary="Terminal acik.", frontmost_app="Terminal", window_title="Terminal", accessibility=[], vision=[], ocr_text="Terminal", ocr_lines=[]),
            _ScreenState(summary="Cursor acik.", frontmost_app="Cursor", window_title="Cursor", accessibility=[], vision=[], ocr_text="Cursor", ocr_lines=[]),
            _ScreenState(summary="Search field hazir.", frontmost_app="Safari", window_title="Search", accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}], vision=[], ocr_text="", ocr_lines=[]),
            _ScreenState(summary="Search field icinde kittens yaziyor.", frontmost_app="Safari", window_title="Search", accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}], vision=[], ocr_text="kittens", ocr_lines=[{"text": "kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}]),
        ],
        type_transitions={4: 5},
    )

    async def _sys18(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name != "open_app":
            return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}
        app = str(params.get("app_name") or "")
        index_map = {"Finder": 1, "Terminal": 2, "Cursor": 3, "Safari": 4}
        if app in index_map:
            screen18.set_index(index_map[app])
        return {"success": True, "status": "success", "message": f"{app} opened."}

    planner18 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host18, system_tool_runner=_sys18, tasks_root=tmp_path / "tasks18"))
    cases.append(
        {
            "name": "app_switch_finder_safari_cursor_terminal",
            "request": "Finder'ı aç sonra Terminal'i aç sonra Cursor'u aç sonra Safari'ye geç ve arama kutusuna kittens yaz",
            "planner": planner18,
            "screen_services": screen18.build(),
        }
    )

    host19 = DesktopHost(state_path=tmp_path / "desktop19.json")
    browser19 = _TaskBrowserServices(
        tmp_path / "browser19",
        [
            _PageState(
                url="https://login.local",
                title="Login",
                visible_text="Email Password Login",
                html="<html><body><input id='email'/><input id='password'/><button id='login'>Login</button></body></html>",
                selectors={"#email": {"text": ""}, "#password": {"text": ""}, "#login": {"text": "Login"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://login.local/review",
                title="Review",
                visible_text="Continue",
                html="<html><body><button id='continue'>Continue</button></body></html>",
                selectors={"#continue": {"text": "Continue"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://upload.local",
                title="Upload",
                visible_text="Upload",
                html="<html><body><button id='upload'>Upload</button></body></html>",
                selectors={"#upload": {"text": "Upload"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://upload.local/complete",
                title="Upload Complete",
                visible_text="Upload Complete",
                html="<html><body>Upload Complete</body></html>",
                selectors={"#complete": {"text": "Upload Complete"}},
                links=[],
                table={},
            ),
        ],
        url_map={"https://login.local": 0, "https://upload.local": 2},
        click_transitions={(0, "#login"): 1, (1, "#continue"): 2},
    )
    screen19 = _CoupledDialogScreenServices(
        _mkdir(tmp_path / "screen19"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Upload tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        on_confirm=lambda: setattr(browser19, "index", 3),
    )

    async def _sys19(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app":
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    planner19 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host19, system_tool_runner=_sys19, tasks_root=tmp_path / "tasks19"))
    cases.append(
        {
            "name": "login_continue_upload_flow",
            "request": 'Safari\'yi aç ve https://login.local aç ve email alanına "user@example.com" yaz, şifre alanına "secret123" yaz ve giriş yap sonra Continue butonuna tıkla sonra https://upload.local aç ve yükleme diyaloğunu onayla ve tamamlandığını doğrula',
            "planner": planner19,
            "browser_services": browser19.build(),
            "screen_services": screen19.build(),
        }
    )

    host20 = DesktopHost(state_path=tmp_path / "desktop20.json")
    browser20 = _TaskBrowserServices(
        tmp_path / "browser20",
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={}),
            _PageState(url="https://upload.local/review", title="Review Upload", visible_text="Save", html="<html><body><button id='save'>Save</button></body></html>", selectors={"#save": {"text": "Save"}}, links=[], table={}),
            _PageState(url="https://upload.local/complete", title="Upload Complete", visible_text="Upload Complete", html="<html><body>Upload Complete</body></html>", selectors={"#complete": {"text": "Upload Complete"}}, links=[], table={}),
        ],
        url_map={"https://upload.local": 0},
        click_transitions={(1, "#save"): 2},
    )
    screen20_fail = _TaskScreenServices(
        _mkdir(tmp_path / "screen20_fail"),
        [
            _ScreenState(summary="Native dialog acik ama Open hedefi yok.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[], vision=[], ocr_text="", ocr_lines=[]),
        ],
    )
    screen20_resume = _CoupledDialogScreenServices(
        _mkdir(tmp_path / "screen20_resume"),
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Review upload ekrani acildi.", frontmost_app="Safari", window_title="Review Upload", accessibility=[], vision=[], ocr_text="Save", ocr_lines=[]),
        ],
        on_confirm=lambda: setattr(browser20, "index", 1),
    )
    planner20 = LiveOperatorTaskPlanner(task_runtime=OperatorTaskRuntime(desktop_host=host20, tasks_root=tmp_path / "tasks20", default_max_step_retries=0))

    async def _runner20(case: dict[str, Any]) -> dict[str, Any]:
        first = await planner20.start_request(
            str(case.get("request") or ""),
            browser_services=browser20.build(),
            screen_services=screen20_fail.build(),
            clear_live_state=True,
        )
        assert first["success"] is False
        resumed = await planner20.resume_request(
            str(first.get("task_id") or ""),
            browser_services=browser20.build(),
            screen_services=screen20_resume.build(),
        )
        return resumed

    cases.append(
        {
            "name": "interrupted_resume_after_partial_completion",
            "request": "https://upload.local aç ve yükleme diyaloğunu onayla sonra Save butonuna tıkla",
            "planner": planner20,
            "browser_services": browser20.build(),
            "runner": _runner20,
        }
    )

    return cases


@pytest.mark.asyncio
async def test_production_benchmark_runner_persists_summary_and_exact_rows(tmp_path: Path):
    report = await run_production_benchmarks(_benchmark_cases(tmp_path), reports_root=tmp_path / "reports")

    assert report["success"] is True
    summary = report["summary"]
    assert summary["pass_count"] == 20
    assert summary["total"] == 20
    assert len(summary["rows"]) == 20
    assert {row["name"] for row in summary["rows"]} == {
        "open_app_frontmost",
        "type_visible_field",
        "click_button_transition",
        "browser_fill_submit",
        "native_dialog_fallback",
        "login_form_fill",
        "upload_flow",
        "multi_step_browser_navigation",
        "wrong_window_recovery",
        "dom_screen_dom_continuation",
        "upload_flow_with_confirmation",
        "app_switch_focused_field_typing",
        "long_mixed_login_continue",
        "browser_desktop_browser_continuation",
        "telegram_triggered_operator_flow",
        "telegram_desktop_task_completion",
        "research_document_creation_verification",
        "app_switch_finder_safari_cursor_terminal",
        "login_continue_upload_flow",
        "interrupted_resume_after_partial_completion",
    }
    for row in summary["rows"]:
        assert isinstance(row.get("plan_steps"), list)
        assert isinstance(row.get("completed_step_names"), list)
    for artifact in report["artifacts"]:
        assert Path(str(artifact["path"])).exists()
    artifact_names = {Path(str(artifact["path"])).name for artifact in report["artifacts"]}
    assert {"summary.json", "summary.md", "dashboard.json", "dashboard.md"} <= artifact_names
