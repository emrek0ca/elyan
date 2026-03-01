import pytest
import asyncio
from pathlib import Path
from core.delivery.engine import DeliveryEngine
from core.delivery.state_machine import DeliveryState
from core.pipeline import pipeline_runner, PipelineContext

@pytest.mark.asyncio
async def test_delivery_state_machine_flow():
    engine = DeliveryEngine()
    project_name = f"test_proj_{int(asyncio.get_event_loop().time())}"
    
    # Test project creation
    res = await engine.create_project(project_name, "python_cli", {"welcome_msg": "Test!"})
    assert res["success"] is True
    assert "path" in res
    
    # Check if files exist
    project_path = Path(res["path"])
    assert (project_path / "main.py").exists()
    assert (project_path / "requirements.txt").exists()

@pytest.mark.asyncio
async def test_pipeline_routing():
    from core.agent import Agent
    agent = Agent()
    
    # Mocking complexity for reasoning trigger
    ctx = PipelineContext(user_input="Bana çok karmaşık bir Python scripti yaz ve bunu analiz et.", user_id="test_user")
    
    # Run route stage
    from core.pipeline import StageRoute
    router = StageRoute()
    ctx = await router.run(ctx, agent)
    
    assert ctx.is_code_job is True
    # Complexity should be detected as low initially but our route logic sets it high for certain keywords
    # Actually complexity is set by intent parser, if it's 0 it might not trigger.
    # But StageRoute marks is_code_job.
    
@pytest.mark.asyncio
async def test_cdg_dynamic_planning():
    from core.cdg_engine import cdg_engine
    from unittest.mock import AsyncMock
    
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"nodes": [{"id": "n1", "name": "Task 1", "action": "write_file", "params": {"path": "test.txt", "content": "hello"}}]}'
    
    job_id = "test_job_123"
    # Dynamic plan building
    plan = await cdg_engine.create_plan(job_id, "code_project", "Create a simple calculator", llm_client=mock_llm)
    assert len(plan.nodes) > 0
    # Check if QA gates were auto-injected
    assert len(plan.node_qa_gates) > 0
