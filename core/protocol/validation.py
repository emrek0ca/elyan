from typing import Any, Dict, Optional, Type, TypeVar, Union
from pydantic import ValidationError
from core.protocol.events import ElyanEvent
from core.observability.logger import get_structured_logger

slog = get_structured_logger("protocol_validation")

T = TypeVar("T", bound=ElyanEvent)

def validate_event(payload: Dict[str, Any], event_class: Type[T]) -> Optional[T]:
    """
    Validates a dictionary against a specific Elyan event class.
    Returns the validated event object or None if invalid.
    """
    try:
        return event_class(**payload)
    except ValidationError as e:
        slog.log_event("validation_error", {
            "expected_type": event_class.__name__,
            "errors": e.errors()
        }, level="error")
        return None

def parse_raw_event(payload: Dict[str, Any]) -> Optional[ElyanEvent]:
    """
    Attempts to parse a raw dictionary into one of the known Elyan events
    based on the 'event_type' field (if present) or schema heuristics.
    """
    # This is a placeholder for a more sophisticated factory pattern
    # In a full implementation, we'd use a registry mapping type names to classes
    from core.protocol.events import (
        MessageReceived, SessionResolved, RunQueued, RunStarted, RunStatusChanged, SessionStateChanged,
        PlanCreated, PlanStepStarted, PlanStepCompleted,
        ToolRequested, ToolApproved, ToolRejected, ToolSucceeded, ToolFailed,
        ApprovalRequested, ApprovalResolved,
        OutputBlockCreated, PreviewUpdated, VerificationStarted, VerificationResult,
        RecoveryStarted, RecoveryCompleted, RunCompleted, RunFailed, RunCancelled, RunCompacted,
        MemoryWritten, NodeRegistered, NodeHealthUpdated
    )
    
    event_type = payload.get("event_type")
    if not event_type:
        # Heuristic fallback could go here
        return None
        
    mapping = {
        "MessageReceived": MessageReceived,
        "SessionResolved": SessionResolved,
        "RunQueued": RunQueued,
        "RunStarted": RunStarted,
        "RunStatusChanged": RunStatusChanged,
        "SessionStateChanged": SessionStateChanged,
        "PlanCreated": PlanCreated,
        "PlanStepStarted": PlanStepStarted,
        "PlanStepCompleted": PlanStepCompleted,
        "ToolRequested": ToolRequested,
        "ToolApproved": ToolApproved,
        "ToolRejected": ToolRejected,
        "ToolSucceeded": ToolSucceeded,
        "ToolFailed": ToolFailed,
        "ApprovalRequested": ApprovalRequested,
        "ApprovalResolved": ApprovalResolved,
        "OutputBlockCreated": OutputBlockCreated,
        "PreviewUpdated": PreviewUpdated,
        "VerificationStarted": VerificationStarted,
        "VerificationResult": VerificationResult,
        "RecoveryStarted": RecoveryStarted,
        "RecoveryCompleted": RecoveryCompleted,
        "RunCompleted": RunCompleted,
        "RunFailed": RunFailed,
        "RunCancelled": RunCancelled,
        "RunCompacted": RunCompacted,
        "MemoryWritten": MemoryWritten,
        "NodeRegistered": NodeRegistered,
        "NodeHealthUpdated": NodeHealthUpdated
    }
    
    cls = mapping.get(event_type)
    if cls:
        return validate_event(payload.get("data", payload), cls)
        
    return None
