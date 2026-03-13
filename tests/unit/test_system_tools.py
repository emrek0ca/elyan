from pathlib import Path

import pytest
import asyncio

from core.contracts.tool_result import coerce_tool_result
from tools import system_tools


class _Proc:
    def __init__(self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"", on_communicate=None):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._on_communicate = on_communicate

    async def communicate(self):
        if callable(self._on_communicate):
            self._on_communicate()
        return self._stdout, self._stderr


@pytest.mark.asyncio
async def test_open_app_reports_frontmost_verification(monkeypatch):
    async def _fake_exec(*_args, **_kwargs):
        return _Proc(returncode=0, stdout=b"", stderr=b"")

    async def _fake_osascript(script: str):
        _ = script
        return (0, "", "")

    async def _fake_frontmost():
        return "Safari"

    monkeypatch.setattr(system_tools.asyncio, "create_subprocess_exec", _fake_exec)
    monkeypatch.setattr(system_tools, "_run_osascript", _fake_osascript)
    monkeypatch.setattr(system_tools, "_get_frontmost_app_name", _fake_frontmost)

    result = await system_tools.open_app("Safari", settle_timeout_s=0.0)
    assert result["success"] is True
    assert result["status"] == "success"
    assert result["verified"] is True
    assert result["frontmost_app"] == "Safari"
    assert (result.get("data") or {}).get("app_name") == "Safari"


@pytest.mark.asyncio
async def test_key_combo_target_app_mismatch_returns_failure(monkeypatch):
    async def _fake_osascript(script: str):
        _ = script
        return (0, "", "")

    async def _fake_press_key(key: str = "", modifiers=None):
        return {"success": True, "key": key, "modifiers": modifiers or []}

    async def _fake_frontmost():
        return "Finder"

    monkeypatch.setattr(system_tools, "_run_osascript", _fake_osascript)
    monkeypatch.setattr(system_tools, "press_key", _fake_press_key)
    monkeypatch.setattr(system_tools, "_get_frontmost_app_name", _fake_frontmost)

    result = await system_tools.key_combo("cmd+t", target_app="Google Chrome", settle_ms=0)
    assert result["success"] is False
    assert "hedef dışı uygulamaya gitti" in str(result.get("error") or "")
    assert result.get("frontmost_app") == "Finder"


@pytest.mark.asyncio
async def test_take_screenshot_waits_for_process_and_verifies_file(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def _fake_exec(*args, **kwargs):
        _ = kwargs
        target = Path(args[-1])
        return _Proc(
            returncode=0,
            on_communicate=lambda: (target.parent.mkdir(parents=True, exist_ok=True), target.write_bytes(b"png-bytes")),
        )

    monkeypatch.setattr(system_tools.asyncio, "create_subprocess_exec", _fake_exec)
    result = await system_tools.take_screenshot("proof.png")
    assert result["success"] is True
    assert result["status"] == "success"
    assert result["size_bytes"] > 0
    assert Path(result["path"]).exists()
    normalized = coerce_tool_result(result, tool="take_screenshot")
    assert normalized.status == "success"
    assert normalized.artifacts


@pytest.mark.asyncio
async def test_take_screenshot_returns_error_on_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def _fake_exec(*_args, **_kwargs):
        return _Proc(returncode=1, stderr=b"permission denied")

    monkeypatch.setattr(system_tools.asyncio, "create_subprocess_exec", _fake_exec)
    result = await system_tools.take_screenshot("proof.png")
    assert result["success"] is False
    assert result["status"] == "failed"
    assert "permission denied" in str(result.get("error") or "")


@pytest.mark.asyncio
async def test_open_project_in_ide_falls_back_to_finder(monkeypatch, tmp_path):
    project = tmp_path / "demo"
    project.mkdir(parents=True)

    monkeypatch.setattr(system_tools.shutil, "which", lambda _name: None)

    async def _fake_exec(*args, **kwargs):
        _ = kwargs
        if len(args) >= 3 and args[0] == "open" and args[1] == "-a":
            return _Proc(returncode=1, stderr=b"app not found")
        if len(args) >= 2 and args[0] == "open":
            return _Proc(returncode=0, stdout=b"finder opened")
        return _Proc(returncode=1, stderr=b"unexpected")

    monkeypatch.setattr(system_tools.asyncio, "create_subprocess_exec", _fake_exec)

    result = await system_tools.open_project_in_ide(str(project), ide="vscode")
    assert result["success"] is True
    assert result.get("method") == "finder-fallback"
    assert "warning" in result


@pytest.mark.asyncio
async def test_computer_use_generates_plan_from_goal(monkeypatch):
    async def _ok(**kwargs):
        return {"success": True, **kwargs}

    monkeypatch.setattr(system_tools, "open_app", lambda app_name="": _ok(app_name=app_name))
    monkeypatch.setattr(system_tools, "open_url", lambda url="", browser=None: _ok(url=url, browser=browser))
    monkeypatch.setattr(system_tools, "type_text", lambda text="", press_enter=False: _ok(text=text, press_enter=press_enter))
    monkeypatch.setattr(system_tools, "press_key", lambda key="", modifiers=None: _ok(key=key, modifiers=modifiers or []))
    monkeypatch.setattr(system_tools, "take_screenshot", lambda filename=None: _ok(path=f"/tmp/{filename or 'x.png'}"))

    result = await system_tools.computer_use(
        steps=None,
        goal='Safari aç ve "köpek resimleri" ara enter bas',
        auto_plan=True,
        final_screenshot=False,
        vision_feedback=False,
    )
    assert result["success"] is True
    assert result.get("generated_from_goal") is True
    assert isinstance(result.get("planned_steps"), list) and result["planned_steps"]


@pytest.mark.asyncio
async def test_computer_use_vision_feedback_marks_goal_achieved(monkeypatch):
    async def _ok(**kwargs):
        return {"success": True, **kwargs}

    monkeypatch.setattr(system_tools, "open_app", lambda app_name="": _ok(app_name=app_name))
    monkeypatch.setattr(system_tools, "open_url", lambda url="", browser=None: _ok(url=url, browser=browser))
    monkeypatch.setattr(system_tools, "key_combo", lambda combo="": _ok(combo=combo))
    monkeypatch.setattr(system_tools, "type_text", lambda text="", press_enter=False: _ok(text=text, press_enter=press_enter))
    monkeypatch.setattr(system_tools, "take_screenshot", lambda filename=None: _ok(path=f"/tmp/{filename or 'x.png'}"))
    monkeypatch.setattr(
        system_tools,
        "analyze_screen",
        lambda prompt="": _ok(summary="Google sonuçları: köpek resimleri", ocr="köpek resimleri"),
    )

    result = await system_tools.computer_use(
        steps=None,
        goal="google'da köpek resimleri ara",
        auto_plan=True,
        final_screenshot=False,
        vision_feedback=True,
        max_feedback_loops=1,
    )
    assert result["success"] is True
    assert result.get("goal_achieved") is True
    assert isinstance(result.get("vision_observations"), list) and result["vision_observations"]


@pytest.mark.asyncio
async def test_computer_use_generates_terminal_plan_from_goal(monkeypatch):
    events = []

    async def _ok(**kwargs):
        return {"success": True, **kwargs}

    async def _fake_open_app(app_name=""):
        events.append(("open_app", app_name))
        return await _ok(app_name=app_name)

    async def _fake_type_text(text="", press_enter=False):
        events.append(("type_text", text, press_enter))
        return await _ok(text=text, press_enter=press_enter)

    monkeypatch.setattr(system_tools, "open_app", _fake_open_app)
    monkeypatch.setattr(system_tools, "type_text", _fake_type_text)
    monkeypatch.setattr(system_tools, "take_screenshot", lambda filename=None: _ok(path=f"/tmp/{filename or 'x.png'}"))

    result = await system_tools.computer_use(
        steps=None,
        goal='Terminal aç ve "ls -la" yaz',
        auto_plan=True,
        final_screenshot=False,
        vision_feedback=False,
    )

    assert result["success"] is True
    assert ("open_app", "Terminal") in events
    assert ("type_text", "ls -la", True) in events


@pytest.mark.asyncio
async def test_vision_operator_loop_handles_read_only_goal_without_action(monkeypatch):
    called = {"computer_use": 0}

    async def _fake_analyze_screen(prompt=""):
        _ = prompt
        return {
            "success": True,
            "summary": "On planda Cursor acik gorunuyor.",
            "provider": "mock",
            "ui_map": {"frontmost_app": "Cursor", "running_apps": ["Cursor"], "coordinates_detected": False},
            "path": "/tmp/read_only.png",
        }

    async def _fake_computer_use(**kwargs):
        _ = kwargs
        called["computer_use"] += 1
        return {"success": True}

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr(system_tools, "computer_use", _fake_computer_use)

    result = await system_tools.vision_operator_loop("ekrana bak ve durumu soyle")

    assert result["success"] is True
    assert result["goal_achieved"] is True
    assert result["iterations"][0]["result"] == "inspection_only"
    assert called["computer_use"] == 0


@pytest.mark.asyncio
async def test_operator_mission_control_executes_subtasks_and_collects_results(monkeypatch):
    async def _fake_analyze_screen(prompt=""):
        _ = prompt
        return {
            "success": True,
            "summary": "On planda Mail acik gorunuyor.",
            "provider": "mock",
            "ui_map": {"frontmost_app": "Mail", "running_apps": ["Mail"], "coordinates_detected": False},
            "path": "/tmp/mail.png",
        }

    async def _fake_vision_operator_loop(objective, **kwargs):
        _ = kwargs
        return {
            "success": True,
            "goal_achieved": True,
            "message": f"{objective} tamamlandi",
            "screenshots": ["/tmp/op.png"],
        }

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr(system_tools, "vision_operator_loop", _fake_vision_operator_loop)

    result = await system_tools.operator_mission_control("maili kontrol et ve sonra safari ac")

    assert result["success"] is True
    assert result["objective_count"] == 2
    assert result["completed_subtasks"] == 2
    assert len(result["subtasks"]) == 2
    assert result["screenshots"]


@pytest.mark.asyncio
async def test_operator_mission_control_runs_read_only_groups_concurrently(monkeypatch):
    state = {"current": 0, "max": 0}

    async def _fake_analyze_screen(prompt=""):
        _ = prompt
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(0.05)
        state["current"] -= 1
        return {
            "success": True,
            "summary": "Kontrol tamam.",
            "provider": "mock",
            "ui_map": {"frontmost_app": "Mail", "running_apps": ["Mail", "Finder"], "coordinates_detected": False},
            "path": "/tmp/inspect.png",
        }

    async def _unexpected_vision_operator_loop(*args, **kwargs):
        raise AssertionError(f"vision_operator_loop should not run for inspect group: {args} {kwargs}")

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr(system_tools, "vision_operator_loop", _unexpected_vision_operator_loop)

    result = await system_tools.operator_mission_control("maili kontrol et ve sonra finderi kontrol et")

    assert result["success"] is True
    assert state["max"] >= 2
    assert result["parallelizable_groups"] == [[1, 2]]
    assert result["executed_parallel_groups"] == [[1, 2]]
    assert result["scheduler_plan"][0]["execution_lane"] == "mail"
    assert result["scheduler_plan"][1]["execution_lane"] == "filesystem"
    assert result["lane_recovery_attempts"] == []
    assert all(item["execution_mode"] == "parallel_inspect" for item in result["subtasks"])


@pytest.mark.asyncio
async def test_computer_use_times_out_slow_step(monkeypatch):
    async def _slow_open_app(app_name=""):
        _ = app_name
        await asyncio.sleep(0.2)
        return {"success": True}

    monkeypatch.setattr(system_tools, "_operator_step_timeout_s", lambda: 0.05)
    monkeypatch.setattr(system_tools, "open_app", _slow_open_app)

    result = await system_tools.computer_use(
        steps=[{"action": "open_app", "params": {"app_name": "Safari"}}],
        final_screenshot=False,
        vision_feedback=False,
    )

    assert result["success"] is False
    assert "operator_step_timeout" in str(result.get("error") or "")


@pytest.mark.asyncio
async def test_vision_operator_loop_emits_operator_budget(monkeypatch):
    async def _fake_analyze_screen(prompt=""):
        _ = prompt
        return {
            "success": True,
            "summary": "On planda Safari acik gorunuyor.",
            "provider": "mock",
            "ui_map": {"frontmost_app": "Safari", "running_apps": ["Safari"], "coordinates_detected": False},
            "path": "/tmp/safari.png",
        }

    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)

    result = await system_tools.vision_operator_loop("safari ac")

    assert result["success"] is True
    assert isinstance(result.get("operator_budget"), dict)
    assert result["operator_budget"]["elapsed_s"] >= 0


@pytest.mark.asyncio
async def test_operator_mission_control_times_out_subtask(monkeypatch):
    async def _slow_vision_operator_loop(objective, **kwargs):
        _ = (objective, kwargs)
        await asyncio.sleep(0.2)
        return {"success": True, "goal_achieved": True, "message": "ok", "screenshots": []}

    monkeypatch.setattr(system_tools, "_operator_mission_timeout_s", lambda: 0.05)
    monkeypatch.setattr(system_tools, "vision_operator_loop", _slow_vision_operator_loop)

    result = await system_tools.operator_mission_control("safari ac ve sonra maili kontrol et")

    assert result["success"] is False
    assert result["next_action"]
    assert result["timeout_s"] == 0.05


@pytest.mark.asyncio
async def test_operator_mission_control_probes_degraded_lane_before_retry(monkeypatch):
    calls = {"vision": 0, "probe": 0, "recovery": 0}

    async def _fake_vision_operator_loop(objective, **kwargs):
        _ = kwargs
        calls["vision"] += 1
        if calls["vision"] == 1:
            return {"success": False, "goal_achieved": False, "message": "ilk deneme fail", "screenshots": []}
        return {"success": True, "goal_achieved": True, "message": f"{objective} ok", "screenshots": []}

    async def _fake_analyze_screen(prompt=""):
        if "Lane recovery probe" in prompt:
            calls["probe"] += 1
            return {
                "success": True,
                "summary": "Safari browser tab ve address bar hazir",
                "path": "/tmp/probe.png",
                "ui_map": {"frontmost_app": "Safari"},
            }
        return {"success": True, "summary": "ok", "path": "/tmp/inspect.png"}

    async def _fake_computer_use(**kwargs):
        calls["recovery"] += 1
        return {"success": True, "screenshots": [], "steps": kwargs.get("steps") or []}

    monkeypatch.setattr(system_tools, "vision_operator_loop", _fake_vision_operator_loop)
    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr(system_tools, "computer_use", _fake_computer_use)

    result = await system_tools.operator_mission_control("safari aç ve sonra maili kontrol et ve sonra safaride köpek ara")

    assert result["success"] is False
    assert calls["vision"] == 2
    assert calls["probe"] == 1
    assert calls["recovery"] == 1
    assert result["lane_recovery_attempts"][0]["lane"] == "browser"
    assert result["lane_recovery_attempts"][0]["self_heal_success"] is True
    assert result["lane_recovery_attempts"][0]["self_heal_steps"][0]["action"] == "open_app"
    assert result["lane_statuses"]["browser"]["recovery_attempts"] == 1
    assert any(item["execution_mode"] == "lane_recovered_serial" for item in result["subtasks"])


@pytest.mark.asyncio
async def test_operator_mission_control_blocks_lane_when_recovery_probe_fails(monkeypatch):
    calls = {"vision": 0, "recovery": 0}

    async def _fake_vision_operator_loop(objective, **kwargs):
        _ = (objective, kwargs)
        calls["vision"] += 1
        return {"success": False, "goal_achieved": False, "message": "lane fail", "screenshots": []}

    async def _fake_analyze_screen(prompt=""):
        if "Lane recovery probe" in prompt:
            return {"success": False, "summary": "browser lane bozuk", "ui_map": {"frontmost_app": "Safari"}}
        return {"success": True, "summary": "ok", "path": "/tmp/inspect.png"}

    async def _fake_computer_use(**kwargs):
        calls["recovery"] += 1
        return {"success": True, "screenshots": [], "steps": kwargs.get("steps") or []}

    monkeypatch.setattr(system_tools, "vision_operator_loop", _fake_vision_operator_loop)
    monkeypatch.setattr(system_tools, "analyze_screen", _fake_analyze_screen)
    monkeypatch.setattr(system_tools, "computer_use", _fake_computer_use)

    result = await system_tools.operator_mission_control("safari aç ve sonra safaride köpek ara")

    assert result["success"] is False
    assert calls["vision"] == 1
    assert calls["recovery"] == 1
    assert result["lane_statuses"]["browser"]["status"] == "blocked"
    assert result["lane_recovery_attempts"][0]["success"] is False
    assert result["subtasks"][1]["execution_mode"] == "lane_recovery_blocked"


def test_build_operator_goal_profile_includes_app_profile_markers():
    profile = system_tools._build_operator_goal_profile('Safari aç ve "köpek resimleri" ara')

    assert profile["target_app"] == "Safari"
    assert profile["launch_wait_s"] == pytest.approx(0.9)
    assert profile["app_profile"]["category"] == "browser"
    assert "browser" in profile["verification_markers"]
    assert "address bar" in profile["verification_markers"]


def test_operator_execution_class_marks_read_only_as_inspect():
    inspect_profile = system_tools._build_operator_goal_profile("maili kontrol et")
    control_profile = system_tools._build_operator_goal_profile("mail aç")

    assert system_tools._operator_execution_class(inspect_profile) == "inspect"
    assert system_tools._operator_execution_class(control_profile) == "mutating_control"


def test_operator_execution_lane_uses_app_resource_lane():
    inspect_profile = system_tools._build_operator_goal_profile("maili kontrol et")
    browser_profile = system_tools._build_operator_goal_profile("safari aç")

    assert system_tools._operator_execution_lane(inspect_profile) == "mail"
    assert system_tools._operator_execution_lane(browser_profile) == "browser"


def test_build_operator_scheduler_plan_exposes_lane_and_blocking_reason():
    plan = system_tools._build_operator_scheduler_plan(["maili kontrol et", "safari aç"])

    assert plan[0]["execution_class"] == "inspect"
    assert plan[0]["execution_lane"] == "mail"
    assert plan[0]["can_run_parallel"] is True
    assert plan[0]["blocking_reason"] == ""
    assert plan[1]["execution_class"] == "mutating_control"
    assert plan[1]["execution_lane"] == "browser"
    assert plan[1]["can_run_parallel"] is False
    assert plan[1]["blocking_reason"] == "shared_operator_surface"


def test_build_operator_lane_recovery_steps_uses_browser_recipe():
    profile = system_tools._build_operator_goal_profile("safari aç")
    steps = system_tools._build_operator_lane_recovery_steps("browser", profile)

    assert steps[0]["action"] == "open_app"
    assert steps[0]["params"]["app_name"] == "Safari"
    assert any(step["action"] == "key_combo" and step["params"]["combo"] == "cmd+l" for step in steps)


def test_lane_probe_matches_requires_lane_markers():
    profile = system_tools._build_operator_goal_profile("safari aç")
    analysis = {
        "summary": "Safari browser tab ve address bar gorunuyor",
        "ui_map": {"frontmost_app": "Safari"},
    }
    miss = {
        "summary": "hazir gibi",
        "ui_map": {"frontmost_app": "Safari"},
    }

    ok_eval = system_tools._lane_probe_matches("browser", profile, analysis)
    miss_eval = system_tools._lane_probe_matches("browser", profile, miss)

    assert ok_eval["marker_match"] is True
    assert "address bar" in ok_eval["marker_hits"]
    assert miss_eval["marker_match"] is False


def test_goal_to_computer_steps_uses_app_specific_launch_wait():
    steps = system_tools._goal_to_computer_steps("mail aç")

    assert steps[0]["action"] == "open_app"
    assert steps[0]["params"]["app_name"] == "Mail"
    assert steps[1]["action"] == "wait"
    assert steps[1]["params"]["seconds"] == pytest.approx(1.0)


def test_build_goal_repair_steps_uses_profile_wait_budget():
    analysis = {"ui_map": {"frontmost_app": "Finder"}}

    steps = system_tools._build_goal_repair_steps("mail aç", analysis)

    assert steps[0]["action"] == "open_app"
    assert steps[0]["params"]["app_name"] == "Mail"
    assert steps[1]["action"] == "wait"
    assert steps[1]["params"]["seconds"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_run_operator_subtask_serializes_mutating_controls(monkeypatch):
    state = {"current": 0, "max": 0}

    async def _fake_vision_operator_loop(objective, **kwargs):
        _ = (objective, kwargs)
        state["current"] += 1
        state["max"] = max(state["max"], state["current"])
        await asyncio.sleep(0.05)
        state["current"] -= 1
        return {
            "success": True,
            "goal_achieved": True,
            "message": "ok",
            "screenshots": [],
        }

    monkeypatch.setattr(system_tools, "_OPERATOR_MUTATION_LOCK", None)
    monkeypatch.setattr(system_tools, "vision_operator_loop", _fake_vision_operator_loop)

    first, second = await asyncio.gather(
        system_tools._run_operator_subtask("safari aç", pause_ms=0, timeout_s=1.0),
        system_tools._run_operator_subtask("mail aç", pause_ms=0, timeout_s=1.0),
    )

    assert state["max"] == 1
    assert first["execution_class"] == "mutating_control"
    assert second["execution_class"] == "mutating_control"
    assert first["execution_lane"] == "browser"
    assert second["execution_lane"] == "mail"
