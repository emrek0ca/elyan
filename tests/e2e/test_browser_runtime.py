from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from core.capabilities.browser.runtime import NATIVE_DIALOG_REQUIRED, run_browser_runtime
from core.capabilities.browser.services import BrowserRuntimeServices
from core.capabilities.screen_operator.services import ScreenOperatorServices
from core.runtime.hosts import DesktopHost


@dataclass
class _PageState:
    url: str
    title: str
    visible_text: str
    html: str
    selectors: dict[str, dict[str, Any]]
    links: list[dict[str, Any]]
    table: dict[str, Any]


@dataclass
class _ScreenState:
    summary: str
    frontmost_app: str
    window_title: str
    accessibility: list[dict[str, Any]]
    vision: list[dict[str, Any]]
    ocr_text: str
    ocr_lines: list[dict[str, Any]]


class _FallbackScreenServices:
    def __init__(self, tmp_path: Path, states: list[_ScreenState], *, click_transitions: dict[tuple[int, int], int] | None = None) -> None:
        self.tmp_path = tmp_path
        self.states = list(states)
        self.index = 0
        self.click_transitions = dict(click_transitions or {})
        self.click_events: list[tuple[int, int]] = []

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
            self.index = int(next_index)
        return {"success": True, "x": x, "y": y}

    async def type_text(self, text: str, press_enter: bool = False) -> dict[str, Any]:
        _ = (text, press_enter)
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


class _FakeBrowserServices:
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
        self.scroll = {"x": 0, "y": 0}

    @property
    def current(self) -> _PageState:
        return self.states[self.index]

    def _state_payload(self) -> dict[str, Any]:
        return {
            "success": True,
            "dom_available": True,
            "url": self.current.url,
            "title": self.current.title,
            "visible_text": self.current.visible_text,
            "dom_hash": hashlib.sha256(self.current.html.encode("utf-8")).hexdigest(),
            "scroll": dict(self.scroll),
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
            self.index = self.url_map[url]
        return {"success": True, "url": self.current.url, "title": self.current.title, "status_code": 200, "dom_available": True}

    async def click(self, selector: str, timeout_ms: int = 5000) -> dict[str, Any]:
        _ = timeout_ms
        if selector not in self.current.selectors:
            return {"success": False, "error": "selector missing", "error_code": "DOM_TARGET_NOT_FOUND", "dom_available": True}
        transition = self.click_transitions.get((self.index, selector))
        if transition is not None:
            self.index = transition
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
            self.index = transition
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
        state = self._state_payload()
        return {**state, "html": self.current.html}

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
        before = dict(self.scroll)
        if direction == "down":
            self.scroll["y"] += int(amount)
        elif direction == "up":
            self.scroll["y"] -= int(amount)
        elif direction == "right":
            self.scroll["x"] += int(amount)
        else:
            self.scroll["x"] -= int(amount)
        return {"success": True, "before": before, "after": dict(self.scroll), "dom_available": True}

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
@pytest.mark.smoke
async def test_browser_runtime_opens_page_and_verifies_navigation(tmp_path: Path):
    services = _FakeBrowserServices(
        tmp_path,
        [
            _PageState(
                url="https://example.com",
                title="Example Domain",
                visible_text="Example Domain More information",
                html="<html><title>Example Domain</title><body>Example Domain</body></html>",
                selectors={},
                links=[{"href": "https://iana.org", "text": "More information"}],
                table={},
            )
        ],
        url_map={"https://example.com": 0},
    )

    result = await run_browser_runtime(
        action="open",
        url="https://example.com",
        expected_url_contains="example.com",
        expected_title_contains="Example",
        services=services.build(),
    )

    assert result["success"] is True
    assert result["url"] == "https://example.com"
    assert result["title"] == "Example Domain"
    assert result["artifacts"]
    assert result["verifier_outcomes"][0]["ok"] is True


@pytest.mark.asyncio
async def test_browser_runtime_artifacts_use_resolved_data_dir(tmp_path: Path, monkeypatch):
    services = _FakeBrowserServices(
        tmp_path,
        [
            _PageState(
                url="https://example.com",
                title="Example Domain",
                visible_text="Example Domain",
                html="<html><title>Example Domain</title><body>Example Domain</body></html>",
                selectors={},
                links=[],
                table={},
            )
        ],
        url_map={"https://example.com": 0},
    )
    data_root = (tmp_path / "elyan_data").resolve()
    monkeypatch.setattr(
        "core.capabilities.browser.runtime.resolve_elyan_data_dir",
        lambda: data_root,
    )

    result = await run_browser_runtime(action="open", url="https://example.com", services=services.build())
    assert result["success"] is True
    base = (data_root / "browser_runtime").resolve()
    assert result["artifacts"]
    for item in result["artifacts"]:
        p = Path(str(item.get("path") or "")).resolve()
        assert str(p).startswith(str(base))


@pytest.mark.asyncio
async def test_browser_runtime_fills_search_field_and_submits(tmp_path: Path):
    services = _FakeBrowserServices(
        tmp_path,
        [
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
        submit_transitions={(0, "#q"): 1},
    )

    type_result = await run_browser_runtime(action="type", selector="#q", text="kittens", services=services.build())
    submit_result = await run_browser_runtime(
        action="submit",
        selector="#q",
        expected_text="kittens",
        services=services.build(),
    )

    assert type_result["success"] is True
    assert submit_result["success"] is True
    assert "kittens" in submit_result["browser_state"]["visible_text"].lower()
    assert submit_result["verifier_outcomes"][0]["ok"] is True


@pytest.mark.asyncio
async def test_browser_runtime_clicks_and_verifies_dom_transition(tmp_path: Path):
    services = _FakeBrowserServices(
        tmp_path,
        [
            _PageState(
                url="https://app.local",
                title="Start",
                visible_text="Continue",
                html="<html><body><button id='continue'>Continue</button></body></html>",
                selectors={"#continue": {"text": "Continue"}},
                links=[],
                table={},
            ),
            _PageState(
                url="https://app.local/next",
                title="Next",
                visible_text="Welcome next step",
                html="<html><body>Welcome next step</body></html>",
                selectors={"#welcome": {"text": "Welcome next step"}},
                links=[],
                table={},
            ),
        ],
        click_transitions={(0, "#continue"): 1},
    )

    result = await run_browser_runtime(
        action="click",
        selector="#continue",
        expected_text="Welcome",
        services=services.build(),
    )

    assert result["success"] is True
    assert result["browser_state"]["url"].endswith("/next")
    assert result["verifier_outcomes"][0]["ok"] is True


@pytest.mark.asyncio
async def test_browser_runtime_extracts_visible_page_content(tmp_path: Path):
    services = _FakeBrowserServices(
        tmp_path,
        [
            _PageState(
                url="https://docs.local",
                title="Docs",
                visible_text="API Reference Install Usage",
                html="<html><body>API Reference Install Usage</body></html>",
                selectors={"main": {"text": "API Reference Install Usage"}},
                links=[],
                table={},
            )
        ],
    )

    result = await run_browser_runtime(action="extract", selector="main", services=services.build(), screenshot=False)

    assert result["success"] is True
    assert "API Reference" in result["extracted_text"]
    assert result["verifier_outcomes"][0]["ok"] is True


@pytest.mark.asyncio
async def test_browser_runtime_hands_off_native_dialog_to_screen_operator(tmp_path: Path):
    services = _FakeBrowserServices(tmp_path, [], dom_available=False)
    seen: dict[str, Any] = {}

    async def _fake_screen_operator_runner(**kwargs):
        seen.update(kwargs)
        return {
            "success": True,
            "status": "success",
            "goal_achieved": True,
            "message": "Native dialog handled.",
            "summary": "Native dialog handled.",
            "artifacts": [{"path": "/tmp/dialog.png", "type": "image"}],
            "screenshots": ["/tmp/dialog.png"],
            "action_logs": [{"step": 1}],
            "verifier_outcomes": [{"ok": True}],
            "task_state": {"current_step": 1},
            "ui_state": {"frontmost_app": "Safari"},
        }

    result = await run_browser_runtime(
        action="click",
        selector="#upload",
        native_dialog_expected=True,
        screen_instruction="Dosya secme diyalogunu onayla",
        services=services.build(),
        screen_operator_runner=_fake_screen_operator_runner,
    )

    assert result["success"] is True
    assert result["fallback"]["used"] is True
    assert result["fallback"]["reason"] == NATIVE_DIALOG_REQUIRED
    assert seen["instruction"] == "Dosya secme diyalogunu onayla"


@pytest.mark.asyncio
async def test_browser_runtime_treats_partial_native_dialog_fallback_as_failure(tmp_path: Path):
    services = _FakeBrowserServices(
        tmp_path,
        [
            _PageState(
                url="https://upload.local/review",
                title="Review Upload",
                visible_text="Save",
                html="<html><body><button id='save'>Save</button></body></html>",
                selectors={"#save": {"text": "Save"}},
                links=[],
                table={},
            )
        ],
        dom_available=False,
    )

    async def _fake_screen_operator_runner(**kwargs):
        _ = kwargs
        return {
            "success": True,
            "status": "partial",
            "goal_achieved": False,
            "message": "Dialog still open.",
            "summary": "Dialog still open.",
            "artifacts": [],
            "screenshots": [],
            "action_logs": [],
            "verifier_outcomes": [],
            "task_state": {"current_step": 0},
            "ui_state": {"frontmost_app": "Safari", "active_window": {"title": "Upload Dialog"}},
        }

    result = await run_browser_runtime(
        action="click",
        selector="#upload",
        native_dialog_expected=True,
        services=services.build(),
        screen_operator_runner=_fake_screen_operator_runner,
    )

    assert result["success"] is False
    assert result["error_code"] == NATIVE_DIALOG_REQUIRED
    assert result["browser_state"]["title"] == "Review Upload"


@pytest.mark.asyncio
async def test_browser_runtime_dom_loss_fallback_uses_screen_target_scoring(tmp_path: Path):
    browser = _FakeBrowserServices(tmp_path, [], dom_available=False)
    screen = _FallbackScreenServices(
        tmp_path,
        [
            _ScreenState(
                summary="Search field ve Search button ayni ekranda.",
                frontmost_app="Safari",
                window_title="Search",
                accessibility=[
                    {"label": "Search", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30},
                    {"label": "Search", "role": "button", "x": 320, "y": 92, "width": 80, "height": 28},
                ],
                vision=[],
                ocr_text="Search",
                ocr_lines=[],
            ),
            _ScreenState(
                summary="Results sayfasi acildi.",
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
    host = DesktopHost(state_path=tmp_path / "desktop_host_state.json")

    async def _run_screen_operator(**kwargs):
        return await host.run_screen_operator(services=screen.build(), **kwargs)

    result = await run_browser_runtime(
        action="click",
        selector="#search",
        screen_instruction="Search butonuna tikla",
        services=browser.build(),
        screen_operator_runner=_run_screen_operator,
    )

    assert result["success"] is True
    assert result["fallback"]["used"] is True
    assert screen.click_events[0] == (360, 106)
    assert result["action_logs"][0]["planned_action"]["decision_trace"]["chosen"]["role"] == "button"
