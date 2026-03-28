from __future__ import annotations

from pydantic import TypeAdapter

from core.protocol.events import (
    ConsensusProposed,
    ConsensusResolved,
    DeadlockRecovered,
    ElyanEvent,
    LearningSignalRecorded,
    ModeSwitched,
    PlanCreated,
    RecoveryCompleted,
    RunQueued,
    SessionStateChanged,
    ToolApproved,
    VerificationStarted,
)
from core.protocol.validation import parse_raw_event
from core.protocol.shared_types import ExecutionMode, QueuePolicy


def test_new_event_models_apply_base_defaults():
    event = ConsensusProposed(
        event_id="evt-1",
        session_id="sess-1",
        consensus_id="cons-1",
        topic="route-selection",
        proposed_by="planner",
    )

    assert event.source == "system"
    assert isinstance(event.timestamp, float)
    assert event.candidates == []
    assert event.metadata == {}
    assert event.schema_version == 1
    assert event.correlation_id is None


def test_mode_switched_and_learning_signal_preserve_typed_fields():
    mode_event = ModeSwitched(
        event_id="evt-2",
        session_id="sess-1",
        from_mode="direct",
        to_mode="approval_gate",
        reason="risk increased",
    )
    signal_event = LearningSignalRecorded(
        event_id="evt-3",
        session_id="sess-1",
        signal_type="reward",
        value=0.75,
        source_event_id="evt-prev",
    )

    assert mode_event.from_mode is ExecutionMode.DIRECT
    assert mode_event.to_mode is ExecutionMode.APPROVAL_GATE
    assert signal_event.value == 0.75
    assert signal_event.source_event_id == "evt-prev"
    assert signal_event.metadata == {}


def test_mediator_lifecycle_event_models_preserve_traceability_and_typed_fields():
    run_event = RunQueued(
        event_id="evt-queue",
        session_id="sess-1",
        run_id="run-1",
        policy="merge",
        queue_depth=2,
        correlation_id="corr-1",
        causation_id="cause-1",
        idempotency_key="idem-1",
        business_justification="queue compatible follow-up work",
    )
    session_event = SessionStateChanged(
        event_id="evt-state",
        session_id="sess-1",
        actor_id="user-1",
        old_lane_state="idle",
        new_lane_state="executing",
        queue_policy="interrupt",
    )
    plan_event = PlanCreated(
        event_id="evt-plan",
        session_id="sess-1",
        run_id="run-1",
        planner_id="planner",
        plan_id="plan-1",
        step_count=3,
        execution_mode="delegated",
    )
    verify_event = VerificationStarted(
        event_id="evt-verify",
        session_id="sess-1",
        run_id="run-1",
        verifier_id="verifier",
        verification_target="artifact_bundle",
    )
    recovery_event = RecoveryCompleted(
        event_id="evt-recover",
        session_id="sess-1",
        run_id="run-1",
        recovery_id="recovery-1",
        outcome="resumed",
        resumed_run=True,
    )
    approval_event = ToolApproved(
        event_id="evt-approve",
        session_id="sess-1",
        run_id="run-1",
        tool_name="filesystem.write_text",
        request_id="req-1",
        approver_id="user-1",
    )

    assert run_event.policy is QueuePolicy.MERGE
    assert run_event.queue_depth == 2
    assert run_event.correlation_id == "corr-1"
    assert run_event.idempotency_key == "idem-1"
    assert session_event.queue_policy is QueuePolicy.INTERRUPT
    assert plan_event.execution_mode is ExecutionMode.DELEGATED
    assert verify_event.verification_target == "artifact_bundle"
    assert recovery_event.resumed_run is True
    assert approval_event.tool_name == "filesystem.write_text"


def test_elyan_event_union_accepts_new_event_models():
    adapter = TypeAdapter(ElyanEvent)

    samples = [
        (
            {
                "event_id": "evt-4",
                "session_id": "sess-1",
                "consensus_id": "cons-2",
                "topic": "policy",
                "proposed_by": "engine",
                "candidates": ["followup", "interrupt"],
            },
            ConsensusProposed,
        ),
        (
            {
                "event_id": "evt-5",
                "session_id": "sess-1",
                "consensus_id": "cons-2",
                "resolved_by": "engine",
                "accepted": True,
                "selected_option": "followup",
            },
            ConsensusResolved,
        ),
        (
            {
                "event_id": "evt-6",
                "session_id": "sess-1",
                "run_id": "run-1",
                "deadlock_type": "retry_loop",
                "recovery_action": "reset_plan",
            },
            DeadlockRecovered,
        ),
        (
            {
                "event_id": "evt-7",
                "session_id": "sess-1",
                "run_id": "run-1",
                "planner_id": "planner",
                "plan_id": "plan-1",
                "step_count": 2,
                "execution_mode": "delegated",
            },
            PlanCreated,
        ),
        (
            {
                "event_id": "evt-8",
                "session_id": "sess-1",
                "run_id": "run-1",
                "verifier_id": "qa",
                "verification_target": "artifact_bundle",
            },
            VerificationStarted,
        ),
        (
            {
                "event_id": "evt-9",
                "session_id": "sess-1",
                "run_id": "run-1",
                "recovery_id": "recover-1",
                "outcome": "resumed",
                "resumed_run": True,
            },
            RecoveryCompleted,
        ),
    ]

    for payload, expected_type in samples:
        event = adapter.validate_python(payload)
        assert isinstance(event, expected_type)


def test_parse_raw_event_handles_mediator_lifecycle_events():
    parsed = parse_raw_event(
        {
            "event_type": "PlanCreated",
            "event_id": "evt-plan",
            "session_id": "sess-1",
            "run_id": "run-1",
            "planner_id": "planner",
            "plan_id": "plan-1",
            "step_count": 3,
            "execution_mode": "delegated",
        }
    )

    assert isinstance(parsed, PlanCreated)
    assert parsed.execution_mode is ExecutionMode.DELEGATED
