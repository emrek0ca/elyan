from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.capabilities.screen_operator.services import ScreenOperatorServices
from core.runtime.hosts import DesktopHost


@dataclass
class _ScreenState:
    summary: str
    frontmost_app: str
    window_title: str
    accessibility: list[dict[str, Any]]
    vision: list[dict[str, Any]]
    ocr_text: str
    ocr_lines: list[dict[str, Any]]


class _StatefulScreenServices:
    def __init__(
        self,
        tmp_path: Path,
        states: list[_ScreenState],
        *,
        click_transitions: dict[tuple[int, int], int] | None = None,
        type_transitions: dict[int, int] | None = None,
    ) -> None:
        self.tmp_path = tmp_path
        self.states = list(states)
        self.index = 0
        self.click_transitions = dict(click_transitions or {})
        self.type_transitions = dict(type_transitions or {})
        self.click_events: list[tuple[int, int]] = []
        self.type_events: list[str] = []

    @property
    def current(self) -> _ScreenState:
        return self.states[self.index]

    def set_index(self, index: int) -> None:
        self.index = int(index)

    async def take_screenshot(self, filename: str | None = None) -> dict[str, Any]:
        path = self.tmp_path / (filename or f"screen_{self.index}.png")
        path.write_bytes(f"screen:{self.index}:{self.current.summary}".encode("utf-8"))
        return {"success": True, "path": str(path), "size_bytes": path.stat().st_size}

    async def capture_region(self, **kwargs) -> dict[str, Any]:
        return await self.take_screenshot(filename=kwargs.get("filename"))

    async def get_window_metadata(self) -> dict[str, Any]:
        return {
            "success": True,
            "frontmost_app": self.current.frontmost_app,
            "window_title": self.current.window_title,
            "bounds": {"x": 0, "y": 0, "width": 1280, "height": 800},
        }

    async def get_accessibility_snapshot(self) -> dict[str, Any]:
        return {
            "success": True,
            "frontmost_app": self.current.frontmost_app,
            "window_title": self.current.window_title,
            "elements": list(self.current.accessibility),
        }

    async def run_ocr(self, image_path: str) -> dict[str, Any]:
        _ = image_path
        return {"success": True, "text": self.current.ocr_text, "lines": list(self.current.ocr_lines)}

    async def run_vision(self, image_path: str, prompt: str) -> dict[str, Any]:
        _ = (image_path, prompt)
        return {"success": True, "summary": self.current.summary, "elements": list(self.current.vision), "provider": "fake"}

    async def mouse_move(self, x: int, y: int) -> dict[str, Any]:
        return {"success": True, "x": x, "y": y}

    async def mouse_click(self, x: int, y: int, button: str = "left", double: bool = False) -> dict[str, Any]:
        _ = (button, double)
        self.click_events.append((x, y))
        next_index = self.click_transitions.get((int(x), int(y)))
        if next_index is not None:
            self.index = int(next_index)
        return {"success": True, "x": x, "y": y}

    async def type_text(self, text: str, press_enter: bool = False) -> dict[str, Any]:
        _ = press_enter
        self.type_events.append(text)
        next_index = self.type_transitions.get(self.index)
        if next_index is not None:
            self.index = int(next_index)
        return {"success": True, "typed_chars": len(text), "press_enter": bool(press_enter)}

    async def press_key(self, key: str, modifiers: list[str] | None = None) -> dict[str, Any]:
        return {"success": True, "key": key, "modifiers": modifiers or []}

    async def key_combo(self, combo: str) -> dict[str, Any]:
        return {"success": True, "combo": combo}

    async def sleep(self, seconds: float) -> None:
        _ = seconds
        return None

    def build(self) -> ScreenOperatorServices:
        return ScreenOperatorServices(
            take_screenshot=self.take_screenshot,
            capture_region=self.capture_region,
            get_window_metadata=self.get_window_metadata,
            get_accessibility_snapshot=self.get_accessibility_snapshot,
            run_ocr=self.run_ocr,
            run_vision=self.run_vision,
            mouse_move=self.mouse_move,
            mouse_click=self.mouse_click,
            type_text=self.type_text,
            press_key=self.press_key,
            key_combo=self.key_combo,
            sleep=self.sleep,
        )


@pytest.mark.asyncio
async def test_desktop_host_reuses_target_cache_for_follow_up_click(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    services = _StatefulScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Safari acik. Search butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Start",
                accessibility=[{"label": "Search", "role": "button", "x": 200, "y": 100, "width": 80, "height": 20}],
                vision=[],
                ocr_text="Search",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Safari acik. Hedef buton mevcut degil ama ayni pencere acik.",
                frontmost_app="Safari",
                window_title="Start",
                accessibility=[],
                vision=[],
                ocr_text="",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search paneli acildi.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[{"label": "Search field", "role": "text_field", "x": 260, "y": 150, "width": 160, "height": 30}],
                vision=[],
                ocr_text="Search field",
                ocr_lines=[],
            ),
        ],
        click_transitions={(240, 110): 2},
    )

    inspect_result = await host.run_screen_operator(instruction="ekrana bak", mode="inspect", services=services.build())
    services.set_index(1)
    click_result = await host.run_screen_operator(instruction="Search butonuna tikla", mode="control", services=services.build())

    assert inspect_result["success"] is True
    assert click_result["success"] is True
    assert click_result["action_logs"][0]["planned_action"]["target"]["source"] == "cache"
    state = await host.get_live_state()
    assert state["frontmost_app"] == "Safari"
    assert state["active_window"]["title"] == "Search"
    assert "search" in state["target_cache"]


@pytest.mark.asyncio
async def test_desktop_host_persists_ui_state_across_click_then_type(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    services = _StatefulScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Safari acik. Search butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Start",
                accessibility=[{"label": "Search", "role": "button", "x": 200, "y": 100, "width": 80, "height": 20}],
                vision=[],
                ocr_text="Search",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search field odakta.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[{"label": "Search field", "role": "text_field", "x": 260, "y": 150, "width": 160, "height": 30}],
                vision=[],
                ocr_text="",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search field icinde kittens yaziyor.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[{"label": "Search field", "role": "text_field", "x": 260, "y": 150, "width": 160, "height": 30}],
                vision=[],
                ocr_text="kittens",
                ocr_lines=[{"text": "kittens", "x": 270, "y": 158, "width": 60, "height": 18, "confidence": 0.95}],
            ),
        ],
        click_transitions={(240, 110): 1},
        type_transitions={1: 2},
    )

    click_result = await host.run_screen_operator(instruction="Search butonuna tikla", mode="control", services=services.build())
    type_result = await host.run_screen_operator(instruction='Search field icine "kittens" yaz', mode="control", services=services.build())

    assert click_result["success"] is True
    assert type_result["success"] is True
    assert services.type_events == ["kittens"]
    state = await host.get_live_state()
    assert state["frontmost_app"] == "Safari"
    assert state["active_window"]["title"] == "Search"
    assert state["last_ui_state"]["frontmost_app"] == "Safari"
    assert state["current_task_state"]["last_ui_state"]["frontmost_app"] == "Safari"
    assert state["recent_action_logs"]
    assert state["verifier_outcomes"]
    assert state["last_screenshot"]


@pytest.mark.asyncio
async def test_desktop_host_state_can_be_inspected_and_cleared_safely(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    services = _StatefulScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Cursor acik.",
                frontmost_app="Cursor",
                window_title="main.py",
                accessibility=[{"label": "Run", "role": "button", "x": 100, "y": 100, "width": 50, "height": 20}],
                vision=[],
                ocr_text="main.py",
                ocr_lines=[],
            )
        ],
    )

    await host.run_screen_operator(instruction="ekrana bak", mode="inspect", services=services.build())
    live_state = await host.get_live_state()
    cleared_state = await host.clear_live_state()

    assert live_state["frontmost_app"] == "Cursor"
    assert live_state["last_ui_state"]["frontmost_app"] == "Cursor"
    assert cleared_state["frontmost_app"] == ""
    assert cleared_state["active_window"] == {}
    assert cleared_state["last_screenshot"] == ""
    assert cleared_state["last_ui_state"] == {}
    assert cleared_state["current_task_state"] == {}
    assert cleared_state["target_cache"] == {}
    assert cleared_state["recent_action_logs"] == []
    assert cleared_state["verifier_outcomes"] == []


@pytest.mark.asyncio
async def test_desktop_host_prefers_current_window_target_over_stale_cached_label(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    services = _StatefulScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Ilk Open butonu gorunuyor.",
                frontmost_app="Finder",
                window_title="Open A",
                accessibility=[{"label": "Open", "role": "button", "x": 100, "y": 100, "width": 80, "height": 20}],
                vision=[],
                ocr_text="Open",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Open A tamamlandi.",
                frontmost_app="Finder",
                window_title="Open A Done",
                accessibility=[],
                vision=[],
                ocr_text="Done",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Yeni pencerede baska bir Open butonu gorunuyor.",
                frontmost_app="Finder",
                window_title="Open B",
                accessibility=[{"label": "Open", "role": "button", "x": 400, "y": 100, "width": 80, "height": 20}],
                vision=[],
                ocr_text="Open",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Open B tamamlandi.",
                frontmost_app="Finder",
                window_title="Open B Done",
                accessibility=[],
                vision=[],
                ocr_text="Done",
                ocr_lines=[],
            ),
        ],
        click_transitions={(140, 110): 1, (440, 110): 3},
    )

    first = await host.run_screen_operator(instruction="Open butonuna tikla", mode="control", services=services.build())
    services.set_index(2)
    second = await host.run_screen_operator(instruction="Open butonuna tikla", mode="control", services=services.build())

    assert first["success"] is True
    assert second["success"] is True
    assert services.click_events[-1] == (440, 110)
    assert second["action_logs"][0]["planned_action"]["target"]["source"] == "accessibility"
    state = await host.get_live_state()
    assert state["active_window"]["title"] == "Open B Done"
