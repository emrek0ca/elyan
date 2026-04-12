from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from core.capabilities.browser.runtime import run_browser_runtime
from core.capabilities.file_ops.workflow import evaluate_file_ops_runtime
from core.capabilities.registry import evaluate_capability_runtime
from core.capabilities.screen_operator.workflow import evaluate_screen_operator_runtime


class _BrowserServices:
    def __init__(self, tmp_path: Path) -> None:
        self.tmp_path = tmp_path
        self.values: dict[str, str] = {}

    async def ensure_session(self, headless: bool = True) -> dict:
        _ = headless
        return {"success": True, "dom_available": True, "session_id": "sess-browser"}

    async def get_state(self) -> dict:
        return {
            "success": True,
            "dom_available": True,
            "url": "https://example.com/search",
            "title": "Search",
            "visible_text": "Cats and kittens",
            "dom_hash": "hash-1",
            "scroll": {"x": 0, "y": 0},
        }

    async def get_dom_snapshot(self) -> dict:
        state = await self.get_state()
        return {**state, "html": "<html><body>Cats and kittens</body></html>"}

    async def fill(self, selector: str, text: str, timeout_ms: int = 5000) -> dict:
        _ = timeout_ms
        self.values[selector] = text
        return {"success": True, "selector": selector, "text": text, "dom_available": True}

    async def get_value(self, selector: str) -> dict:
        return {"success": True, "selector": selector, "value": self.values.get(selector, ""), "dom_available": True}

    async def screenshot(self, path: str | None = None, selector: str | None = None) -> dict:
        _ = selector
        target = Path(path or (self.tmp_path / "page.png"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"browser-proof")
        return {"success": True, "path": str(target)}

    async def close(self) -> dict:
        return {"success": True}


def test_evaluate_capability_runtime_normalizes_file_ops_verification(tmp_path):
    target = tmp_path / "note.txt"
    target.write_text("hello", encoding="utf-8")
    ctx = SimpleNamespace(
        action="write_file",
        intent={"params": {"path": str(target)}},
        tool_results=[{"path": str(target), "exists": True, "size_bytes": 5, "sha256": "abc"}],
    )

    payload = evaluate_capability_runtime(ctx)

    assert payload["capability_id"] == "file_ops"
    assert payload["verification_envelope"]["capability_id"] == "file_ops"
    assert payload["verification_envelope"]["ok"] is True
    assert payload["verification_envelope"]["status"] == "success"
    assert payload["verification_envelope"]["failed"] == []
    assert payload["verify"]["capability"] == "file_ops"


def test_screen_operator_workflow_exposes_verification_envelope():
    ctx = SimpleNamespace(
        action="analyze_screen",
        intent={"params": {"mode": "inspect"}},
        tool_results=[
            {"summary": "Inbox visible"},
            {"ui_state": {"frontmost_app": "Notes"}},
            {"screenshot": "/tmp/screen.png"},
        ],
    )

    payload = evaluate_screen_operator_runtime(ctx)

    assert payload["verification_envelope"]["capability_id"] == "screen_operator"
    assert payload["verification_envelope"]["ok"] is True
    assert payload["verification_envelope"]["checks"]


@pytest.mark.asyncio
async def test_browser_runtime_exposes_normalized_verification_envelope(tmp_path):
    payload = await run_browser_runtime(
        action="type",
        selector="#q",
        text="kittens",
        services=_BrowserServices(tmp_path),
    )

    assert payload["success"] is True
    assert payload["verification_envelope"]["capability_id"] == "browser"
    assert payload["verification_envelope"]["ok"] is True
    assert payload["verification_envelope"]["status"] == "success"
    assert payload["verification_envelope"]["checks"]
