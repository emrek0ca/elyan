
import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from core.predictive_tasks import PredictiveTaskEngine, TaskPrediction, PredictionConfidence
from core.intelligent_planner import SubTask

@pytest.mark.asyncio
async def test_heuristic_prediction_research():
    engine = PredictiveTaskEngine()
    
    step = SubTask(
        task_id="t1",
        name="Research AI",
        action="advanced_research",
        params={"topic": "AI Agents"},
        dependencies=[]
    )
    
    preds = await engine.predict_next_steps(step)
    
    assert len(preds) >= 1
    assert any(p.action == "write_file" for p in preds)
    assert any(p.confidence == PredictionConfidence.HIGH for p in preds)

@pytest.mark.asyncio
async def test_heuristic_prediction_scaffold():
    engine = PredictiveTaskEngine()
    
    step = SubTask(
        task_id="t2",
        name="Scaffold Web",
        action="create_web_project_scaffold",
        params={"output_dir": "~/Projects/test"},
        dependencies=[]
    )
    
    preds = await engine.predict_next_steps(step)
    
    assert len(preds) >= 1
    ide_pred = next((p for p in preds if p.action == "open_project_in_ide"), None)
    assert ide_pred is not None
    assert ide_pred.params.get("project_path") == "~/Projects/test"

@pytest.mark.asyncio
async def test_prefetch_execution():
    engine = PredictiveTaskEngine()
    # Mocking logger to verify it doesn't crash
    
    preds = [
        TaskPrediction(
            action="write_file",
            params={"path": "test.md"},
            confidence=PredictionConfidence.HIGH,
            reasoning="Testing"
        )
    ]
    
@pytest.mark.asyncio
async def test_llm_prediction_fallback():
    mock_llm = MagicMock()
    mock_llm.generate = AsyncMock(return_value='{"action": "send_message", "params": {"message": "done"}, "confidence": "MEDIUM"}')
    
    engine = PredictiveTaskEngine(llm_client=mock_llm)
    
    step = SubTask(
        task_id="t3",
        name="Unknown Action",
        action="unknown_tool",
        params={},
        dependencies=[]
    )
    
    # Heuristics should fail for "unknown_tool", triggering LLM
    preds = await engine.predict_next_steps(step)
    
    assert len(preds) > 0
    assert preds[0].action == "send_message"
    assert preds[0].confidence == PredictionConfidence.MEDIUM
    mock_llm.generate.assert_called_once()
