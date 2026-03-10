from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.capabilities.browser.services import BrowserRuntimeServices
from core.capabilities.screen_operator.services import ScreenOperatorServices
from core.runtime import DesktopHost
from core.runtime.scenarios import OperatorScenarioRunner


@dataclass
class _ScreenState:
    summary: str
    frontmost_app: str
    window_title: str
    accessibility: list[dict[str, Any]]
    vision: list[dict[str, Any]]
    ocr_text: str
    ocr_lines: list[dict[str, Any]]


class _ScenarioScreenServices:
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


@dataclass
class _PageState:
    url: str
    title: str
    visible_text: str
    html: str
    selectors: dict[str, dict[str, Any]]
    links: list[dict[str, Any]]
    table: dict[str, Any]


class _ScenarioBrowserServices:
    def __init__(
        self,
        tmp_path: Path,
        states: list[_PageState],
        *,
        url_map: dict[str, int] | None = None,
        click_transitions: dict[tuple[int, str], int] | None = None,
        submit_transitions: dict[tuple[int, str], int] | None = None,
        dom_available: bool = True,
    ) -> None:
        self.tmp_path = tmp_path
        self.states = list(states)
        self.index = 0
        self.url_map = dict(url_map or {})
        self.click_transitions = dict(click_transitions or {})
        self.submit_transitions = dict(submit_transitions or {})
        self.dom_available = bool(dom_available)
        self.values: dict[str, str] = {}
        self.scroll_pos = {"x": 0, "y": 0}

    @property
    def current(self) -> _PageState:
        return self.states[self.index]

    def _state_payload(self) -> dict[str, Any]:
        return {
            "success": True,
            "dom_available": self.dom_available,
            "url": self.current.url,
            "title": self.current.title,
            "visible_text": self.current.visible_text,
            "dom_hash": hashlib.sha256(self.current.html.encode("utf-8")).hexdigest(),
            "scroll": dict(self.scroll_pos),
            "session_id": "fake-browser",
            "headless": True,
        }

    async def ensure_session(self, headless: bool = True) -> dict[str, Any]:
        _ = headless
        if not self.dom_available:
            return {"success": False, "error": "dom unavailable", "error_code": "DOM_UNAVAILABLE", "dom_available": False}
        return {"success": True, "dom_available": True, "session_id": "fake-browser", "headless": True}

    async def goto(self, url: str, timeout_ms: int = 10000) -> dict[str, Any]:
        _ = timeout_ms
        if url in self.url_map:
            self.index = int(self.url_map[url])
        return {"success": True, "url": self.current.url, "title": self.current.title, "status_code": 200, "dom_available": True}

    async def click(self, selector: str, timeout_ms: int = 5000) -> dict[str, Any]:
        _ = timeout_ms
        if selector not in self.current.selectors:
            return {"success": False, "error": "selector missing", "error_code": "DOM_TARGET_NOT_FOUND", "dom_available": True}
        transition = self.click_transitions.get((self.index, selector))
        if transition is not None:
            self.index = int(transition)
        return {"success": True, "selector": selector, "dom_available": True}

    async def fill(self, selector: str, text: str, timeout_ms: int = 5000) -> dict[str, Any]:
        _ = timeout_ms
        if selector not in self.current.selectors:
            return {"success": False, "error": "selector missing", "error_code": "DOM_TARGET_NOT_FOUND", "dom_available": True}
        self.values[selector] = str(text or "")
        return {"success": True, "selector": selector, "text": str(text or ""), "dom_available": True}

    async def press(self, selector: str | None = None, key: str = "Enter", timeout_ms: int = 5000) -> dict[str, Any]:
        _ = timeout_ms
        target = str(selector or "").strip()
        transition = self.submit_transitions.get((self.index, target))
        if transition is not None:
            self.index = int(transition)
        return {"success": True, "selector": target, "key": key, "dom_available": True}

    async def get_text(self, selector: str | None = None) -> dict[str, Any]:
        target = str(selector or "").strip()
        if target:
            text = str((self.current.selectors.get(target) or {}).get("text") or "")
        else:
            text = self.current.visible_text
        return {"success": True, "selector": target, "text": text, "dom_available": True}

    async def get_value(self, selector: str) -> dict[str, Any]:
        return {"success": True, "selector": selector, "value": str(self.values.get(selector, "")), "dom_available": True}

    async def get_state(self) -> dict[str, Any]:
        return self._state_payload()

    async def get_dom_snapshot(self) -> dict[str, Any]:
        return {**self._state_payload(), "html": self.current.html}

    async def screenshot(self, path: str | None = None, selector: str | None = None) -> dict[str, Any]:
        _ = selector
        target = Path(path or (self.tmp_path / f"browser_{self.index}.png"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(f"browser:{self.index}:{self.current.title}".encode("utf-8"))
        return {"success": True, "path": str(target), "dom_available": True}

    async def wait_for(self, selector: str, timeout_ms: int = 10000, state: str = "visible") -> dict[str, Any]:
        _ = (timeout_ms, state)
        return {"success": selector in self.current.selectors, "found": selector in self.current.selectors, "selector": selector, "dom_available": True}

    async def scroll(self, direction: str = "down", amount: int = 500) -> dict[str, Any]:
        before = dict(self.scroll_pos)
        if direction == "down":
            self.scroll_pos["y"] += int(amount)
        return {"success": True, "before": before, "after": dict(self.scroll_pos), "dom_available": True}

    async def query_links(self, pattern: str | None = None) -> dict[str, Any]:
        links = list(self.current.links)
        if pattern:
            links = [item for item in links if pattern in str(item.get("href") or "")]
        return {"success": True, "links": links, "count": len(links), "dom_available": True}

    async def query_table(self, selector: str = "table") -> dict[str, Any]:
        _ = selector
        return {
            "success": True,
            "headers": list((self.current.table or {}).get("headers") or []),
            "rows": list((self.current.table or {}).get("rows") or []),
            "dom_available": True,
        }

    async def close(self) -> dict[str, Any]:
        return {"success": True}

    def build(self) -> BrowserRuntimeServices:
        return BrowserRuntimeServices(
            ensure_session=self.ensure_session,
            goto=self.goto,
            click=self.click,
            fill=self.fill,
            press=self.press,
            get_text=self.get_text,
            get_value=self.get_value,
            get_state=self.get_state,
            get_dom_snapshot=self.get_dom_snapshot,
            screenshot=self.screenshot,
            wait_for=self.wait_for,
            scroll=self.scroll,
            query_links=self.query_links,
            query_table=self.query_table,
            close=self.close,
        )


@pytest.mark.asyncio
async def test_operator_scenario_runs_open_app_type_and_click_sequence(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _ScenarioScreenServices(
        tmp_path,
        [
            _ScreenState(summary="Masaustu gorunuyor.", frontmost_app="Finder", window_title="Desktop", accessibility=[], vision=[], ocr_text="Desktop", ocr_lines=[]),
            _ScreenState(
                summary="Safari arama penceresi acildi.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[
                    {"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                ],
                vision=[],
                ocr_text="Search",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Search field icinde kittens yaziyor.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[
                    {"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                ],
                vision=[],
                ocr_text="kittens",
                ocr_lines=[{"text": "kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}],
            ),
            _ScreenState(summary="Results for kittens gorunuyor.", frontmost_app="Safari", window_title="Results", accessibility=[], vision=[], ocr_text="Results for kittens", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 3},
        type_transitions={1: 2},
    )

    async def _system_runner(tool_name: str, params: dict[str, Any]) -> dict[str, Any]:
        if tool_name == "open_app" and str(params.get("app_name") or "") == "Safari":
            screen.set_index(1)
            return {"success": True, "status": "success", "message": "Safari opened."}
        return {"success": False, "status": "failed", "error": "unsupported", "error_code": "UNSUPPORTED"}

    runner = OperatorScenarioRunner(desktop_host=host, system_tool_runner=_system_runner, artifacts_root=tmp_path / "scenario_artifacts")
    result = await runner.run(
        name="desktop-sequence",
        clear_live_state=True,
        screen_services=screen.build(),
        steps=[
            {"kind": "system", "name": "open_safari", "tool": "open_app", "params": {"app_name": "Safari"}, "verify": {"frontmost_app": "Safari", "window_title_contains": "Search"}},
            {"kind": "screen", "name": "type_query", "instruction": 'Search field icine "kittens" yaz', "verify": {"text_contains": "kittens", "window_title_contains": "Search"}},
            {"kind": "screen", "name": "submit_search", "instruction": "Search butonuna tikla", "verify": {"text_contains": "Results for kittens", "window_title_contains": "Results"}},
        ],
    )

    assert result["success"] is True
    assert len(result["steps"]) == 3
    assert screen.type_events == ["kittens"]
    assert screen.click_events[-1] == (360, 106)
    task_state_path = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("task_state.json"))
    verification_path = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("verification.json"))
    summary_path = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("scenario_summary.md"))
    target_path = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("target_decisions.json"))
    assert json.loads(Path(task_state_path).read_text(encoding="utf-8"))["desktop_live_state"]["frontmost_app"] == "Safari"
    assert json.loads(Path(verification_path).read_text(encoding="utf-8"))["status"] == "success"
    assert "open_safari" in Path(summary_path).read_text(encoding="utf-8")
    assert json.loads(Path(target_path).read_text(encoding="utf-8"))
    assert result["screenshots"]


@pytest.mark.asyncio
async def test_operator_scenario_runs_browser_open_fill_submit_sequence(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    browser = _ScenarioBrowserServices(
        tmp_path,
        [
            _PageState(url="", title="", visible_text="", html="<html></html>", selectors={}, links=[], table={}),
            _PageState(
                url="https://search.local",
                title="Search",
                visible_text="Search",
                html="<html><body><input id='q'/></body></html>",
                selectors={"#q": {"text": ""}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://search.local?q=kittens",
                title="Results",
                visible_text="Results for kittens",
                html="<html><body>Results for kittens</body></html>",
                selectors={"#results": {"text": "Results for kittens"}},
                links=[],
                table={},
            ),
        ],
        url_map={"https://search.local": 1},
        submit_transitions={(1, "#q"): 2},
    )

    runner = OperatorScenarioRunner(desktop_host=host, artifacts_root=tmp_path / "scenario_artifacts")
    result = await runner.run(
        name="browser-sequence",
        clear_live_state=True,
        browser_services=browser.build(),
        steps=[
            {"kind": "browser", "name": "open_page", "action": "open", "url": "search.local", "expected_url_contains": "search.local", "expected_title_contains": "Search", "verify": {"url_contains": "search.local", "title_contains": "Search"}},
            {"kind": "browser", "name": "fill_query", "action": "type", "selector": "#q", "text": "kittens", "verify": {"text_contains": "kittens"}},
            {"kind": "browser", "name": "submit_query", "action": "submit", "selector": "#q", "expected_text": "Results for kittens", "verify": {"url_contains": "kittens", "title_contains": "Results", "text_contains": "Results for kittens"}},
        ],
    )

    assert result["success"] is True
    assert len(result["steps"]) == 3
    assert browser.values["#q"] == "kittens"
    browser_state_path = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("browser_state_snapshots.json"))
    browser_states = json.loads(Path(browser_state_path).read_text(encoding="utf-8"))
    assert browser_states[-1]["browser_state"]["url"].endswith("?q=kittens")
    assert result["screenshots"]


@pytest.mark.asyncio
async def test_operator_scenario_runs_mixed_browser_and_screen_fallback_sequence(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    browser = _ScenarioBrowserServices(
        tmp_path,
        [
            _PageState(
                url="https://upload.local",
                title="Upload",
                visible_text="Upload file",
                html="<html><body><button id='upload'>Upload</button></body></html>",
                selectors={"#upload": {"text": "Upload"}},
                links=[],
                table={},
            )
        ],
        url_map={"https://upload.local": 0},
    )
    screen = _ScenarioScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Dosya secme diyaloğu acik. Open butonu gorunuyor.",
                frontmost_app="Safari",
                window_title="Open Dialog",
                accessibility=[{"label": "Open", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28}],
                vision=[],
                ocr_text="Open",
                ocr_lines=[],
            ),
            _ScreenState(summary="Yukleme tamamlandi.", frontmost_app="Safari", window_title="Upload Complete", accessibility=[], vision=[], ocr_text="Upload Complete", ocr_lines=[]),
        ],
        click_transitions={(360, 106): 1},
    )

    runner = OperatorScenarioRunner(desktop_host=host, artifacts_root=tmp_path / "scenario_artifacts")
    result = await runner.run(
        name="mixed-browser-fallback",
        clear_live_state=True,
        screen_services=screen.build(),
        browser_services=browser.build(),
        steps=[
            {"kind": "browser", "name": "open_upload_page", "action": "open", "url": "upload.local", "expected_url_contains": "upload.local", "expected_title_contains": "Upload", "verify": {"url_contains": "upload.local", "title_contains": "Upload"}},
            {"kind": "browser", "name": "confirm_native_dialog", "action": "click", "selector": "#upload", "native_dialog_expected": True, "screen_instruction": "Open butonuna tikla", "verify": {"fallback_used": True, "window_title_contains": "Upload Complete"}},
        ],
    )

    assert result["success"] is True
    assert result["steps"][1]["result"]["fallback"]["used"] is True
    assert screen.click_events[0] == (360, 106)
    assert result["action_logs"]


@pytest.mark.asyncio
async def test_operator_scenario_stops_after_failed_step(tmp_path: Path):
    host = DesktopHost(state_path=tmp_path / "desktop_state.json")
    screen = _ScenarioScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Confirm butonu gorunuyor ama tiklama sonucu degismiyor.",
                frontmost_app="Safari",
                window_title="Dialog",
                accessibility=[{"label": "Confirm", "role": "button", "x": 100, "y": 100, "width": 40, "height": 20}],
                vision=[],
                ocr_text="Confirm",
                ocr_lines=[],
            )
        ],
    )

    runner = OperatorScenarioRunner(desktop_host=host, artifacts_root=tmp_path / "scenario_artifacts")
    result = await runner.run(
        name="failed-sequence",
        clear_live_state=True,
        screen_services=screen.build(),
        steps=[
            {"kind": "screen", "name": "confirm_dialog", "instruction": "Confirm butonuna tikla", "verify": {"window_title_contains": "Done"}},
            {"kind": "screen", "name": "should_not_run", "instruction": "ekrana bak"},
        ],
    )

    assert result["success"] is False
    assert result["error_code"] == "NO_VISUAL_CHANGE"
    assert len(result["steps"]) == 1
    verification_path = next(item["path"] for item in result["artifacts"] if str(item["path"]).endswith("verification.json"))
    assert json.loads(Path(verification_path).read_text(encoding="utf-8"))["status"] == "failed"
