
import pytest
from core.self_healing import get_healing_engine

def test_diagnose_permission_error():
    engine = get_healing_engine()
    error = "OSError: [Errno 13] Permission denied: '/root/test.txt'"
    strategy = engine.diagnose(error)
    assert strategy is not None
    assert strategy.name == "permission_denied"

def test_diagnose_module_error():
    engine = get_healing_engine()
    error = "ModuleNotFoundError: No module named 'pandas'"
    strategy = engine.diagnose(error)
    assert strategy is not None
    assert strategy.name == "module_not_found"

@pytest.mark.asyncio
async def test_healing_plan_permission():
    engine = get_healing_engine()
    strategy = engine.diagnose("Permission denied")
    ctx = {
        "tool_name": "write_file",
        "params": {"path": "/restricted/file.txt", "content": "hello"}
    }
    plan = await engine.get_healing_plan(strategy, "Permission denied", ctx)
    assert plan["can_auto_fix"] is True
    assert "Desktop" in plan["suggested_params"]["path"]
    assert plan["action_type"] == "suggest_home_path"

@pytest.mark.asyncio
async def test_healing_plan_module():
    engine = get_healing_engine()
    error = "ModuleNotFoundError: No module named 'python-docx'"
    strategy = engine.diagnose(error)
    ctx = {"tool_name": "write_word", "params": {}}
    plan = await engine.get_healing_plan(strategy, error, ctx)
    assert plan["can_auto_fix"] is True
    assert "pip install" in plan["fix_command"]
