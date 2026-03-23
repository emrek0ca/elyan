"""
Test Enhanced Approval Workflow

Tests for priority-based approval system, bulk operations, and workflow metrics.
"""

import pytest
from core.security.approval_engine import ApprovalEngine, ApprovalRequest
from core.protocol.shared_types import RiskLevel


class TestApprovalPriority:
    """Test approval request priority calculation."""

    def test_priority_calculation_system_critical(self):
        """Test highest priority for system critical requests."""
        req = ApprovalRequest(
            request_id="appr_test1",
            session_id="sess_123",
            run_id="run_456",
            action_type="system_restart",
            payload={},
            risk_level=RiskLevel.SYSTEM_CRITICAL,
            reason="System restart"
        )
        assert req.priority == 1  # Highest priority

    def test_priority_calculation_destructive(self):
        """Test priority for destructive requests."""
        req = ApprovalRequest(
            request_id="appr_test2",
            session_id="sess_123",
            run_id="run_456",
            action_type="delete_all",
            payload={},
            risk_level=RiskLevel.DESTRUCTIVE,
            reason="Delete all data"
        )
        assert req.priority == 2

    def test_priority_calculation_write_sensitive(self):
        """Test priority for write sensitive requests."""
        req = ApprovalRequest(
            request_id="appr_test3",
            session_id="sess_123",
            run_id="run_456",
            action_type="modify_config",
            payload={},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Modify configuration"
        )
        assert req.priority == 3

    def test_priority_calculation_read_only(self):
        """Test lowest priority for read-only requests."""
        req = ApprovalRequest(
            request_id="appr_test4",
            session_id="sess_123",
            run_id="run_456",
            action_type="read_log",
            payload={},
            risk_level=RiskLevel.READ_ONLY,
            reason="Read log"
        )
        assert req.priority == 5  # Lowest priority

    def test_priority_in_to_dict(self):
        """Test that priority is included in serialization."""
        req = ApprovalRequest(
            request_id="appr_test5",
            session_id="sess_123",
            run_id="run_456",
            action_type="test",
            payload={},
            risk_level=RiskLevel.DESTRUCTIVE,
            reason="Test"
        )
        data = req.to_dict()
        assert "priority" in data
        assert data["priority"] == 2


class TestPrioritySorting:
    """Test sorting of approval requests by priority."""

    def test_get_pending_approvals_sorted_by_priority(self):
        """Test that pending approvals are sorted by priority."""
        engine = ApprovalEngine()

        # Add requests in reverse priority order
        reqs_data = [
            (RiskLevel.READ_ONLY, "read1"),
            (RiskLevel.SYSTEM_CRITICAL, "critical1"),
            (RiskLevel.WRITE_SENSITIVE, "write1"),
            (RiskLevel.DESTRUCTIVE, "destruct1"),
        ]

        for risk, action in reqs_data:
            engine._pending[f"appr_{action}"] = ApprovalRequest(
                request_id=f"appr_{action}",
                session_id="sess_123",
                run_id="run_456",
                action_type=action,
                payload={},
                risk_level=risk,
                reason="Test"
            )

        # Get sorted pending approvals
        pending = engine.get_pending_approvals(sorted_by_priority=True)

        # Verify they are sorted by priority (lowest priority number first)
        assert len(pending) == 4
        assert pending[0]["priority"] == 1  # Critical
        assert pending[1]["priority"] == 2  # Destructive
        assert pending[2]["priority"] == 3  # Write sensitive
        assert pending[3]["priority"] == 5  # Read only

    def test_get_pending_approvals_not_sorted(self):
        """Test getting unsorted pending approvals."""
        engine = ApprovalEngine()

        for i in range(3):
            engine._pending[f"appr_test{i}"] = ApprovalRequest(
                request_id=f"appr_test{i}",
                session_id="sess_123",
                run_id="run_456",
                action_type=f"action{i}",
                payload={},
                risk_level=RiskLevel.WRITE_SENSITIVE,
                reason="Test"
            )

        # Get unsorted pending approvals
        pending = engine.get_pending_approvals(sorted_by_priority=False)
        assert len(pending) == 3


class TestBulkResolve:
    """Test bulk approval operations."""

    def test_bulk_resolve_approve_all(self):
        """Test bulk approving multiple requests."""
        engine = ApprovalEngine()

        # Create multiple requests
        request_ids = []
        for i in range(3):
            req_id = f"appr_bulk_{i}"
            request_ids.append(req_id)
            engine._pending[req_id] = ApprovalRequest(
                request_id=req_id,
                session_id="sess_123",
                run_id="run_456",
                action_type=f"action{i}",
                payload={},
                risk_level=RiskLevel.WRITE_SENSITIVE,
                reason="Test"
            )

        # Bulk resolve as approved
        results = engine.bulk_resolve(request_ids, approved=True, resolver_id="bulk_user")

        assert results["success"] == 3
        assert results["failure"] == 0
        assert len(results["resolved_ids"]) == 3
        assert len(results["failed_ids"]) == 0
        assert len(engine._pending) == 0  # All should be resolved

    def test_bulk_resolve_deny_all(self):
        """Test bulk denying multiple requests."""
        engine = ApprovalEngine()

        # Create multiple requests
        request_ids = []
        for i in range(3):
            req_id = f"appr_bulk_{i}"
            request_ids.append(req_id)
            engine._pending[req_id] = ApprovalRequest(
                request_id=req_id,
                session_id="sess_123",
                run_id="run_456",
                action_type=f"action{i}",
                payload={},
                risk_level=RiskLevel.DESTRUCTIVE,
                reason="Test"
            )

        # Bulk resolve as denied
        results = engine.bulk_resolve(request_ids, approved=False, resolver_id="bulk_user")

        assert results["success"] == 3
        assert results["failure"] == 0
        assert len(engine._pending) == 0

    def test_bulk_resolve_partial_failure(self):
        """Test bulk resolve with some non-existent requests."""
        engine = ApprovalEngine()

        # Create only 2 requests
        engine._pending["appr_1"] = ApprovalRequest(
            request_id="appr_1",
            session_id="sess_123",
            run_id="run_456",
            action_type="action1",
            payload={},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Test"
        )
        engine._pending["appr_2"] = ApprovalRequest(
            request_id="appr_2",
            session_id="sess_123",
            run_id="run_456",
            action_type="action2",
            payload={},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Test"
        )

        # Try to resolve 3 (one doesn't exist)
        request_ids = ["appr_1", "appr_2", "appr_nonexistent"]
        results = engine.bulk_resolve(request_ids, approved=True, resolver_id="user")

        assert results["success"] == 2
        assert results["failure"] == 1
        assert "appr_nonexistent" in results["failed_ids"]


class TestApprovalMetrics:
    """Test approval workflow metrics."""

    def test_metrics_empty(self):
        """Test metrics with no pending approvals."""
        engine = ApprovalEngine()
        metrics = engine.get_approval_metrics()

        assert metrics["pending_count"] == 0
        assert metrics["by_priority"] == {}
        assert metrics["by_risk_level"] == {}
        assert metrics["oldest_age_seconds"] == 0
        assert metrics["avg_age_seconds"] == 0

    def test_metrics_pending_count(self):
        """Test pending count in metrics."""
        engine = ApprovalEngine()

        # Add requests
        for i in range(5):
            engine._pending[f"appr_test{i}"] = ApprovalRequest(
                request_id=f"appr_test{i}",
                session_id="sess_123",
                run_id="run_456",
                action_type=f"action{i}",
                payload={},
                risk_level=RiskLevel.WRITE_SENSITIVE,
                reason="Test"
            )

        metrics = engine.get_approval_metrics()
        assert metrics["pending_count"] == 5

    def test_metrics_by_priority(self):
        """Test priority distribution in metrics."""
        engine = ApprovalEngine()

        # Add requests with different priorities
        priorities = [
            RiskLevel.SYSTEM_CRITICAL,  # priority 1
            RiskLevel.SYSTEM_CRITICAL,  # priority 1
            RiskLevel.DESTRUCTIVE,       # priority 2
            RiskLevel.WRITE_SENSITIVE,   # priority 3
        ]

        for i, risk in enumerate(priorities):
            engine._pending[f"appr_{i}"] = ApprovalRequest(
                request_id=f"appr_{i}",
                session_id="sess_123",
                run_id="run_456",
                action_type=f"action{i}",
                payload={},
                risk_level=risk,
                reason="Test"
            )

        metrics = engine.get_approval_metrics()
        assert metrics["by_priority"][1] == 2  # 2 critical
        assert metrics["by_priority"][2] == 1  # 1 destructive
        assert metrics["by_priority"][3] == 1  # 1 write sensitive

    def test_metrics_by_risk_level(self):
        """Test risk level distribution in metrics."""
        engine = ApprovalEngine()

        # Add requests with different risk levels
        risks = [
            RiskLevel.DESTRUCTIVE,
            RiskLevel.DESTRUCTIVE,
            RiskLevel.WRITE_SENSITIVE,
        ]

        for i, risk in enumerate(risks):
            engine._pending[f"appr_{i}"] = ApprovalRequest(
                request_id=f"appr_{i}",
                session_id="sess_123",
                run_id="run_456",
                action_type=f"action{i}",
                payload={},
                risk_level=risk,
                reason="Test"
            )

        metrics = engine.get_approval_metrics()
        assert metrics["by_risk_level"]["destructive"] == 2
        assert metrics["by_risk_level"]["write_sensitive"] == 1

    def test_metrics_age_calculation(self):
        """Test age calculation in metrics."""
        import time
        engine = ApprovalEngine()

        # Add a request
        engine._pending["appr_test"] = ApprovalRequest(
            request_id="appr_test",
            session_id="sess_123",
            run_id="run_456",
            action_type="action",
            payload={},
            risk_level=RiskLevel.WRITE_SENSITIVE,
            reason="Test"
        )

        # Wait a bit
        time.sleep(0.1)

        metrics = engine.get_approval_metrics()
        assert metrics["pending_count"] == 1
        assert metrics["oldest_age_seconds"] > 0
        assert metrics["newest_age_seconds"] > 0
        assert metrics["avg_age_seconds"] > 0
        assert metrics["oldest_age_seconds"] >= metrics["newest_age_seconds"]


class TestWorkflowIntegration:
    """Test complete workflow with priority and bulk operations."""

    def test_complete_workflow(self):
        """Test a complete approval workflow."""
        engine = ApprovalEngine()

        # Create mixed priority requests
        engine._pending["appr_low"] = ApprovalRequest(
            request_id="appr_low",
            session_id="sess_123",
            run_id="run_456",
            action_type="read",
            payload={},
            risk_level=RiskLevel.READ_ONLY,
            reason="Read log"
        )

        engine._pending["appr_critical"] = ApprovalRequest(
            request_id="appr_critical",
            session_id="sess_123",
            run_id="run_456",
            action_type="restart",
            payload={},
            risk_level=RiskLevel.SYSTEM_CRITICAL,
            reason="System restart"
        )

        # Get sorted pending
        pending = engine.get_pending_approvals(sorted_by_priority=True)
        assert pending[0]["request_id"] == "appr_critical"  # Critical first
        assert pending[1]["request_id"] == "appr_low"       # Low second

        # Get metrics
        metrics = engine.get_approval_metrics()
        assert metrics["pending_count"] == 2
        assert metrics["by_priority"][1] == 1  # 1 critical

        # Bulk deny non-critical
        results = engine.bulk_resolve(["appr_low"], approved=False, resolver_id="user")
        assert results["success"] == 1

        # Verify only critical remains
        remaining = engine.get_pending_approvals()
        assert len(remaining) == 1
        assert remaining[0]["request_id"] == "appr_critical"
