from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.capabilities.screen_operator.runtime import run_screen_operator
from core.capabilities.screen_operator.services import ScreenOperatorServices


@dataclass
class _ScreenState:
    summary: str
    frontmost_app: str
    window_title: str
    accessibility: list[dict[str, Any]]
    vision: list[dict[str, Any]]
    ocr_text: str
    ocr_lines: list[dict[str, Any]]


class _FakeScreenServices:
    def __init__(
        self,
        tmp_path: Path,
        states: list[_ScreenState],
        *,
        click_map: dict[str, int] | None = None,
        click_transitions: dict[tuple[int, int], int] | None = None,
        type_target_index: int | None = None,
    ):
        self.tmp_path = tmp_path
        self.states = list(states)
        self.index = 0
        self.click_map = dict(click_map or {})
        self.click_transitions = dict(click_transitions or {})
        self.type_target_index = type_target_index
        self.click_events: list[tuple[int, int]] = []
        self.type_events: list[str] = []

    @property
    def current(self) -> _ScreenState:
        return self.states[self.index]

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
            self.index = next_index
            return {"success": True, "x": x, "y": y}
        for label, next_index in self.click_map.items():
            matched = False
            for item in self.current.accessibility + self.current.vision:
                if str(item.get("label") or "") != label:
                    continue
                item_x = int(item.get("x") or 0)
                item_y = int(item.get("y") or 0)
                item_w = int(item.get("width") or 1)
                item_h = int(item.get("height") or 1)
                if item_x <= x <= item_x + item_w and item_y <= y <= item_y + item_h:
                    self.index = next_index
                    matched = True
                    break
            if matched:
                break
        return {"success": True, "x": x, "y": y}

    async def type_text(self, text: str, press_enter: bool = False) -> dict[str, Any]:
        _ = press_enter
        self.type_events.append(text)
        if self.type_target_index is not None:
            self.index = int(self.type_target_index)
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
async def test_screen_operator_inspect_returns_ui_state_and_artifacts(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Cursor acik ve editor gorunuyor.",
                frontmost_app="Cursor",
                window_title="main.py",
                accessibility=[{"label": "Run", "role": "button", "x": 100, "y": 100, "width": 50, "height": 20}],
                vision=[],
                ocr_text="main.py",
                ocr_lines=[{"text": "main.py", "x": 10, "y": 10, "width": 40, "height": 10, "confidence": 0.9}],
            )
        ],
    )

    result = await run_screen_operator(instruction="ekrana bak", mode="inspect", services=fake.build())

    assert result["success"] is True
    assert result["ui_state"]["frontmost_app"] == "Cursor"
    assert any(str(item["path"]).endswith("ui_state.json") for item in result["artifacts"])
    assert any(str(item["path"]).endswith("screen_summary.txt") for item in result["artifacts"])
    assert result["screenshots"]


@pytest.mark.asyncio
async def test_screen_operator_artifacts_use_resolved_data_dir(tmp_path: Path, monkeypatch):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Cursor acik ve editor gorunuyor.",
                frontmost_app="Cursor",
                window_title="main.py",
                accessibility=[],
                vision=[],
                ocr_text="main.py",
                ocr_lines=[],
            )
        ],
    )
    data_root = (tmp_path / "elyan_data").resolve()
    monkeypatch.setattr(
        "core.capabilities.screen_operator.runtime.resolve_elyan_data_dir",
        lambda: data_root,
    )

    result = await run_screen_operator(instruction="ekrana bak", mode="inspect", services=fake.build())
    assert result["success"] is True
    base = (data_root / "screen_operator").resolve()
    assert result["artifacts"]
    for item in result["artifacts"]:
        p = Path(str(item.get("path") or "")).resolve()
        assert str(p).startswith(str(base))


@pytest.mark.asyncio
async def test_screen_operator_clicks_target_and_verifies_visual_change(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Safari acik. Search butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Start",
                accessibility=[{"label": "Search", "role": "button", "x": 220, "y": 180, "width": 80, "height": 26}],
                vision=[],
                ocr_text="Search",
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
        click_map={"Search": 1},
    )

    result = await run_screen_operator(instruction="Search butonuna tikla", mode="control", services=fake.build())

    assert result["success"] is True
    assert result["goal_achieved"] is True
    assert fake.click_events
    assert result["action_logs"][0]["verification"]["ok"] is True
    assert result["ui_state"]["active_window"]["title"] == "Search"


@pytest.mark.asyncio
async def test_screen_operator_falls_back_to_vision_target_when_accessibility_missing_coords(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Safari acik. Continue butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Start",
                accessibility=[{"label": "Continue", "role": "button"}],
                vision=[{"label": "Continue", "role": "button", "x": 400, "y": 300, "width": 120, "height": 30, "confidence": 0.7}],
                ocr_text="Continue",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Continue sonrasi ekran acildi.",
                frontmost_app="Safari",
                window_title="Next",
                accessibility=[],
                vision=[],
                ocr_text="Welcome",
                ocr_lines=[],
            ),
        ],
        click_map={"Continue": 1},
    )

    result = await run_screen_operator(instruction="Continue butonuna tikla", mode="control", services=fake.build())

    assert result["success"] is True
    planned = result["action_logs"][0]["planned_action"]
    assert planned["target"]["source"] == "vision"
    assert result["action_logs"][0]["verification"]["ok"] is True


@pytest.mark.asyncio
async def test_screen_operator_types_and_verifies_text(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
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
                ocr_lines=[{"text": "kittens", "x": 265, "y": 158, "width": 60, "height": 20, "confidence": 0.95}],
            ),
        ],
        type_target_index=1,
    )

    result = await run_screen_operator(instruction='Search field icine "kittens" yaz', mode="control", services=fake.build())

    assert result["success"] is True
    assert fake.type_events == ["kittens"]
    assert result["action_logs"][-1]["verification"]["ok"] is True
    assert "kittens" in str(result["summary"]).lower()


@pytest.mark.asyncio
async def test_screen_operator_bounds_retry_and_fails_safely_after_no_visual_change(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Dialog acik. Confirm butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Dialog",
                accessibility=[{"label": "Confirm", "role": "button", "x": 100, "y": 100, "width": 40, "height": 20}],
                vision=[{"label": "Confirm", "role": "button", "x": 200, "y": 200, "width": 40, "height": 20, "confidence": 0.6}],
                ocr_text="Confirm",
                ocr_lines=[],
            )
        ],
    )

    result = await run_screen_operator(instruction="Confirm butonuna tikla", mode="control", services=fake.build(), max_retries_per_action=1)

    assert result["success"] is False
    assert result["error_code"] == "NO_VISUAL_CHANGE"
    assert len(result["action_logs"]) == 2


@pytest.mark.asyncio
async def test_screen_operator_prefers_search_button_over_search_field_for_click(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Safari acik. Search field ve Search button gorunuyor.",
                frontmost_app="Safari",
                window_title="Start",
                accessibility=[
                    {"label": "Search", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                ],
                vision=[],
                ocr_text="Search",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search button tiklandi ve sonuc ekranina gecildi.",
                frontmost_app="Safari",
                window_title="Results",
                accessibility=[],
                vision=[],
                ocr_text="Results",
                ocr_lines=[],
            ),
        ],
        click_transitions={(360, 106): 1},
    )

    result = await run_screen_operator(instruction="Search butonuna tikla", mode="control", services=fake.build())

    assert result["success"] is True
    assert fake.click_events[0] == (360, 106)
    trace = result["action_logs"][0]["planned_action"]["decision_trace"]
    assert trace["chosen"]["role"] == "button"
    assert trace["chosen"]["label"].lower() == "search"


@pytest.mark.asyncio
async def test_screen_operator_prefers_text_field_for_typing_and_emits_decision_trace(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Search field ve Search button ayni ekranda.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                    {"label": "Search", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                ],
                vision=[],
                ocr_text="",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search field odaga alindi.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                    {"label": "Search", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                ],
                vision=[],
                ocr_text="",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search field icinde kittens yaziyor.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                    {"label": "Search", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                ],
                vision=[],
                ocr_text="kittens",
                ocr_lines=[{"text": "kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}],
            ),
        ],
        click_transitions={(190, 105): 1},
        type_target_index=2,
    )

    result = await run_screen_operator(instruction='Search field icine "kittens" yaz', mode="control", services=fake.build())

    assert result["success"] is True
    assert fake.click_events[0] == (190, 105)
    assert fake.type_events == ["kittens"]
    focus_action = result["action_logs"][0]["planned_action"]
    type_action = result["action_logs"][-1]["planned_action"]
    assert focus_action["focus_before_type"] is True
    assert focus_action["target"]["role"] == "text_field"
    assert type_action["decision_trace"]["chosen"]["role"] == "text_field"


@pytest.mark.asyncio
async def test_screen_operator_prefers_submit_button_over_submit_field_and_writes_decision_trace_artifact(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Submit field ve Submit butonu ayni ekranda.",
                frontmost_app="Safari",
                window_title="Checkout",
                accessibility=[
                    {"label": "Submit", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                    {"label": "Submit", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                ],
                vision=[],
                ocr_text="Submit",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Form gonderildi.",
                frontmost_app="Safari",
                window_title="Done",
                accessibility=[],
                vision=[],
                ocr_text="Done",
                ocr_lines=[],
            ),
        ],
        click_transitions={(360, 106): 1},
    )

    result = await run_screen_operator(instruction="Submit butonuna tikla", mode="control", services=fake.build())

    assert result["success"] is True
    assert fake.click_events[0] == (360, 106)
    trace = result["action_logs"][0]["planned_action"]["decision_trace"]
    assert trace["chosen"]["role"] == "button"
    assert any(item["role"] == "text_field" for item in trace["rejected"])
    decision_artifact = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("target_decisions.json"))
    payload = json.loads(Path(decision_artifact).read_text(encoding="utf-8"))
    assert payload[0]["chosen"]["role"] == "button"


@pytest.mark.asyncio
async def test_screen_operator_prefers_recently_verified_continue_target_when_duplicates_exist(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Iki ayri Continue butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Checkout",
                accessibility=[
                    {"label": "Continue", "role": "button", "x": 400, "y": 180, "width": 120, "height": 30},
                ],
                vision=[],
                ocr_text="Continue",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Dogru continue adimi acildi.",
                frontmost_app="Safari",
                window_title="Shipping",
                accessibility=[],
                vision=[],
                ocr_text="Shipping",
                ocr_lines=[],
            ),
        ],
        click_transitions={(180, 110): 1},
    )

    task_state = {
        "last_target_cache": {
            "continue": {
                "label": "Continue",
                "role": "button",
                "x": 120,
                "y": 96,
                "width": 120,
                "height": 28,
                "source": "cache",
                "frontmost_app": "Safari",
                "window_title": "Checkout",
                "confidence": 0.35,
                "_cache_meta": {
                    "last_verified_success": True,
                    "verified_success_count": 2,
                    "last_action_kind": "click",
                    "last_seen_at": 4102444800.0,
                    "last_verified_success_at": 4102444800.0,
                    "frontmost_app": "Safari",
                    "window_title": "Checkout",
                },
            }
        }
    }

    result = await run_screen_operator(
        instruction="Continue butonuna tikla",
        mode="control",
        services=fake.build(),
        task_state=task_state,
    )

    assert result["success"] is True
    assert fake.click_events[0] == (180, 110)
    trace = result["action_logs"][0]["planned_action"]["decision_trace"]
    assert trace["chosen"]["source"] == "cache"


@pytest.mark.asyncio
async def test_screen_operator_prefers_prior_ui_state_over_stale_cache_when_context_conflicts(tmp_path: Path):
    fake = _FakeScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Checkout penceresi acik ancak hedefler yeniden tespit edilemedi.",
                frontmost_app="Safari",
                window_title="Checkout",
                accessibility=[],
                vision=[],
                ocr_text="Checkout",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Dogru continue adimi acildi.",
                frontmost_app="Safari",
                window_title="Shipping",
                accessibility=[],
                vision=[],
                ocr_text="Shipping",
                ocr_lines=[],
            ),
        ],
        click_transitions={(480, 194): 1},
    )

    task_state = {
        "last_target_cache": {
            "continue": {
                "label": "Continue",
                "role": "button",
                "x": 120,
                "y": 96,
                "width": 120,
                "height": 28,
                "source": "cache",
                "frontmost_app": "Safari",
                "window_title": "Landing",
                "confidence": 0.35,
                "_cache_meta": {
                    "last_verified_success": True,
                    "verified_success_count": 3,
                    "last_action_kind": "click",
                    "last_seen_at": 4102444800.0,
                    "last_verified_success_at": 4102444800.0,
                    "frontmost_app": "Safari",
                    "window_title": "Landing",
                },
            }
        },
        "last_ui_state": {
            "frontmost_app": "Safari",
            "active_window": {"title": "Checkout"},
            "elements": [
                {
                    "label": "Continue",
                    "role": "button",
                    "x": 420,
                    "y": 180,
                    "width": 120,
                    "height": 28,
                    "frontmost_app": "Safari",
                    "window_title": "Checkout",
                }
            ],
        },
    }

    result = await run_screen_operator(
        instruction="Continue butonuna tikla",
        mode="control",
        services=fake.build(),
        task_state=task_state,
    )

    assert result["success"] is True
    assert fake.click_events[0] == (480, 194)
    trace = result["action_logs"][0]["planned_action"]["decision_trace"]
    assert trace["chosen"]["source"] == "prior_ui_state"
    assert trace["chosen"]["window_title"].lower() == "checkout"
