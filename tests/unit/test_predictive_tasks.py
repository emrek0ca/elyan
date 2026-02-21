
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
    
    # Should run without error
    await engine.prefetch_dependencies(preds)
