from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace

import pytest

from core.cowork_runtime import CoworkRuntime, ScreenState, ToolDecision
import core.vision_automation as vision_automation


class _MemoryStore:
    def __init__(self) -> None:
        self.calls = defaultdict(int)

    def get_user_preferences(self, user_id):
        self.calls["preferences"] += 1
        _ = user_id
        return {"preferred_language": "tr", "response_length_bias": "short"}

    def get_recent_conversations(self, user_id, limit=5):
        self.calls["recent"] += 1
        _ = (user_id, limit)
        return [{"role": "assistant", "content": "Eski proje baglami"}]

    def get_task_history(self, user_id, limit=5):
        self.calls["task_history"] += 1
        _ = (user_id, limit)
        return [{"goal": "Python hesap makinesi", "outcome": "done"}]

    def query_knowledge(self, entity):
        self.calls["knowledge"] += 1
        _ = entity
        return [{"value": "Eski gorev notu"}]


@pytest.mark.asyncio
async def test_build_memory_context_skips_task_history_for_communication():
    runtime = CoworkRuntime()
    session = runtime.start_session(
        user_id="u1",
        channel="cli",
        objective="Merhaba",
        quick_intent=SimpleNamespace(category="greeting"),
        runtime_policy={},
    )
    store = _MemoryStore()

    bundle = await runtime.build_memory_context(
        session=session,
        user_input="Merhaba",
        memory_store=store,
    )

    assert bundle["policy"]["scope"] == "communication_minimal"
    assert bundle["topic_shift_detected"] is True
    assert store.calls["preferences"] == 1
    assert store.calls["recent"] == 0
    assert store.calls["task_history"] == 0
    assert store.calls["knowledge"] == 0
    assert "Python hesap makinesi" not in bundle["text"]
    assert "Preferred language: tr" in bundle["text"]


@pytest.mark.asyncio
async def test_collect_screen_state_fuses_sources():
    runtime = CoworkRuntime()

    async def fake_runner(**kwargs):
        _ = kwargs
        return {
            "success": True,
            "summary": "Safari penceresi acik.",
            "path": "/tmp/screen.png",
            "screenshot": {"path": "/tmp/screen.png"},
            "window_metadata": {
                "frontmost_app": "Safari",
                "window_title": "Search",
                "bounds": {"x": 10, "y": 20, "width": 800, "height": 600},
            },
            "ui_state": {
                "frontmost_app": "Safari",
                "active_window": {"title": "Search", "bounds": {"x": 10, "y": 20, "width": 800, "height": 600}},
                "confidence": 0.81,
                "source_counts": {"accessibility": 1, "ocr": 1, "vision": 1},
                "elements": [{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}],
            },
            "accessibility": {
                "elements": [{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}],
            },
            "ocr": {
                "text": "Search kittens",
                "lines": [{"text": "Search kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}],
            },
            "vision": {
                "summary": "Arama sonucu gorunuyor.",
                "elements": [{"label": "Search button", "role": "button", "x": 250, "y": 90, "width": 100, "height": 30}],
            },
        }

    async def fake_clipboard():
        return {"success": True, "text": "Clipboard notu"}

    async def fake_display():
        return {"success": True, "displays": [{"id": 1, "width": 1920, "height": 1080}]}

    def fake_window():
        return {"app": "Safari", "title": "Search", "cursor": {"x": 14, "y": 30}, "selection": {"text": "Search kittens"}}

    state = await runtime.collect_screen_state(
        goal="kedi ara",
        screen_operator_runner=fake_runner,
        clipboard_reader=fake_clipboard,
        display_info_reader=fake_display,
        window_context_reader=fake_window,
    )

    assert state.frontmost_app == "Safari"
    assert state.summary == "Safari penceresi acik."
    assert state.ocr_text == "Search kittens"
    assert state.clipboard_text == "Clipboard notu"
    assert state.display_info["displays"][0]["width"] == 1920
    assert state.cursor["x"] == 14
    assert state.selection["text"] == "Search kittens"
    prompt = state.to_prompt_block()
    assert "Frontmost app: Safari" in prompt
    assert "Clipboard: Clipboard notu" in prompt
    assert "Search field" in prompt


def test_score_tool_prefers_safe_low_latency_tools():
    runtime = CoworkRuntime()
    usage_snapshot = {
        "stats": {
            "delete_file": {"calls": 4, "success": 1, "failure": 3, "avg_latency_ms": 1200.0, "success_rate": 25.0},
            "read_file": {"calls": 100, "success": 99, "failure": 1, "avg_latency_ms": 45.0, "success_rate": 99.0},
        }
    }

    risky = runtime.score_tool("delete_file", user_input="delete_file /tmp/demo", usage_snapshot=usage_snapshot)
    safe = runtime.score_tool("read_file", user_input="read_file /tmp/demo", usage_snapshot=usage_snapshot)

    assert risky.risk_level == "high"
    assert risky.requires_approval is True
    assert "risk=high" in risky.rationale
    assert "requires_approval" in risky.rationale
    assert safe.score > risky.score
    assert safe.available is True


@pytest.mark.asyncio
async def test_vision_automate_returns_fused_screen_state(monkeypatch):
    captured: dict[str, str] = {}

    class _DummyLLM:
        pass

    async def fake_collect_screen_state(goal: str):
        _ = goal
        return ScreenState(
            summary="Safari penceresi acik.",
            frontmost_app="Safari",
            active_window={"title": "Search", "bounds": {"x": 10, "y": 20, "width": 800, "height": 600}},
            accessibility=[{"label": "Search field", "role": "text_field", "x": 110, "y": 90, "width": 160, "height": 30}],
            ocr_text="Search kittens",
            ocr_lines=[{"text": "Search kittens", "x": 120, "y": 98, "width": 70, "height": 18, "confidence": 0.95}],
            clipboard_text="Clipboard notu",
            confidence=0.84,
        )

    async def fake_run_vision_task(goal: str, llm_client=None, max_steps: int = 5, context: str = ""):
        _ = (goal, llm_client, max_steps)
        captured["context"] = context
        return vision_automation.VisionAutomationResult(
            goal=goal,
            success=True,
            total_steps=2,
            total_duration_ms=42.0,
            final_state="complete",
            error="",
        )

    monkeypatch.setattr("core.llm_client.LLMClient", _DummyLLM)
    monkeypatch.setattr(vision_automation, "get_cowork_runtime", lambda: SimpleNamespace(collect_screen_state=fake_collect_screen_state))
    monkeypatch.setattr(vision_automation, "run_vision_task", fake_run_vision_task)

    payload = await vision_automation.vision_automate("ekrandaki butona tikla", max_steps=2)

    assert payload["success"] is True
    assert payload["steps_taken"] == 2
    assert payload["screen_state"]["frontmost_app"] == "Safari"
    assert "Frontmost app: Safari" in captured["context"]
    assert "Clipboard: Clipboard notu" in captured["context"]
