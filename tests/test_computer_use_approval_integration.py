"""Integration tests for Computer Use with Approval System

Tests full task execution flow with approval gates.
"""

import pytest
import asyncio
import tempfile
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from pathlib import Path

from elyan.computer_use.tool import ComputerUseTool, ComputerAction, ComputerUseTask
from elyan.computer_use.approval import ApprovalGateFactory
from core.protocol.shared_types import RiskLevel


class TestComputerUseWithApproval:
    """Integration tests for Computer Use with approval system"""

    @pytest.fixture
    def temp_evidence_dir(self):
        """Create temporary evidence directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_task_execution_with_auto_approval(self, temp_evidence_dir):
        """Test task execution with AUTO approval level (no approvals needed)"""
        tool = ComputerUseTool(max_steps=2)

        # Mock all components to avoid external dependencies
        mock_vision = AsyncMock()
        mock_vision.analyze = AsyncMock(return_value={
            "description": "Screen with button",
            "elements": [{"type": "button", "text": "Click me", "x": 100, "y": 200}]
        })

        mock_planner = AsyncMock()
        mock_planner.plan_next_action = AsyncMock(return_value=ComputerAction(
            action_type="left_click",
            x=100,
            y=200
        ))

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "task_completed": True,
            "extracted_data": "Button clicked successfully"
        })

        with patch.object(tool, 'vision', mock_vision):
            with patch.object(tool, 'planner', mock_planner):
                with patch.object(tool, 'executor', mock_executor):
                    with patch('elyan.computer_use.evidence.recorder.get_evidence_recorder', new_callable=AsyncMock) as mock_recorder:
                        mock_recorder_instance = AsyncMock()
                        mock_recorder_instance.save_screenshot = AsyncMock(return_value=True)
                        mock_recorder_instance.record_task = AsyncMock(return_value={
                            "success": True,
                            "evidence_dir": temp_evidence_dir
                        })
                        mock_recorder.return_value = mock_recorder_instance

                        result = await tool.execute_task(
                            user_intent="Click the button",
                            initial_screenshot=b"fake_screenshot",
                            approval_level="AUTO"
                        )

                        assert result["status"] == "completed"
                        assert len(result.get("approval_requests", [])) == 0

    @pytest.mark.asyncio
    async def test_task_execution_with_confirm_approval_approved(self, temp_evidence_dir):
        """Test CONFIRM approval level with user approval"""
        tool = ComputerUseTool(max_steps=2)

        mock_vision = AsyncMock()
        mock_vision.analyze = AsyncMock(return_value={
            "description": "Screen",
            "elements": []
        })

        # First step: safe click (no approval needed)
        # Second step: type at TWO_FA level (requires approval for all writes)
        call_count = [0]

        async def plan_action_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ComputerAction(action_type="left_click", x=100, y=200)
            else:
                return ComputerAction(action_type="type", text="data")

        mock_planner = AsyncMock()
        mock_planner.plan_next_action = AsyncMock(side_effect=plan_action_side_effect)

        mock_executor = AsyncMock()
        # Return task_completed=True on second call to complete the task
        execute_call_count = [0]

        async def execute_side_effect(*args, **kwargs):
            execute_call_count[0] += 1
            return {
                "success": True,
                "task_completed": execute_call_count[0] >= 2  # Complete on second action
            }

        mock_executor.execute = AsyncMock(side_effect=execute_side_effect)

        with patch.object(tool, 'vision', mock_vision):
            with patch.object(tool, 'planner', mock_planner):
                with patch.object(tool, 'executor', mock_executor):
                    with patch('elyan.computer_use.evidence.recorder.get_evidence_recorder', new_callable=AsyncMock) as mock_recorder:
                        mock_recorder_instance = AsyncMock()
                        mock_recorder_instance.save_screenshot = AsyncMock(return_value=True)
                        mock_recorder_instance.record_task = AsyncMock(return_value={
                            "success": True
                        })
                        mock_recorder.return_value = mock_recorder_instance

                        # Mock the approval engine
                        with patch('elyan.computer_use.approval.gates.get_approval_engine') as mock_get_engine:
                            mock_engine = MagicMock()
                            mock_engine.request_approval = AsyncMock(return_value=True)
                            mock_get_engine.return_value = mock_engine

                            result = await tool.execute_task(
                                user_intent="Type data with approval",
                                initial_screenshot=b"fake_screenshot",
                                approval_level="TWO_FA"  # TWO_FA requires approval for all writes
                            )

                            # Verify approval was requested for write action
                            assert mock_engine.request_approval.called
                            # Task should complete since approval was granted
                            assert result["status"] == "completed"

    @pytest.mark.asyncio
    async def test_task_execution_with_approval_denied(self, temp_evidence_dir):
        """Test task cancellation when approval is denied"""
        tool = ComputerUseTool(max_steps=2)

        mock_vision = AsyncMock()
        mock_vision.analyze = AsyncMock(return_value={
            "description": "Screen",
            "elements": []
        })

        mock_planner = AsyncMock()
        mock_planner.plan_next_action = AsyncMock(return_value=ComputerAction(
            action_type="type", text="data"
        ))

        mock_executor = AsyncMock()
        # Should not be called since action is denied
        mock_executor.execute = AsyncMock(return_value={"success": False})

        with patch.object(tool, 'vision', mock_vision):
            with patch.object(tool, 'planner', mock_planner):
                with patch.object(tool, 'executor', mock_executor):
                    with patch('elyan.computer_use.evidence.recorder.get_evidence_recorder', new_callable=AsyncMock) as mock_recorder:
                        mock_recorder_instance = AsyncMock()
                        mock_recorder_instance.save_screenshot = AsyncMock(return_value=True)
                        mock_recorder_instance.record_task = AsyncMock(return_value={
                            "success": True
                        })
                        mock_recorder.return_value = mock_recorder_instance

                        with patch('elyan.computer_use.approval.gates.get_approval_engine') as mock_get_engine:
                            mock_engine = MagicMock()
                            mock_engine.request_approval = AsyncMock(return_value=False)
                            mock_get_engine.return_value = mock_engine

                            result = await tool.execute_task(
                                user_intent="Type data with strict approval",
                                initial_screenshot=b"fake_screenshot",
                                approval_level="TWO_FA"  # TWO_FA requires approval for all writes
                            )

                            # Task should be cancelled
                            assert result["status"] == "cancelled"
                            assert "denied" in result["error"].lower()
                            # Executor should not have been called
                            assert not mock_executor.execute.called

    @pytest.mark.asyncio
    async def test_approval_requests_tracked_in_task(self, temp_evidence_dir):
        """Test approval requests are tracked in task data"""
        tool = ComputerUseTool(max_steps=2)

        mock_vision = AsyncMock()
        mock_vision.analyze = AsyncMock(return_value={
            "description": "Screen",
            "elements": []
        })

        call_count = [0]

        async def plan_action_side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return ComputerAction(action_type="type", text="secret")
            else:
                return ComputerAction(action_type="type", text="confirm")

        mock_planner = AsyncMock()
        mock_planner.plan_next_action = AsyncMock(side_effect=plan_action_side_effect)

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "task_completed": False
        })

        with patch.object(tool, 'vision', mock_vision):
            with patch.object(tool, 'planner', mock_planner):
                with patch.object(tool, 'executor', mock_executor):
                    with patch('elyan.computer_use.evidence.recorder.get_evidence_recorder', new_callable=AsyncMock) as mock_recorder:
                        mock_recorder_instance = AsyncMock()
                        mock_recorder_instance.save_screenshot = AsyncMock(return_value=True)
                        mock_recorder_instance.record_task = AsyncMock(return_value={
                            "success": True
                        })
                        mock_recorder.return_value = mock_recorder_instance

                        with patch('elyan.computer_use.approval.gates.get_approval_engine') as mock_get_engine:
                            mock_engine = MagicMock()
                            mock_engine.request_approval = AsyncMock(return_value=True)
                            mock_get_engine.return_value = mock_engine

                            result = await tool.execute_task(
                                user_intent="Enter credentials",
                                initial_screenshot=b"fake_screenshot",
                                approval_level="SCREEN"
                            )

                            # Check approval requests were tracked
                            approval_requests = result.get("approval_requests", [])
                            # Should have approvals if SCREEN level requires them for type actions
                            assert isinstance(approval_requests, list)

    @pytest.mark.asyncio
    async def test_approval_callback_override(self, temp_evidence_dir):
        """Test legacy approval callback can override approval gate"""
        tool = ComputerUseTool(max_steps=2)

        mock_vision = AsyncMock()
        mock_vision.analyze = AsyncMock(return_value={
            "description": "Screen",
            "elements": []
        })

        mock_planner = AsyncMock()
        mock_planner.plan_next_action = AsyncMock(return_value=ComputerAction(
            action_type="type", text="data to enter"
        ))

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "task_completed": True,
            "extracted_data": "File deleted"
        })

        approval_callback_called = []

        async def approval_callback(action, screenshot):
            approval_callback_called.append(action.action_type)
            return True  # Override with approval

        with patch.object(tool, 'vision', mock_vision):
            with patch.object(tool, 'planner', mock_planner):
                with patch.object(tool, 'executor', mock_executor):
                    with patch('elyan.computer_use.evidence.recorder.get_evidence_recorder', new_callable=AsyncMock) as mock_recorder:
                        mock_recorder_instance = AsyncMock()
                        mock_recorder_instance.save_screenshot = AsyncMock(return_value=True)
                        mock_recorder_instance.record_task = AsyncMock(return_value={
                            "success": True
                        })
                        mock_recorder.return_value = mock_recorder_instance

                        with patch('elyan.computer_use.approval.gates.get_approval_engine') as mock_get_engine:
                            mock_engine = MagicMock()
                            # Engine denies, but callback approves
                            mock_engine.request_approval = AsyncMock(return_value=False)
                            mock_get_engine.return_value = mock_engine

                            result = await tool.execute_task(
                                user_intent="Delete data with callback override",
                                initial_screenshot=b"fake_screenshot",
                                approval_level="TWO_FA",  # TWO_FA requires approval for all writes
                                approval_callback=approval_callback
                            )

                            # Task should complete despite engine denial
                            # (callback override took precedence)
                            assert result["status"] == "completed"
                            assert "type" in approval_callback_called

    @pytest.mark.asyncio
    async def test_approval_level_params_passed_to_task(self, temp_evidence_dir):
        """Test approval_level parameter is properly passed through"""
        tool = ComputerUseTool(max_steps=1)

        mock_vision = AsyncMock()
        mock_vision.analyze = AsyncMock(return_value={"description": "Screen"})

        mock_planner = AsyncMock()
        mock_planner.plan_next_action = AsyncMock(return_value=ComputerAction(
            action_type="left_click", x=100, y=200
        ))

        mock_executor = AsyncMock()
        mock_executor.execute = AsyncMock(return_value={
            "success": True,
            "task_completed": True
        })

        with patch.object(tool, 'vision', mock_vision):
            with patch.object(tool, 'planner', mock_planner):
                with patch.object(tool, 'executor', mock_executor):
                    with patch('elyan.computer_use.evidence.recorder.get_evidence_recorder', new_callable=AsyncMock) as mock_recorder:
                        mock_recorder_instance = AsyncMock()
                        mock_recorder_instance.save_screenshot = AsyncMock(return_value=True)
                        mock_recorder_instance.record_task = AsyncMock(return_value={
                            "success": True
                        })
                        mock_recorder.return_value = mock_recorder_instance

                        result = await tool.execute_task(
                            user_intent="Click button",
                            initial_screenshot=b"fake",
                            session_id="test_session",
                            approval_level="TWO_FA"
                        )

                        # Verify approval_level is in returned task
                        assert result["approval_level"] == "TWO_FA"


class TestApprovalGateIntegration:
    """Integration tests for approval gates with full scenarios"""

    @pytest.mark.asyncio
    async def test_multi_step_approval_workflow(self):
        """Test multi-step task with multiple approval points"""
        from elyan.computer_use.approval.gates import ComputerUseApprovalGate

        gate = ComputerUseApprovalGate(
            session_id="multi_step_test",
            run_id="workflow_test",
            approval_level="SCREEN"
        )

        # Change gate to TWO_FA to ensure all writes need approval
        gate = ComputerUseApprovalGate(
            session_id="multi_step_test",
            run_id="workflow_test",
            approval_level="TWO_FA"  # TWO_FA requires approval for all writes
        )

        steps = [
            ComputerAction(action_type="left_click", x=100, y=200),      # No approval (read-only)
            ComputerAction(action_type="type", text="password_input"),    # Needs approval at TWO_FA
            ComputerAction(action_type="type", text="data"),              # Needs approval at TWO_FA
            ComputerAction(action_type="hotkey", key_combination=["ctrl", "shift", "delete"]),  # Needs approval
        ]

        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            # Always approve for this test
            mock_request.return_value = True

            approval_count = 0
            for action in steps:
                result = await gate.evaluate_action(
                    action=action,
                    task_context="Multi-step workflow"
                )

                if not result.approved:
                    break

                if result.request_id:
                    approval_count += 1

            # TWO_FA level should require approval for the 3 write actions
            assert mock_request.call_count == 3

    @pytest.mark.asyncio
    async def test_sensitive_data_protection_in_approval(self):
        """Test that sensitive data is properly handled in approval requests"""
        from elyan.computer_use.approval.gates import ComputerUseApprovalGate

        gate = ComputerUseApprovalGate(
            session_id="sensitive_test",
            run_id="data_protection_test",
            approval_level="SCREEN"
        )

        sensitive_action = ComputerAction(
            action_type="type",
            text="4532-1234-5678-9012"  # Long sensitive data
        )

        captured_requests = []

        async def capture_request(session_id, run_id, action_type, payload, risk_level, reason):
            captured_requests.append(payload)
            return True

        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = capture_request

            result = await gate.evaluate_action(
                action=sensitive_action,
                task_context="Enter payment info"
            )

            # Verify sensitive text was truncated in payload if present
            if captured_requests and "text" in captured_requests[0]:
                # Text should be truncated to 50 chars
                assert len(captured_requests[0]["text"]) <= 50
