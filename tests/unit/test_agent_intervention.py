import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from core.agent import Agent

@pytest.mark.asyncio
async def test_agent_intervention_trigger():
    """Test that risky tools trigger intervention manager."""
    agent = Agent()
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
    
    # Mock tool_policy to require approval for "delete_file"
    with patch("core.agent.tool_policy") as mock_policy:
        mock_policy.check_access.return_value = {
            "allowed": True, 
            "requires_approval": True, 
            "reason": "Policy says so"
        }
        
        # Mock intervention manager
        with patch("core.agent.get_intervention_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.ask_human = AsyncMock(return_value="Onayla")
            mock_get_mgr.return_value = mock_mgr
            
            # Execute
            await agent._execute_tool("delete_file", {"path": "test.txt"})
            
            # Verify intervention was requested
            mock_mgr.ask_human.assert_called_once()
            args, kwargs = mock_mgr.ask_human.call_args
            assert "Kritik işlem onayı gerekiyor" in kwargs["prompt"]

@pytest.mark.asyncio
async def test_agent_intervention_cancel():
    """Test that user cancellation aborts tool execution."""
    agent = Agent()
    agent.kernel = MagicMock()
    
    with patch("core.agent.tool_policy") as mock_policy:
        mock_policy.check_access.return_value = {"allowed": True, "requires_approval": True}
        
        with patch("core.agent.get_intervention_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.ask_human = AsyncMock(return_value="İptal Et")
            mock_get_mgr.return_value = mock_mgr
            
            result = await agent._execute_tool("delete_file", {"path": "test.txt"})
            
            assert result["success"] is False
            assert result["error_code"] == "USER_ABORTED"
            # Kernel execute should NOT be called
            agent.kernel.tools.execute.assert_not_called()

@pytest.mark.asyncio
async def test_write_retry_on_verification_failure():
    """Test that write operations retry once if verification fails."""
    agent = Agent()
    agent.kernel = MagicMock()
    
    # First call returns success=True but verification fails (simulated via side_effect or return values)
    # Verification happens in _postprocess_tool_result. We need to mock that too or let it run.
    # To let it run, we need FS. It's easier to mock _postprocess_tool_result to return verified=False first, then True.
    
    with patch.object(agent, "_postprocess_tool_result") as mock_post:
        # First call: verified=False. Second call: verified=True
        mock_post.side_effect = [
            {"verified": False, "success": True}, 
            {"verified": True, "success": True}
        ]
        
        # Kernel execute called twice
        agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
        
        # Mock policy to allow
        with patch("core.agent.tool_policy") as mock_policy:
            mock_policy.check_access.return_value = {"allowed": True, "requires_approval": False}
            
            await agent._execute_tool("write_file", {"path": "test.txt", "content": "content"})
            
            # Should have called execute twice
            assert agent.kernel.tools.execute.call_count == 2
