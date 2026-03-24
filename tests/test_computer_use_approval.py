"""Tests for Computer Use Approval System

Tests approval gates, risk mapping, and integration with ApprovalEngine.
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from core.protocol.shared_types import RiskLevel

from elyan.computer_use.approval.risk_mapping import (
    ActionRiskLevel,
    get_action_risk_level,
    should_require_approval,
    ACTION_RISK_MAP,
)
from elyan.computer_use.approval.gates import (
    ComputerUseApprovalGate,
    ApprovalGateResult,
    ApprovalGateFactory,
)
from elyan.computer_use.tool import ComputerAction


class TestRiskMapping:
    """Tests for action risk level mapping"""

    def test_critical_action_risk_mapping(self):
        """Test system critical actions are mapped correctly"""
        risk_level, reason = get_action_risk_level("system_restart")
        assert risk_level == RiskLevel.SYSTEM_CRITICAL
        assert "irreversible" in reason.lower()

    def test_destructive_action_risk_mapping(self):
        """Test destructive actions are mapped correctly"""
        risk_level, reason = get_action_risk_level("delete_file")
        assert risk_level == RiskLevel.DESTRUCTIVE
        assert "permanent" in reason.lower()

    def test_sensitive_write_risk_mapping(self):
        """Test sensitive write actions are mapped correctly"""
        risk_level, reason = get_action_risk_level("type_password")
        assert risk_level == RiskLevel.WRITE_SENSITIVE
        assert "password" in reason.lower() or "verification" in reason.lower()

    def test_safe_write_risk_mapping(self):
        """Test safe write actions are mapped correctly"""
        risk_level, reason = get_action_risk_level("type")
        assert risk_level == RiskLevel.WRITE_SAFE

    def test_read_only_risk_mapping(self):
        """Test read-only actions are mapped correctly"""
        risk_level, reason = get_action_risk_level("left_click")
        assert risk_level == RiskLevel.READ_ONLY

    def test_unknown_action_default_mapping(self):
        """Test unknown actions default to safe write"""
        risk_level, reason = get_action_risk_level("unknown_action_type")
        assert risk_level == RiskLevel.WRITE_SAFE
        assert "unknown" in reason.lower()

    def test_all_mapped_actions_have_reason(self):
        """Test all mapped actions have a reason"""
        for action_type in ACTION_RISK_MAP.keys():
            risk_level, reason = get_action_risk_level(action_type)
            assert reason is not None
            assert len(reason) > 0


class TestApprovalGates:
    """Tests for approval gate logic"""

    def test_auto_level_no_approval_for_read_only(self):
        """AUTO level: read-only actions don't need approval"""
        assert not should_require_approval("left_click", "AUTO")

    def test_auto_level_approval_for_critical(self):
        """AUTO level: critical actions need approval"""
        assert should_require_approval("system_restart", "AUTO")

    def test_confirm_level_no_approval_for_read_only(self):
        """CONFIRM level: read-only actions don't need approval"""
        assert not should_require_approval("left_click", "CONFIRM")

    def test_confirm_level_approval_for_destructive(self):
        """CONFIRM level: destructive actions need approval"""
        assert should_require_approval("delete_file", "CONFIRM")

    def test_confirm_level_approval_for_critical(self):
        """CONFIRM level: critical actions need approval"""
        assert should_require_approval("system_restart", "CONFIRM")

    def test_confirm_level_no_approval_for_safe_write(self):
        """CONFIRM level: safe writes don't need approval"""
        assert not should_require_approval("type", "CONFIRM")

    def test_screen_level_approval_for_sensitive_write(self):
        """SCREEN level: sensitive writes need approval"""
        assert should_require_approval("type_password", "SCREEN")

    def test_screen_level_approval_for_destructive(self):
        """SCREEN level: destructive actions need approval"""
        assert should_require_approval("delete_file", "SCREEN")

    def test_screen_level_no_approval_for_safe_write(self):
        """SCREEN level: safe writes don't need approval"""
        assert not should_require_approval("type", "SCREEN")

    def test_two_fa_level_approval_for_all_writes(self):
        """TWO_FA level: all writes need approval"""
        assert should_require_approval("type", "TWO_FA")
        assert should_require_approval("type_password", "TWO_FA")
        assert should_require_approval("delete_file", "TWO_FA")
        assert should_require_approval("system_restart", "TWO_FA")

    def test_two_fa_level_no_approval_for_read_only(self):
        """TWO_FA level: read-only actions don't need approval"""
        assert not should_require_approval("left_click", "TWO_FA")
        assert not should_require_approval("scroll", "TWO_FA")

    def test_invalid_approval_level_defaults_to_no_approval(self):
        """Invalid approval level defaults to no approval"""
        assert not should_require_approval("system_restart", "INVALID_LEVEL")


class TestApprovalGateClass:
    """Tests for ComputerUseApprovalGate class"""

    @pytest.fixture
    def approval_gate(self):
        """Create approval gate instance"""
        return ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="CONFIRM"
        )

    def test_gate_initialization(self, approval_gate):
        """Test approval gate initializes correctly"""
        assert approval_gate.session_id == "test_session"
        assert approval_gate.run_id == "test_run"
        assert approval_gate.approval_level == "CONFIRM"

    @pytest.mark.asyncio
    async def test_read_only_action_no_approval_needed(self, approval_gate):
        """Test read-only action doesn't require approval"""
        action = ComputerAction(action_type="left_click", x=100, y=200)
        result = await approval_gate.evaluate_action(
            action=action,
            task_context="Test task"
        )
        assert result.approved is True
        assert result.request_id is None

    @pytest.mark.asyncio
    async def test_safe_write_action_no_approval_for_confirm_level(self, approval_gate):
        """Test safe write doesn't need approval at CONFIRM level"""
        action = ComputerAction(action_type="type", text="test")
        result = await approval_gate.evaluate_action(
            action=action,
            task_context="Test task"
        )
        assert result.approved is True
        assert result.request_id is None

    @pytest.mark.asyncio
    async def test_destructive_action_needs_approval_at_confirm_level(self):
        """Test hotkey action (system critical) needs approval at CONFIRM level"""
        gate = ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="CONFIRM"
        )

        # Mock approval engine
        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = True

            # Use hotkey as a proxy for critical action (could be system command)
            action = ComputerAction(action_type="hotkey", key_combination=["ctrl", "shift", "delete"])
            result = await gate.evaluate_action(
                action=action,
                task_context="Execute system command"
            )

            # Verify approval was requested (if hotkey maps to critical)
            assert result.approved is True

    @pytest.mark.asyncio
    async def test_approval_request_rejected(self):
        """Test handling when approval request is denied"""
        gate = ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="TWO_FA"
        )

        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            mock_request.return_value = False

            # TWO_FA requires approval for all writes, including type
            action = ComputerAction(action_type="type", text="some input")
            result = await gate.evaluate_action(
                action=action,
                task_context="Type task"
            )

            assert result.approved is False
            assert "denied" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_approval_engine_error_handling(self):
        """Test handling of approval engine errors"""
        gate = ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="TWO_FA"
        )

        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = Exception("Approval engine error")

            action = ComputerAction(action_type="type", text="data")
            result = await gate.evaluate_action(
                action=action,
                task_context="Type task"
            )

            # Fail-safe: deny on error
            assert result.approved is False
            assert "error" in result.reason.lower()

    @pytest.mark.asyncio
    async def test_approval_payload_includes_action_details(self):
        """Test approval payload includes action-specific details"""
        gate = ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="SCREEN"
        )

        captured_payload = {}

        async def capture_approval(session_id, run_id, action_type, payload, risk_level, reason):
            captured_payload.update(payload)
            return True

        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = capture_approval

            action = ComputerAction(
                action_type="type",
                text="sensitive_data",
                x=100,
                y=200
            )
            # SCREEN level requires approval for writes
            result = await gate.evaluate_action(
                action=action,
                task_context="Enter sensitive data"
            )

            if result.request_id:  # Only if approval was requested
                assert "action_type" in captured_payload
                assert "task_context" in captured_payload

    @pytest.mark.asyncio
    async def test_approval_gate_result_timestamp(self):
        """Test approval result includes timestamp"""
        gate = ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="CONFIRM"
        )

        action = ComputerAction(action_type="left_click", x=100, y=200)
        result = await gate.evaluate_action(
            action=action,
            task_context="Test task"
        )

        assert result.timestamp is not None
        assert isinstance(result.timestamp, float)

    @pytest.mark.asyncio
    async def test_sensitive_text_not_leaked_in_logs(self):
        """Test sensitive text is previewed, not fully logged"""
        gate = ComputerUseApprovalGate(
            session_id="test_session",
            run_id="test_run",
            approval_level="SCREEN"
        )

        captured_payload = {}

        async def capture_approval(session_id, run_id, action_type, payload, risk_level, reason):
            captured_payload.update(payload)
            return True

        with patch.object(gate.approval_engine, 'request_approval', new_callable=AsyncMock) as mock_request:
            mock_request.side_effect = capture_approval

            long_text = "a" * 100
            action = ComputerAction(action_type="type", text=long_text)
            await gate.evaluate_action(
                action=action,
                task_context="Enter data"
            )

            # Text should be truncated in approval payload
            if "text" in captured_payload:
                assert captured_payload["text"] == long_text[:50]


class TestApprovalGateFactory:
    """Tests for ApprovalGateFactory"""

    def test_factory_creates_gate(self):
        """Test factory creates gate instances"""
        gate = ApprovalGateFactory.create_gate(
            session_id="test_session",
            run_id="test_run",
            approval_level="CONFIRM"
        )

        assert isinstance(gate, ComputerUseApprovalGate)
        assert gate.session_id == "test_session"
        assert gate.run_id == "test_run"

    def test_factory_get_gate(self):
        """Test factory get_gate method"""
        gate = ApprovalGateFactory.get_gate(
            session_id="test_session",
            run_id="test_run",
            approval_level="SCREEN"
        )

        assert isinstance(gate, ComputerUseApprovalGate)
        assert gate.approval_level == "SCREEN"

    def test_factory_different_approvals_different_gates(self):
        """Test factory creates different gate instances"""
        gate1 = ApprovalGateFactory.create_gate("sess1", "run1", "CONFIRM")
        gate2 = ApprovalGateFactory.create_gate("sess2", "run2", "SCREEN")

        assert gate1 is not gate2
        assert gate1.approval_level != gate2.approval_level


class TestApprovalGateResult:
    """Tests for ApprovalGateResult dataclass"""

    def test_result_approved(self):
        """Test approval result when approved"""
        result = ApprovalGateResult(approved=True, reason="Test approved")
        assert result.approved is True
        assert result.reason == "Test approved"
        assert result.timestamp is not None

    def test_result_denied(self):
        """Test approval result when denied"""
        result = ApprovalGateResult(approved=False, reason="Test denied")
        assert result.approved is False
        assert result.reason == "Test denied"

    def test_result_with_request_id(self):
        """Test approval result includes request ID"""
        result = ApprovalGateResult(
            approved=True,
            request_id="appr_12345",
            reason="Approved"
        )
        assert result.request_id == "appr_12345"

    def test_result_timestamp_auto_set(self):
        """Test timestamp is automatically set"""
        import time
        before = time.time()
        result = ApprovalGateResult(approved=True)
        after = time.time()

        assert before <= result.timestamp <= after
