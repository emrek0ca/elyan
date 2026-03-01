from pathlib import Path

import pytest

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
    assert result["size_bytes"] > 0
    assert Path(result["path"]).exists()


@pytest.mark.asyncio
async def test_take_screenshot_returns_error_on_nonzero_exit(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    async def _fake_exec(*_args, **_kwargs):
        return _Proc(returncode=1, stderr=b"permission denied")

    monkeypatch.setattr(system_tools.asyncio, "create_subprocess_exec", _fake_exec)
    result = await system_tools.take_screenshot("proof.png")
    assert result["success"] is False
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
