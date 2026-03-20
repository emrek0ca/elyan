from __future__ import annotations

import pytest

from core.realtime_actuator import RealTimeActuator, ScreenObserver, ScreenpipeClient, VisionVerifier


class _FakeScreenServices:
    def __init__(self, tmp_path):
        self.tmp_path = tmp_path

    async def take_screenshot(self, filename=None):
        path = self.tmp_path / (filename or "screen.png")
        path.write_text("frame", encoding="utf-8")
        return {"success": True, "path": str(path)}

    async def capture_region(self, x, y, width, height, filename=None):
        _ = (x, y, width, height)
        return await self.take_screenshot(filename=filename)

    async def get_window_metadata(self):
        return {"success": True, "window_title": "Desktop", "frontmost_app": "Finder"}

    async def get_accessibility_snapshot(self):
        return {
            "success": True,
            "elements": [
                {"label": "Save", "role": "button", "x": 10, "y": 20, "width": 80, "height": 24}
            ],
        }

    async def run_ocr(self, image_path):
        _ = image_path
        return {"success": True, "text": "Save"}

    async def run_vision(self, image_path, prompt):
        _ = (image_path, prompt)
        return {"success": True, "summary": "Save button visible", "elements": [{"label": "Save", "role": "button", "x": 10, "y": 20, "width": 80, "height": 24}]}

    async def mouse_move(self, x, y):
        return {"success": True, "x": x, "y": y}

    async def mouse_click(self, x, y, button="left", double=False):
        return {"success": True, "x": x, "y": y, "button": button, "double": double}

    async def type_text(self, text, press_enter=False):
        return {"success": True, "text": text, "press_enter": press_enter}

    async def press_key(self, key, modifiers=None):
        return {"success": True, "key": key, "modifiers": list(modifiers or [])}

    async def key_combo(self, combo):
        return {"success": True, "combo": combo}

    async def sleep(self, seconds):
        _ = seconds
        return None


def test_realtime_actuator_inline_action_and_observation(monkeypatch, tmp_path):
    monkeypatch.setattr("core.realtime_actuator.runtime._module_available", lambda name: False)
    services = _FakeScreenServices(tmp_path)
    actuator = RealTimeActuator(services=services, process_mode=False, fps=30, max_frames=3, max_actions=3)

    submit_result = actuator.submit({"kind": "click", "x": 10, "y": 20})
    observation = actuator.observe_once("Save button visible")
    snapshot = actuator.snapshot()

    assert submit_result["status"] == "success"
    assert submit_result["result"]["action"] == "click"
    assert submit_result["result"]["verified"] is True
    assert submit_result["result"]["verification"]["ok"] is True
    assert observation["success"] is True
    assert snapshot["last_action"]["action"]["kind"] == "click"
    assert snapshot["last_observation"]["summary"]
    assert len(snapshot["frames"]) >= 1
    assert actuator.get_status()["transport_mode"] == "inline"
    assert actuator.get_status()["backend_profile"]["screen_backend"] in {"services", "screenpipe"}
    assert "platform_backend_candidate" in actuator.get_status()["backend_profile"]


def test_screenpipe_client_uses_service_probe_and_cache(monkeypatch):
    monkeypatch.setattr("core.realtime_actuator.runtime._module_available", lambda name: False)
    calls = []

    class _Resp:
        status_code = 200

    def fake_get(url, timeout=None):
        calls.append((url, timeout))
        return _Resp()

    monkeypatch.setattr("core.realtime_actuator.runtime.requests.get", fake_get)
    client = ScreenpipeClient(base_url="http://localhost:3030", timeout_s=2.0)

    assert client.available() is True
    assert client.available() is True
    assert len(calls) == 1
    assert calls[0][0].endswith("/health")


@pytest.mark.asyncio
async def test_screen_observer_skips_vision_when_accessibility_is_enough(monkeypatch, tmp_path):
    monkeypatch.setattr("core.realtime_actuator.runtime._module_available", lambda name: False)
    services = _FakeScreenServices(tmp_path)
    observer = ScreenObserver(services=services)
    vision_calls = {"count": 0}

    original = services.run_vision

    async def fake_vision(image_path, prompt):
        vision_calls["count"] += 1
        return await original(image_path, prompt)

    services.run_vision = fake_vision
    result = await observer.observe_once("Save button visible")

    assert result["success"] is True
    assert result["vision_used"] is False
    assert vision_calls["count"] == 0


@pytest.mark.asyncio
async def test_screen_observer_uses_vision_for_explicit_visual_goal(monkeypatch, tmp_path):
    monkeypatch.setattr("core.realtime_actuator.runtime._module_available", lambda name: False)
    services = _FakeScreenServices(tmp_path)
    observer = ScreenObserver(services=services)
    vision_calls = {"count": 0}

    original = services.run_vision

    async def fake_vision(image_path, prompt):
        vision_calls["count"] += 1
        return await original(image_path, prompt)

    services.run_vision = fake_vision
    result = await observer.observe_once("Ekranı görsel olarak analiz et")

    assert result["success"] is True
    assert result["vision_used"] is True
    assert vision_calls["count"] == 1


@pytest.mark.asyncio
async def test_vision_verifier_uses_visual_fallback_when_needed(monkeypatch, tmp_path):
    monkeypatch.setattr("core.realtime_actuator.runtime._module_available", lambda name: False)
    services = _FakeScreenServices(tmp_path)
    verifier = VisionVerifier(services=services)
    vision_calls = {"count": 0}

    original = services.run_vision

    async def fake_vision(image_path, prompt):
        vision_calls["count"] += 1
        return await original(image_path, prompt)

    services.run_vision = fake_vision
    before_path = tmp_path / "before.png"
    after_path = tmp_path / "after.png"
    before_path.write_text("frame", encoding="utf-8")
    after_path.write_text("frame", encoding="utf-8")

    before = {
        "screenshot": {"path": str(before_path)},
        "accessibility": {"elements": []},
        "ocr": {"text": ""},
        "vision": {"summary": ""},
        "summary": "",
    }
    after = {
        "screenshot": {"path": str(after_path)},
        "accessibility": {"elements": []},
        "ocr": {"text": ""},
        "vision": {"summary": ""},
        "summary": "",
    }
    action = {"kind": "click", "x": 10, "y": 20}

    result = await verifier.verify_transition(before, after, action, goal="Ekranı görsel olarak analiz et")

    assert result["vision_attempted"] is True
    assert vision_calls["count"] == 1
