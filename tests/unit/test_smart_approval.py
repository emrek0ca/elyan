import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from core.agent import Agent

@pytest.mark.asyncio
async def test_smart_approval_bypass():
    """Test that intervention is bypassed if learning engine gives high confidence."""
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
    
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
            
            # Assert tool WAS executed
            agent.kernel.tools.execute.assert_called_once()

@pytest.mark.asyncio
async def test_smart_approval_fallback():
    """Test that intervention is shown if learning engine gives low confidence."""
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
    
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
