"""
Test Approval System API endpoints.
Tests: approval request creation, resolution, notifications, timeout.
"""

import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock
from core.security.approval_engine import ApprovalEngine, ApprovalRequest
from core.protocol.shared_types import RiskLevel
from api.dashboard_api import DashboardAPIv1


class TestApprovalEngine:
    """Test ApprovalEngine core functionality."""

    def test_approval_request_creation(self):
        """Test creating an approval request."""
        req = ApprovalRequest(
            request_id="appr_test1",
            session_id="sess_123",
            run_id="run_456",
            action_type="execute_shell",
            payload={"cmd": "ls -la"},
            risk_level=RiskLevel.DESTRUCTIVE,
            reason="Executing shell command"
        )
        assert req.request_id == "appr_test1"
        assert req.status == "pending"
        assert req.action_type == "execute_shell"

    def test_approval_request_to_dict(self):
        """Test ApprovalRequest serialization to dict."""
        req = ApprovalRequest(
            request_id="appr_test2",
            session_id="sess_123",
            run_id="run_456",
            action_type="delete_file",
            payload={"path": "/tmp/test"},
            risk_level=RiskLevel.SYSTEM_CRITICAL,
            reason="Deleting file"
        )
        data = req.to_dict()
        assert data["request_id"] == "appr_test2"
        assert data["action_type"] == "delete_file"
        assert "age_seconds" in data
        assert data["risk_level"] == "system_critical"

    @pytest.mark.asyncio
    async def test_request_approval_resolution(self):
        """Test approval request and resolution flow."""
        engine = ApprovalEngine()

        # Create approval task in background
        task = asyncio.create_task(engine.request_approval(
            session_id="sess_123",
            run_id="run_456",
            action_type="execute_shell",
            payload={"cmd": "echo test"},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Test shell execution"
        ))

        # Give task time to set up the future
        await asyncio.sleep(0.05)

        # Get pending approval and resolve it
        pending = engine.get_pending_approvals()
        assert len(pending) >= 1
        req_id = pending[0]["request_id"]

        # Resolve the approval
        engine.resolve_approval(req_id, True, "test_user")

        # Approval task should complete with True
        result = await asyncio.wait_for(task, timeout=1.0)
        assert result is True

    @pytest.mark.asyncio
    async def test_approval_timeout(self):
        """Test approval request timeout."""
        engine = ApprovalEngine()
        # Test that timeout is raised when no resolution is provided
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(
                engine.request_approval(
                    session_id="sess_123",
                    run_id="run_456",
                    action_type="test",
                    payload={},
                    risk_level=RiskLevel.READ_ONLY,
                    reason="Test timeout"
                ),
                timeout=0.5
            )

    def test_get_pending_approvals(self):
        """Test retrieving pending approvals."""
        engine = ApprovalEngine()

        # Add some mock requests
        engine._pending["appr_1"] = ApprovalRequest(
            request_id="appr_1",
            session_id="sess_1",
            run_id="run_1",
            action_type="action_1",
            payload={},
            risk_level=RiskLevel.DESTRUCTIVE,
            reason="Reason 1"
        )
        engine._pending["appr_2"] = ApprovalRequest(
            request_id="appr_2",
            session_id="sess_2",
            run_id="run_2",
            action_type="action_2",
            payload={},
            risk_level=RiskLevel.READ_ONLY,
            reason="Reason 2"
        )

        pending = engine.get_pending_approvals()
        assert len(pending) == 2
        assert pending[0]["request_id"] == "appr_1"
        assert pending[1]["request_id"] == "appr_2"

    def test_resolve_approval_success(self):
        """Test successful approval resolution."""
        engine = ApprovalEngine()
        req = ApprovalRequest(
            request_id="appr_3",
            session_id="sess_3",
            run_id="run_3",
            action_type="action",
            payload={},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Test"
        )
        engine._pending["appr_3"] = req

        success = engine.resolve_approval("appr_3", True, "resolver_1")
        assert success is True
        assert req.status == "approved"

    def test_resolve_approval_denial(self):
        """Test approval denial."""
        engine = ApprovalEngine()
        req = ApprovalRequest(
            request_id="appr_4",
            session_id="sess_4",
            run_id="run_4",
            action_type="action",
            payload={},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Test"
        )
        engine._pending["appr_4"] = req

        success = engine.resolve_approval("appr_4", False, "resolver_2")
        assert success is True
        assert req.status == "denied"

    def test_resolve_nonexistent_approval(self):
        """Test resolving non-existent approval."""
        engine = ApprovalEngine()
        success = engine.resolve_approval("appr_nonexistent", True, "resolver")
        assert success is False


class TestApprovalAPI:
    """Test Approval API endpoints."""

    def test_get_pending_approvals_empty(self):
        """Test getting pending approvals when none exist."""
        api = DashboardAPIv1()

        with patch("core.security.approval_engine.get_approval_engine") as mock_engine:
            mock_engine_instance = MagicMock()
            mock_engine_instance.get_pending_approvals.return_value = []
            mock_engine.return_value = mock_engine_instance

            result = api.get_pending_approvals()
            assert result["success"] is True
            assert result["count"] == 0
            assert result["approvals"] == []

    def test_resolve_approval_endpoint(self):
        """Test resolving approval via API."""
        api = DashboardAPIv1()

        with patch("core.security.approval_engine.get_approval_engine") as mock_engine:
            mock_engine_instance = MagicMock()
            mock_engine_instance.resolve_approval.return_value = True
            mock_engine.return_value = mock_engine_instance

            result = api.resolve_approval("appr_123", True, "web_ui")
            assert result["success"] is True
            mock_engine_instance.resolve_approval.assert_called_once_with(
                "appr_123", True, "web_ui"
            )
