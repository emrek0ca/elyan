from __future__ import annotations

from pathlib import Path

import pytest

from core.runtime import DesktopHost, LiveOperatorTaskPlanner, OperatorTaskRuntime
from tests.e2e.test_operator_task_runtime import _PageState, _ScreenState, _TaskBrowserServices, _TaskScreenServices


@pytest.mark.asyncio
async def test_live_operator_planner_generates_valid_plan_from_natural_language(tmp_path: Path):
    runtime = OperatorTaskRuntime(tasks_root=tmp_path / "task_runtime")
    planner = LiveOperatorTaskPlanner(task_runtime=runtime)

    plan = planner.plan_request("Safari'yi aç ve arama kutusuna kittens yaz")

    assert plan["steps"]
    assert plan["steps"][0]["kind"] == "system"
    assert plan["steps"][0]["tool"] == "open_app"
    assert plan["steps"][1]["kind"] == "screen"
    assert "kittens" in plan["steps"][1]["instruction"].lower()
    assert plan["planning_trace"]["extracted"]["app_name"] == "Safari"
    assert plan["planning_trace"]["extracted"]["typed_text"] == "kittens"
    assert plan["planning_trace"]["bounded"] is True


@pytest.mark.asyncio
async def test_live_operator_planner_runs_generated_plan_through_task_runtime(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _TaskScreenServices(
        tmp_path,
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
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
        type_transitions={1: 2},
    )
    open_calls = {"count": 0}

    async def _system_runner(tool_name: str, params: dict[str, object]) -> dict[str, object]:
        if tool_name == "open_app":
            open_calls["count"] += 1
            screen.set_index(1)
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    runtime = OperatorTaskRuntime(desktop_host=host, system_tool_runner=_system_runner, tasks_root=tmp_path / "task_runtime")
    planner = LiveOperatorTaskPlanner(task_runtime=runtime)

    out = await planner.start_request("Safari'yi aç ve arama kutusuna kittens yaz", screen_services=screen.build(), clear_live_state=True)

    assert out["success"] is True
    assert out["task_result"]["task_state"]["completed_steps"] == [1, 2]
    assert out["comparison"]["planned_step_count"] == 2
    assert out["comparison"]["completed_step_count"] == 2
    assert open_calls["count"] == 1

    inspected = await planner.inspect_task_plan(out["task_id"])
    assert inspected["plan"]["steps"][1]["kind"] == "screen"
    assert inspected["planning_trace"]["matched_rules"]


@pytest.mark.asyncio
async def test_live_operator_planner_failed_task_can_resume_safely(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _TaskScreenServices(
        tmp_path,
        [
            _ScreenState(summary="Desktop.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
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
        type_transitions={},
    )
    open_calls = {"count": 0}

    async def _system_runner(tool_name: str, params: dict[str, object]) -> dict[str, object]:
        if tool_name == "open_app":
            open_calls["count"] += 1
            screen.set_index(1)
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    runtime = OperatorTaskRuntime(desktop_host=host, system_tool_runner=_system_runner, tasks_root=tmp_path / "task_runtime", default_max_step_retries=0)
    planner = LiveOperatorTaskPlanner(task_runtime=runtime)

    first = await planner.start_request("Safari'yi aç ve arama kutusuna kittens yaz", screen_services=screen.build(), clear_live_state=True)
    assert first["success"] is False
    assert first["comparison"]["completed_step_count"] == 1

    screen.type_transitions = {1: 2}
    resumed = await planner.resume_request(first["task_id"], screen_services=screen.build())

    assert resumed["success"] is True
    assert open_calls["count"] == 1
    assert resumed["comparison"]["completed_step_count"] == 2
    assert resumed["comparison"]["steps"][0]["attempts"] == 1
    assert resumed["comparison"]["steps"][1]["attempts"] >= 2


@pytest.mark.asyncio
async def test_live_operator_planner_builds_and_runs_mixed_browser_screen_plan(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    browser = _TaskBrowserServices(
        tmp_path,
        [
            _PageState(url="https://upload.local", title="Upload", visible_text="Upload", html="<html><body><button id='upload'>Upload</button></body></html>", selectors={"#upload": {"text": "Upload"}}, links=[], table={})
        ],
        url_map={"https://upload.local": 0},
    )
    screen = _TaskScreenServices(
        tmp_path,
        [
            _ScreenState(summary="Native dialog acik. Open gorunuyor.", frontmost_app="Safari", window_title="Upload Dialog", accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}], vision=[], ocr_text="Open", ocr_lines=[]),
            _ScreenState(summary="Upload tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 1},
    )
    open_calls = {"count": 0}

    async def _system_runner(tool_name: str, params: dict[str, object]) -> dict[str, object]:
        if tool_name == "open_app":
            open_calls["count"] += 1
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    runtime = OperatorTaskRuntime(desktop_host=host, system_tool_runner=_system_runner, tasks_root=tmp_path / "task_runtime")
    planner = LiveOperatorTaskPlanner(task_runtime=runtime)

    plan = planner.plan_request("upload sayfasını aç ve yükleme diyaloğunu onayla")
    assert [step["kind"] for step in plan["steps"]] == ["system", "browser", "browser"]
    assert plan["steps"][2]["native_dialog_expected"] is True

    out = await planner.start_request(
        "upload sayfasını aç ve yükleme diyaloğunu onayla",
        browser_services=browser.build(),
        screen_services=screen.build(),
        clear_live_state=True,
    )

    assert out["success"] is True
    assert out["comparison"]["planned_step_count"] == 3
    assert out["task_result"]["task_state"]["desktop_host_state"]["active_window"]["title"] == "Upload Complete"
    assert open_calls["count"] == 1


@pytest.mark.asyncio
async def test_live_operator_planner_keeps_ambiguous_request_bounded_and_safe(tmp_path: Path):
    runtime = OperatorTaskRuntime(tasks_root=tmp_path / "task_runtime")
    planner = LiveOperatorTaskPlanner(task_runtime=runtime)

    plan = planner.plan_request("tarayıcıyı aç, siteye git, giriş alanını doldur")

    assert plan["planning_trace"]["bounded"] is True
    assert "url" in plan["planning_trace"]["missing_inputs"]
    assert "text" in plan["planning_trace"]["missing_inputs"]
    assert any(step.get("mode") == "inspect" for step in plan["steps"])
    assert not any(step.get("kind") == "browser" and step.get("action") == "type" and not str(step.get("text") or "").strip() for step in plan["steps"])


@pytest.mark.asyncio
async def test_live_operator_planner_ignores_email_domains_when_extracting_urls(tmp_path: Path):
    runtime = OperatorTaskRuntime(tasks_root=tmp_path / "task_runtime")
    planner = LiveOperatorTaskPlanner(task_runtime=runtime)

    plan = planner.plan_request(
        'Safari\'yi aç ve https://login.local aç ve email alanına "user@example.com" yaz, şifre alanına "secret123" yaz ve giriş yap sonra Continue butonuna tıkla sonra https://upload.local aç ve yükleme diyaloğunu onayla ve tamamlandığını doğrula'
    )

    browser_open_steps = [step for step in plan["steps"] if step.get("kind") == "browser" and step.get("action") == "open"]
    assert [step.get("url") for step in browser_open_steps] == ["https://login.local", "https://upload.local"]
