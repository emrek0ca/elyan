
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from core.predictive_tasks import PredictiveTaskEngine, TaskPrediction, PredictionConfidence
from core.agent import Agent

@pytest.mark.asyncio
async def test_predictive_draft_injection():
    # 1. Setup Mock LLM
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value="Draft Content from LLM")
    
    # 2. Setup Predictive Engine with Mock LLM
    engine = PredictiveTaskEngine(llm_client=mock_llm)
    
    # 3. Create a prediction that triggers draft generation
    pred = TaskPrediction(
        action="write_file",
        params={"path": "test_report.md"},
        confidence=PredictionConfidence.HIGH,
        reasoning="Research complete"
    )
    
    # 4. Execute prefetch (should generate draft)
    await engine.prefetch_dependencies([pred])
    
    # Verify draft is cached
    content = engine.get_prefetched_content("write_file")
    assert content == "Draft Content from LLM"
    
    # Verify cache is cleared after retrieval
    assert engine.get_prefetched_content("write_file") is None

@pytest.mark.asyncio
async def test_agent_uses_prefetched_draft(monkeypatch):
    # 1. Setup Agent and Mock Predictive Engine
    agent = Agent()
    mock_predictor = MagicMock()
    mock_predictor.get_prefetched_content.return_value = "Prefetched Content"
    
    # Monkeypatch the global getter to return our mock
    monkeypatch.setattr("core.agent.get_predictive_task_engine", lambda: mock_predictor)
    
    # 2. Simulate parameter preparation for write_file with missing content
    # We call _infer_missing_param_value directly to test the logic
    # Note: agent._prepare_tool_params calls _infer_missing_param_value internally for missing args
    
    # We need to simulate the 'content' param inference
    result = agent._infer_missing_param_value(
        "content", 
        "write_file", 
        current={}, 
        original={}, 
        user_input="dosyayı yaz"
    )
    
    # 3. Assert that it used the prefetched content
    assert result == "Prefetched Content"
    mock_predictor.get_prefetched_content.assert_called_with("write_file")
