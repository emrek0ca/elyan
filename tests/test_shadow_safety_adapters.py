from __future__ import annotations

import pytest

from core.execution_guard import get_execution_guard
from core.protocol.shared_types import RiskLevel, VerificationStatus
from core.verifier.engine import VerificationEngine


@pytest.mark.asyncio
async def test_verification_engine_emits_shadow_event(monkeypatch):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    verification = await VerificationEngine().verify_action(
        "terminal",
        "exec",
        {"workspace_id": "ws_verify", "session_id": "sess_verify", "run_id": "run_verify"},
        {"status": "success", "exit_code": 1},
    )

    assert verification["status"] == VerificationStatus.FAILED
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert data["phase"] == "verification_result"
    assert data["action"] == "terminal.exec"
    assert data["allowed"] is False
    assert data["checks"][0]["metadata"]["status"] == "failed"
    assert kwargs["workspace_id"] == "ws_verify"
    assert kwargs["session_id"] == "sess_verify"
    assert kwargs["run_id"] == "run_verify"
    assert level == "warning"


@pytest.mark.asyncio
async def test_approval_engine_resolution_emits_shadow_events(monkeypatch):
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    monkeypatch.setenv("ELYAN_APPROVAL_PERSIST", "0")
    monkeypatch.setenv("ELYAN_APPROVAL_LEGACY_JSON", "0")

    from core.security.approval_engine import ApprovalEngine, ApprovalRequest
    import core.event_broadcaster as event_broadcaster

    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    async def _fake_broadcast_approval_resolved(*args, **kwargs):
        return None

    engine = ApprovalEngine()
    engine._pending.clear()
    monkeypatch.setattr(event_broadcaster, "broadcast_approval_resolved", _fake_broadcast_approval_resolved)
    monkeypatch.setattr(engine._repository, "mark_resolved", lambda *args, **kwargs: None)
    granted: list[dict] = []
    monkeypatch.setattr(engine._permission_grants, "issue_grant", lambda **kwargs: granted.append(kwargs))

    request = ApprovalRequest(
        request_id="appr_test_shadow",
        session_id="sess_approval",
        run_id="run_approval",
        action_type="filesystem.write_file",
        payload={
            "workspace_id": "ws_approval",
            "permission_grant": {
                "workspace_id": "ws_approval",
                "scope": "filesystem",
                "resource": "/tmp/demo.txt",
                "allowed_actions": ["write_file"],
                "ttl_seconds": 120,
            },
        },
        risk_level=RiskLevel.WRITE_SENSITIVE,
        reason="needs explicit approval",
    )
    engine._pending[request.request_id] = request

    resolved = engine.resolve_approval(request.request_id, True, "owner_1")

    assert resolved is True
    assert len(granted) == 1
    phases = [data["phase"] for _, data, _, _ in events]
    assert "approval_grant_issued" in phases
    assert "approval_resolved" in phases
    grant_event = next(data for _, data, _, _ in events if data["phase"] == "approval_grant_issued")
    assert grant_event["checks"][0]["metadata"]["scope"] == "filesystem"
    resolve_event = next(data for _, data, _, _ in events if data["phase"] == "approval_resolved")
    assert resolve_event["allowed"] is True
    assert resolve_event["checks"][0]["metadata"]["resolver_id"] == "owner_1"

