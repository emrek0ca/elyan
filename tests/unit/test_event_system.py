from __future__ import annotations

import asyncio

from core.event_system import EventBus, EventPriority


def test_event_publish_carries_trace_metadata():
    bus = EventBus()

    async def _publish() -> str:
        return await bus.publish(
            event_type="run.started",
            data={"run_id": "run-1", "session_id": "sess-1"},
            priority=EventPriority.HIGH,
            source="test",
            tags={"run"},
            metadata={"template_id": "core"},
            schema_version=2,
            correlation_id="corr-1",
            causation_id="cause-1",
            idempotency_key="idem-1",
        )

    event_id = asyncio.run(_publish())

    assert event_id
    assert bus.event_history[-1].schema_version == 2
    assert bus.event_history[-1].correlation_id == "corr-1"
    assert bus.event_history[-1].causation_id == "cause-1"
    assert bus.event_history[-1].idempotency_key == "idem-1"
    assert bus.event_history[-1].metadata == {"template_id": "core"}
