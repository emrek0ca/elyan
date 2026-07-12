"""ReAct tarayıcı ajanı sözleşmeleri (Faz 3): döngü, güvenlik, bütçe."""

from __future__ import annotations

from typing import Any

import pytest

from runtime import browser_agent
from runtime import safety_policy
from runtime.capability_registry import SafeCapabilityError


@pytest.fixture(autouse=True)
def _fake_session(monkeypatch: pytest.MonkeyPatch):
    """browser_session çağrılarını gerçek tarayıcı açmadan taklit eder."""
    calls: list[tuple[str, dict[str, Any]]] = []

    def _record(name: str, payload: dict[str, Any], result: dict[str, Any]):
        calls.append((name, payload))
        return {"text": f"{name} tamam", "result": result}

    monkeypatch.setattr(
        browser_agent.browser_session,
        "session_snapshot",
        lambda limit=40: _record("snapshot", {"limit": limit}, {"url": "https://y.example", "title": "Kanal", "elements": [{"tag": "a", "text": "Videolar"}]}),
    )
    monkeypatch.setattr(
        browser_agent.browser_session,
        "session_goto",
        lambda url: _record("goto", {"url": url}, {"url": url, "title": "Sayfa", "navigated": True}),
    )
    monkeypatch.setattr(
        browser_agent.browser_session,
        "session_click",
        lambda selector="", text="", role="": _record("click", {"selector": selector, "text": text}, {"clicked": True}),
    )
    monkeypatch.setattr(
        browser_agent.browser_session,
        "session_extract",
        lambda selector="", attribute="", limit=20: _record(
            "extract",
            {"selector": selector},
            {"items": [{"text": "v1", "href": "https://v1"}, {"text": "v2", "href": "https://v2"}], "itemCount": 2},
        ),
    )
    monkeypatch.setattr(
        browser_agent.browser_session,
        "session_download",
        lambda selector="", text="", url="", output_dir="": _record("download", {"url": url}, {"downloaded": True, "outputPath": "/tmp/t.txt"}),
    )
    yield calls
    browser_agent.register_decider(None)  # type: ignore[arg-type]


def _decider_script(script: list[dict[str, Any]]):
    state = {"i": 0}

    def _decide(_payload: dict[str, Any]) -> dict[str, Any]:
        decision = script[min(state["i"], len(script) - 1)]
        state["i"] += 1
        return decision

    return _decide


def test_agent_runs_observe_act_loop_and_collects(_fake_session) -> None:
    browser_agent.register_decider(_decider_script([
        {"action": "goto", "url": "https://youtube.com", "reason": "kanala git"},
        {"action": "extract", "selector": "a#video-title", "attribute": "href", "reason": "linkleri topla"},
        {"action": "done", "summary": "Linkler toplandı."},
    ]))
    outcome = browser_agent.run("kanalımdaki videoların linklerini topla")
    result = outcome["result"]
    assert result["completed"] is True
    assert result["turns"] == 3
    assert [item["href"] for item in result["collected"]] == ["https://v1", "https://v2"]
    assert [entry["action"] for entry in result["history"]] == ["goto", "extract"]


def test_agent_fail_action_raises_honest_error(_fake_session) -> None:
    browser_agent.register_decider(_decider_script([
        {"action": "fail", "reason": "Giriş yapılmamış."},
    ]))
    with pytest.raises(SafeCapabilityError) as excinfo:
        browser_agent.run("kanalımı aç")
    assert excinfo.value.code == "REACT_GOAL_FAILED"
    assert "Giriş yapılmamış" in excinfo.value.message


def test_agent_stops_when_decider_repeats_same_action(_fake_session) -> None:
    browser_agent.register_decider(_decider_script([
        {"action": "click", "text": "Videolar"},
        {"action": "click", "text": "Videolar"},
    ]))
    with pytest.raises(SafeCapabilityError) as excinfo:
        browser_agent.run("videolar sekmesine geç")
    assert excinfo.value.code == "REACT_STUCK"


def test_agent_budget_exhaustion_is_explicit(_fake_session) -> None:
    # Hep farklı ama done'a ulaşmayan kararlar → bütçe bitince dürüst hata.
    counter = {"i": 0}

    def _restless(_payload: dict[str, Any]) -> dict[str, Any]:
        counter["i"] += 1
        return {"action": "goto", "url": f"https://p{counter['i']}.example"}

    browser_agent.register_decider(_restless)
    with pytest.raises(SafeCapabilityError) as excinfo:
        browser_agent.run("bitmeyen görev", max_turns=3)
    assert excinfo.value.code == "REACT_BUDGET_EXHAUSTED"


def test_agent_requires_decider() -> None:
    browser_agent.register_decider(None)  # type: ignore[arg-type]
    with pytest.raises(SafeCapabilityError) as excinfo:
        browser_agent.run("bir şey yap")
    assert excinfo.value.code == "server_brain_unavailable"


def test_agent_policy_gated_by_browser_permission() -> None:
    denied = safety_policy.evaluate_tool("browser_agent.run", {}, {})
    assert not denied.allowed and denied.code == "PERMISSION_REQUIRED"
    full_access = {"runtime": {"access": {"fullAccessSession": {"enabled": True}}}}
    assert safety_policy.evaluate_tool("browser_agent.run", {}, full_access).allowed
