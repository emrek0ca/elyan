import pytest
import asyncio
import uuid
from core.protocol.events import MessageReceived
from core.session_engine import session_manager
from core.runtime.lifecycle import run_lifecycle_manager
from core.protocol.shared_types import RunStatus

@pytest.mark.asyncio
async def test_session_lane_locking():
    """Verifies that only one run can be active in a session at a time."""
    session_id = f"test_sess_{uuid.uuid4().hex[:6]}"
    
    # 1. Create two events for the same session
    evt1 = MessageReceived(event_id="e1", channel="test", channel_id="c1", user_id="u1", text="first")
    evt2 = MessageReceived(event_id="e2", channel="test", channel_id="c1", user_id="u1", text="second")
    
    # 2. Setup a dummy executor that waits
    execution_order = []
    
    async def slow_executor(event):
        execution_order.append(f"start_{event.event_id}")
        await asyncio.sleep(0.5)
        execution_order.append(f"end_{event.event_id}")
        
    session_manager.set_executor(slow_executor)
    
    # 3. Dispatch both events
    await session_manager.dispatch_event(evt1)
    await session_manager.dispatch_event(evt2)
    
    # 4. Wait for completion
    await asyncio.sleep(1.5)
    
    # 5. Verify serialization (FIFO order, no overlap)
    # Expected: start_e1, end_e1, start_e2, end_e2
    assert execution_order == ["start_e1", "end_e1", "start_e2", "end_e2"]

@pytest.mark.asyncio
async def test_run_lifecycle_transitions():
    """Verifies that runs follow the correct state machine."""
    run = run_lifecycle_manager.create_run("test_sess")
    run_id = run.run_id
    
    assert run.status == RunStatus.QUEUED
    
    run_lifecycle_manager.update_status(run_id, RunStatus.STARTED)
    assert run.status == RunStatus.STARTED
    
    run_lifecycle_manager.update_status(run_id, RunStatus.COMPLETED)
    assert run.status == RunStatus.COMPLETED
    
    # Terminal state check: should raise RuntimeError on further transition
    with pytest.raises(RuntimeError):
        run_lifecycle_manager.update_status(run_id, RunStatus.EXECUTING)

@pytest.mark.asyncio
async def test_protocol_validation():
    """Verifies that invalid payloads are rejected."""
    from core.protocol.validation import validate_event
    
    # Valid payload
    valid_payload = {
        "event_id": "evt_123",
        "channel": "telegram",
        "channel_id": "chat_456",
        "user_id": "user_789",
        "text": "hello"
    }
    event = validate_event(valid_payload, MessageReceived)
    assert event is not None
    assert event.text == "hello"
    
    # Invalid payload (missing required field 'text')
    invalid_payload = {
        "event_id": "evt_123",
        "channel": "telegram"
    }
    event = validate_event(invalid_payload, MessageReceived)
    assert event is None
