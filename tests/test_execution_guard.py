from __future__ import annotations

from core.execution_guard import ExecutionCheck, get_execution_guard
from core.observability.trace_context import activate_trace_context, build_trace_context, reset_trace_context


def test_execution_guard_shadow_disabled_by_default(monkeypatch):
    events: list[tuple[str, dict, str]] = []
    guard = get_execution_guard()
    monkeypatch.delenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", raising=False)
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level)),
    )

    emitted = guard.observe_shadow(
        action="workflow_run",
        phase="seat_gate",
        allowed=True,
        workspace_id="ws_1",
        actor_id="user_1",
    )

    assert emitted is False
    assert events == []


def test_execution_guard_shadow_logs_enriched_payload(monkeypatch):
    events: list[tuple[str, dict, str, dict]] = []
    guard = get_execution_guard()
    monkeypatch.setenv("ELYAN_FF_EXECUTION_GUARD_SHADOW", "1")
    monkeypatch.setattr(
        guard._logger,
        "log_event",
        lambda event_type, data, level="info", **kwargs: events.append((event_type, data, level, kwargs)),
    )

    trace = build_trace_context(
        method="POST",
        path="/api/v1/workflows/start",
        trace_id="trace demo",
        request_id="req demo",
        workspace_id="ws_trace",
        session_id="sess_trace",
    )
    token = activate_trace_context(trace)
    try:
        emitted = guard.observe_shadow(
            action="workflow_run",
            phase="credit_gate",
            allowed=False,
            workspace_id="ws_runtime",
            actor_id="user_1",
            reason="insufficient credits",
            checks=[
                ExecutionCheck(
                    name="credit_authorization",
                    allowed=False,
                    reason="insufficient credits",
                    metadata={"estimated_credits": 3, "allowed": False},
                )
            ],
            metadata={"task_type": "proposal", "complex": object()},
        )
    finally:
        reset_trace_context(token)

    assert emitted is True
    assert len(events) == 1
    event_type, data, level, kwargs = events[0]
    assert event_type == "execution_guard_shadow"
    assert level == "info"
    assert data["shadow_mode"] is True
    assert data["action"] == "workflow_run"
    assert data["phase"] == "credit_gate"
    assert data["allowed"] is False
    assert data["flag_source"] == "env"
    assert data["checks"][0]["name"] == "credit_authorization"
    assert data["checks"][0]["metadata"]["estimated_credits"] == 3
    assert isinstance(data["metadata"]["complex"], str)
    assert kwargs["trace_id"] == "trace-demo"
    assert kwargs["request_id"] == "req-demo"
    assert kwargs["workspace_id"] == "ws_runtime"
    assert kwargs["session_id"] == "sess_trace"
