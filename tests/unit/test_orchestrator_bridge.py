"""Tests for OrchestratorBridge — verifies subsystem wiring."""

import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.multi_agent.orchestrator_bridge import OrchestratorBridge


@pytest.fixture
def bridge():
    """Bridge with mocked subsystems."""
    b = OrchestratorBridge.__new__(OrchestratorBridge)
    b._bus = MagicMock()
    b._bus.publish = AsyncMock()
    b._tracker = MagicMock()
    b._tracker.register = AsyncMock()
    b._tracker.start = AsyncMock()
    b._tracker.complete = AsyncMock()
    b._tracker.fail = AsyncMock()
    b._tracker.metrics = MagicMock(return_value={"success_rate": 0.95})
    b._model_policy = MagicMock()
    return b


@pytest.mark.asyncio
async def test_job_started_creates_task(bridge):
    result = await bridge.on_job_started("job_1", "web_site_job", "build a site")
    assert result == "job_1"
    bridge._tracker.register.assert_called_once()
    bridge._tracker.start.assert_called_once()


@pytest.mark.asyncio
async def test_job_completed(bridge):
    await bridge.on_job_completed("job_1", {"zip": "/out.zip"})
    bridge._tracker.complete.assert_called_once_with("job_1", {"zip": "/out.zip"})


@pytest.mark.asyncio
async def test_job_failed(bridge):
    await bridge.on_job_failed("job_1", "qa_failed")
    bridge._tracker.fail.assert_called_once_with("job_1", "qa_failed")


@pytest.mark.asyncio
async def test_specialist_called_publishes_and_tracks(bridge):
    child_id = await bridge.on_specialist_called("job_1", "researcher", "search for X")
    assert child_id is not None
    assert "researcher" in child_id
    bridge._tracker.register.assert_called_once()
    bridge._bus.publish.assert_called_once()


@pytest.mark.asyncio
async def test_specialist_completed_records_outcome(bridge):
    decision = MagicMock()
    decision.to_dict.return_value = {"provider": "ollama", "model": "llama3.2:3b"}
    bridge._model_policy.record_outcome = MagicMock()

    await bridge.on_specialist_completed(
        "job_1:researcher:123", "researcher",
        success=True, latency_ms=450.0, model_used="ollama/llama3.2:3b",
    )
    bridge._tracker.complete.assert_called_once()
    bridge._model_policy.record_outcome.assert_called_once_with("ollama", "llama3.2:3b", True, 450.0)


@pytest.mark.asyncio
async def test_phase_started_publishes(bridge):
    await bridge.on_phase_started("job_1", "execute")
    bridge._bus.publish.assert_called_once()
    msg = bridge._bus.publish.call_args[0][0]
    assert msg.topic == "orchestrator.phase.execute"


@pytest.mark.asyncio
async def test_qa_result_publishes(bridge):
    await bridge.on_qa_result("job_1", False, ["issue1", "issue2"])
    msg = bridge._bus.publish.call_args[0][0]
    assert msg.payload["passed"] is False
    assert msg.payload["issue_count"] == 2


def test_get_metrics(bridge):
    m = bridge.get_metrics()
    assert m["success_rate"] == 0.95


def test_model_selection_returns_dict(bridge):
    from core.llm.model_selection_policy import ModelDecision
    decision = ModelDecision(
        provider="ollama", model="qwen2.5:7b", is_local=True,
        score=5.0, reason="test", quality_score=0.55,
    )
    bridge._model_policy.select = MagicMock(return_value=decision)

    result = bridge.select_model_for_specialist("researcher")
    assert result is not None
    assert result["provider"] == "ollama"


def test_graceful_degradation_no_subsystems():
    """Bridge works when all subsystems are None."""
    b = OrchestratorBridge.__new__(OrchestratorBridge)
    b._bus = None
    b._tracker = None
    b._model_policy = None

    assert b.get_metrics() == {"tracker": "unavailable"}
    assert b.select_model_for_specialist("test") is None
