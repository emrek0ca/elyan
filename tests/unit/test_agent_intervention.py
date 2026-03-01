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
            with patch.object(
                agent,
                "_current_runtime_policy",
                return_value={"metadata": {"user_id": "42", "channel": "telegram", "interactive_approval": True}},
            ):
            
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
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})
    
    with patch("core.agent.tool_policy") as mock_policy:
        mock_policy.check_access.return_value = {"allowed": True, "requires_approval": True}
        
        with patch("core.agent.get_intervention_manager") as mock_get_mgr:
            mock_mgr = MagicMock()
            mock_mgr.ask_human = AsyncMock(return_value="İptal Et")
            mock_get_mgr.return_value = mock_mgr
            with patch.object(
                agent,
                "_current_runtime_policy",
                return_value={"metadata": {"user_id": "42", "channel": "telegram", "interactive_approval": True}},
            ):
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


@pytest.mark.asyncio
async def test_agent_intervention_uses_runtime_metadata_user_id_when_current_user_missing():
    """If current_user_id is not set, approval context should use runtime metadata user_id."""
    agent = Agent()
    agent.current_user_id = None
    agent.kernel = MagicMock()
    agent.kernel.tools.execute = AsyncMock(return_value={"success": True})

    with patch("core.agent.runtime_security_guard.evaluate") as mock_guard_eval:
        mock_guard_eval.return_value = {
            "allowed": True,
            "requires_approval": True,
            "reason": "approval_required",
            "risk": "dangerous",
        }
        with patch("core.agent.tool_policy") as mock_policy:
            mock_policy.check_access.return_value = {
                "allowed": True,
                "requires_approval": False,
                "reason": "ok",
            }
            with patch.object(
                agent,
                "_current_runtime_policy",
                return_value={"metadata": {"user_id": "4242", "channel": "telegram", "interactive_approval": True}},
            ):
                with patch("core.agent.AVAILABLE_TOOLS", {"close_app": AsyncMock(return_value={"success": True})}):
                    with patch("core.agent.get_intervention_manager") as mock_get_mgr:
                        mock_mgr = MagicMock()
                        mock_mgr.ask_human = AsyncMock(return_value="Onayla")
                        mock_get_mgr.return_value = mock_mgr
                        if getattr(agent, "learning", None) and hasattr(agent.learning, "check_approval_confidence"):
                            agent.learning.check_approval_confidence = MagicMock(return_value={"auto_approve": False})

                        result = await agent._execute_tool(
                            "close_app",
                            {"app_name": "Terminal"},
                            user_input="terminali kapat",
                        )

                        assert result.get("success") is True
                        assert mock_mgr.ask_human.call_count == 1
                        _, kwargs = mock_mgr.ask_human.call_args
                        assert kwargs["context"]["user_id"] == "4242"
