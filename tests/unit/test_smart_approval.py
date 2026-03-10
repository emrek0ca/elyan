import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from core.agent import Agent

@pytest.mark.asyncio
async def test_smart_approval_bypass():
    """Test that intervention is bypassed if learning engine gives high confidence."""
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
    agent._current_runtime_policy = lambda: {
        "metadata": {"interactive_approval": True, "channel": "telegram", "user_id": "42"}
    }
    
    # Mock policy to require approval
    with patch("core.agent.tool_policy") as mock_policy:
        mock_policy.check_access.return_value = {"allowed": True, "requires_approval": True}
        
        # Mock learning engine to return auto_approve=True
        agent.learning = MagicMock()
        agent.learning.check_approval_confidence.return_value = {
            "auto_approve": True, 
            "confidence": 1.0, 
            "reason": "Test confidence"
        }
        
        # Mock intervention manager (should NOT be called)
        with patch("core.agent.get_intervention_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_get_mgr.return_value = mock_mgr
            
            await agent._execute_tool("delete_file", {"path": "test.txt"})
            
            # Assert intervention was NOT requested
            mock_mgr.ask_human.assert_not_called()
            
            # Assert primary tool was executed (auxiliary proof tools may also run)
            assert agent.kernel.tools.execute.call_count >= 1
            first_call = agent.kernel.tools.execute.call_args_list[0]
            assert first_call.args[0] == "delete_file"

@pytest.mark.asyncio
async def test_smart_approval_fallback():
    """Test that intervention is shown if learning engine gives low confidence."""
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
    agent._current_runtime_policy = lambda: {
        "metadata": {"interactive_approval": True, "channel": "telegram", "user_id": "42"}
    }
    
    with patch("core.agent.tool_policy") as mock_policy:
        mock_policy.check_access.return_value = {"allowed": True, "requires_approval": True}
        
        agent.learning = MagicMock()
        agent.learning.check_approval_confidence.return_value = {"auto_approve": False}
        agent.learning.record_interaction = AsyncMock()
        
        with patch("core.agent.get_intervention_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.ask_human = AsyncMock(return_value="Onayla")
            mock_get_mgr.return_value = mock_mgr
            
            await agent._execute_tool("delete_file", {"path": "test.txt"})
            
            # Assert intervention WAS requested
            mock_mgr.ask_human.assert_called_once()
