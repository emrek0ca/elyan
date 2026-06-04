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
    assert structured_result == {"kind": "document_write"}
    assert artifacts == [{"path": str(output_path)}]
    assert attempts["count"] == 2
    assert runtime_state["metrics"]["verificationRetries"] == 1
    assert runtime_state["metrics"]["completed"] >= 1


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
