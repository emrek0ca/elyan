from __future__ import annotations

from pathlib import Path

import pytest

from runtime import state_store
from runtime.executor_core import ExecutorCore


def _isolate_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(state_store, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(state_store, "STATE_PATH", tmp_path / "elyan_state.json")
    monkeypatch.setattr(state_store, "LEGACY_STATE_PATH", tmp_path / "legacy.json")


def test_executor_core_retries_verification_for_artifact_outputs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    output_path = tmp_path / "elyan_output.txt"
    attempts = {"count": 0}

    def execute_step(_capability: str, args: dict[str, object], _state: dict[str, object], _source: str):
        attempts["count"] += 1
        if attempts["count"] == 1:
            return {
                "ok": True,
                "output": "",
                "result": {"kind": "document_write"},
                "artifacts": [{"path": str(output_path)}],
            }, []
        output_path.write_text("verified", encoding="utf-8")
        return {
            "ok": True,
            "output": "tamam",
            "result": {"kind": "document_write"},
            "artifacts": [{"path": str(output_path)}],
        }, []

    ok, content, _events, error_code, structured_result, artifacts = executor.execute_plan_steps(
        steps=[
            {
                "capability": "document_write",
                "args": {"outputPath": str(output_path)},
            }
        ],
        state_factory=state_store.snapshot,
        execute_step=execute_step,
        source="confirmed_plan",
    )

    runtime_state = state_store.snapshot()["runtime"]["executor"]
    assert ok is True
    assert content == "tamam"
    assert error_code == ""
    # P3 kanıt sözleşmesi doğrulanan adımın sonucuna stepEvidence işler.
    assert structured_result["kind"] == "document_write"
    assert structured_result["stepEvidence"]["kind"] == "file_hash"
    assert structured_result["stepEvidence"]["verified"] is True
    assert artifacts == [{"path": str(output_path)}]
    assert attempts["count"] == 2
    assert runtime_state["metrics"]["verificationRetries"] == 1
    assert runtime_state["metrics"]["completed"] >= 1
    assert runtime_state["lastExecutionTrace"]["plannerVersion"] == "runtime_v2"
    assert runtime_state["lastExecutionTrace"]["repair"]["attempted"] is True
    assert runtime_state["lastExecutionTrace"]["repair"]["repairAttempts"] == 1
    assert runtime_state["lastExecutionTrace"]["verificationState"]["status"] == "repaired"
    assert runtime_state["lastExecutionTrace"]["stepStates"][0]["verificationStatus"] == "repaired"


def test_executor_core_status_payload_exposes_router_and_capability_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    state_store.update_state({"providers": {"routingPolicy": "local_first", "fallbackToCloud": True}})

    payload = executor.status_payload(
        state=state_store.snapshot(),
        runtime_capabilities=["web_research", "document_write", "shell_run"],
        local_provider_readiness={"ollama": {"available": True}},
        cloud_provider_readiness={"openai": {"configured": False}},
    )

    assert payload["available"] is True
    assert payload["graphBackend"] in {"langgraph", "sequential_fallback"}
    assert payload["modelRouterBackend"] in {"litellm", "native_router"}
    assert payload["modelRouterReadiness"]["policy"] == "local_first"
    assert payload["capabilityMetadataSummary"]["total"] == 3
    assert payload["capabilityMetadataSummary"]["sideEffectCount"] == 2
    assert payload["agentStatus"]["active"] is False
    assert payload["agentStatus"]["executionStrategy"] == "single_lane"
    assert payload["agentStatus"]["stepCount"] == 0
    assert payload["agentStatus"]["agentRoles"] == []


def test_executor_core_agent_plan_decomposes_steps_into_roles(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    execution_id = executor.begin_execution(
        source="conversation",
        summary="üç aşamalı görev",
        planned_steps=[
            {"capability": "retrieve_context", "args": {"query": "notlar"}},
            {"capability": "open_app", "args": {"app_name": "Finder"}},
            {"capability": "document_write", "args": {"outputPath": "/tmp/out.txt"}},
        ],
    )

    payload = executor.status_payload(
        state=state_store.snapshot(),
        runtime_capabilities=["retrieve_context", "open_app", "document_write"],
        local_provider_readiness={"ollama": {"available": True}},
        cloud_provider_readiness={},
    )

    assert payload["agentStatus"]["active"] is True
    assert payload["agentStatus"]["stepCount"] == 3
    assert payload["agentStatus"]["executionStrategy"] == "multi_lane"
    assert payload["agentStatus"]["agentRoles"] == ["planner", "observer", "operator", "writer"]
    assert payload["agentStatus"]["planSummary"] == "üç aşamalı görev"
    assert payload["currentExecutions"][0]["id"] == execution_id
    assert payload["currentExecutions"][0]["agentPlan"]["stepRoles"][0]["role"] == "observer"
    assert payload["currentExecutions"][0]["agentPlan"]["stepRoles"][0]["phase"] == "gather"
    assert payload["currentExecutions"][0]["agentPlan"]["phases"][0]["phase"] == "gather"
    assert payload["currentExecutions"][0]["agentPlan"]["riskLevel"] == "approval_required"
    assert payload["currentExecutions"][0]["agentPlan"]["requiresApproval"] is True
    assert payload["currentExecutions"][0]["executionTrace"]["plannerVersion"] == "runtime_v2"
    assert payload["currentExecutions"][0]["executionTrace"]["executionStrategy"] == "multi_lane"
    assert payload["agentStatus"]["nativeReadiness"] == {}
    assert payload["agentStatus"]["degradationReasons"] == []


def test_executor_core_verifies_foreground_confirmed_for_open_app(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()

    ok, content, _events, error_code, structured_result, _artifacts = executor.execute_plan_steps(
        steps=[{"capability": "open_app", "args": {"app_name": "Google Chrome"}}],
        state_factory=state_store.snapshot,
        execute_step=lambda *_args: (
            {
                "ok": True,
                "output": "Google Chrome açıldı.",
                "result": {
                    "appName": "Google Chrome",
                    "foregroundConfirmed": True,
                    "verificationStatus": "foreground_confirmed",
                },
                "artifacts": [],
            },
            [],
        ),
        source="confirmed_plan",
    )

    assert ok is True
    assert content == "Google Chrome açıldı."
    assert error_code == ""
    assert structured_result == {
        "appName": "Google Chrome",
        "foregroundConfirmed": True,
        "verificationStatus": "foreground_confirmed",
    }


def test_executor_core_fails_when_browser_handoff_cannot_be_verified(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()

    ok, content, _events, error_code, _structured_result, _artifacts = executor.execute_plan_steps(
        steps=[{"capability": "browser_control", "args": {"action": "search", "query": "elyan"}}],
        state_factory=state_store.snapshot,
        execute_step=lambda *_args: (
            {
                "ok": True,
                "output": "elyan için arama açıldı.",
                "result": {
                    "action": "search",
                    "launched": False,
                    "targetUrl": "",
                    "query": "",
                    "handoff": "",
                    "handoffVerified": False,
                },
                "artifacts": [],
            },
            [],
        ),
        source="confirmed_plan",
    )

    assert ok is False
    assert error_code == "VERIFICATION_FAILED"
    assert content == "Tarayıcı handoff doğrulanamadı."
    runtime_state = state_store.snapshot()["runtime"]["executor"]
    assert runtime_state["lastExecutionTrace"]["stopReason"] == "verification_failed"
    assert runtime_state["lastExecutionTrace"]["verificationState"]["status"] == "failed"
    assert runtime_state["lastExecutionTrace"]["stepStates"][0]["status"] == "failed"
    assert runtime_state["lastExecutionTrace"]["stepStates"][0]["errorCode"] == "VERIFICATION_FAILED"


def test_executor_core_accepts_verified_media_handoff(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()

    ok, content, _events, error_code, structured_result, _artifacts = executor.execute_plan_steps(
        steps=[{"capability": "play_media", "args": {"query": "lofi", "provider": "youtube"}}],
        state_factory=state_store.snapshot,
        execute_step=lambda *_args: (
            {
                "ok": True,
                "output": "YouTube'da oynatılıyor: lofi",
                "result": {
                    "provider": "youtube",
                    "handoff": "youtube_watch",
                    "query": "lofi",
                    "launched": True,
                    "handoffVerified": True,
                },
                "artifacts": [],
            },
            [],
        ),
        source="confirmed_plan",
    )

    assert ok is True
    assert error_code == ""
    assert content == "YouTube'da oynatılıyor: lofi"
    assert structured_result["provider"] == "youtube"


def test_executor_core_agent_status_maps_runtime_stage_to_simple_copy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    execution_id = executor.begin_execution(source="conversation", summary="belgeyi kontrol et")
    executor.record_stage(execution_id, "step_execution", detail="retrieve_context")

    payload = executor.status_payload(
        state=state_store.snapshot(),
        runtime_capabilities=["retrieve_context"],
        local_provider_readiness={"ollama": {"available": True}},
        cloud_provider_readiness={},
    )

    assert payload["agentStatus"]["active"] is True
    assert payload["agentStatus"]["displayStage"] == "Kaynak topluyor"
    assert payload["agentStatus"]["verificationUsed"] is True


def test_executor_react_replans_after_tool_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """İlk adım araç hatasıyla düşerse, replan_fn kalan planı çalışan bir adımla
    revize edip yürütmeyi tamamlamalı (statik plan iptali yerine ReAct)."""
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()
    calls: list[str] = []

    def execute_step(capability: str, _args, _state, _source):
        calls.append(capability)
        if capability == "web_research":
            return {"ok": False, "error": {"code": "NETWORK_FAILED", "message": "ağ yok"}}, []
        return {"ok": True, "output": "yerel bağlamdan yanıt", "result": {"kind": capability}}, []

    replan_calls: list[dict] = []

    def replan_fn(context: dict):
        replan_calls.append(context)
        # Başarısız web_research yerine yerel retrieve_context ile devam et.
        return [{"capability": "retrieve_context", "args": {"query": "x"}}]

    ok, content, _events, error_code, structured_result, _artifacts = executor.execute_plan_steps(
        steps=[{"capability": "web_research", "args": {"query": "x"}}],
        state_factory=state_store.snapshot,
        execute_step=execute_step,
        source="confirmed_plan",
        replan_fn=replan_fn,
    )

    assert ok is True
    assert error_code == ""
    assert content == "yerel bağlamdan yanıt"
    assert calls == ["web_research", "retrieve_context"]
    assert replan_calls and replan_calls[0]["failedCapability"] == "web_research"
    assert replan_calls[0]["errorCode"] == "NETWORK_FAILED"
    trace = state_store.snapshot()["runtime"]["executor"]["lastExecutionTrace"]
    assert trace["repair"]["attempted"] is True


def test_executor_react_gives_up_when_replan_budget_exhausted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """replan_fn sürekli başarısız adım döndürürse bütçe dolunca iptal edilmeli."""
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()

    def execute_step(_capability, _args, _state, _source):
        return {"ok": False, "error": {"code": "NETWORK_FAILED", "message": "ağ yok"}}, []

    replan_count = {"n": 0}

    def replan_fn(_context):
        replan_count["n"] += 1
        return [{"capability": "web_research", "args": {"query": "x"}}]

    ok, _content, _events, error_code, _structured, _artifacts = executor.execute_plan_steps(
        steps=[{"capability": "web_research", "args": {"query": "x"}}],
        state_factory=state_store.snapshot,
        execute_step=execute_step,
        source="confirmed_plan",
        replan_fn=replan_fn,
        max_replans=2,
    )

    assert ok is False
    assert error_code == "NETWORK_FAILED"
    assert replan_count["n"] == 2  # bütçe kadar denendi, sonra iptal


def test_executor_react_no_replan_fn_keeps_static_abort(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """replan_fn verilmezse davranış eskisi gibi: ilk hata planı iptal eder."""
    _isolate_state(monkeypatch, tmp_path)
    executor = ExecutorCore()

    ok, _content, _events, error_code, _structured, _artifacts = executor.execute_plan_steps(
        steps=[{"capability": "web_research", "args": {}}],
        state_factory=state_store.snapshot,
        execute_step=lambda *_a: ({"ok": False, "error": {"code": "NETWORK_FAILED", "message": "x"}}, []),
        source="confirmed_plan",
    )

    assert ok is False
    assert error_code == "NETWORK_FAILED"
