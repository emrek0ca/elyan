"""
Test Event Broadcaster System

Tests for WebSocket-ready event system with async subscribers and broadcasting.
"""

import pytest
import asyncio
from core.event_broadcaster import (
    EventBroadcaster,
    BroadcastEvent,
    EventType,
    get_event_broadcaster,
    broadcast_approval_pending,
    broadcast_approval_resolved,
    broadcast_run_started,
    broadcast_run_completed,
    broadcast_system_alert
)


class TestBroadcastEvent:
    """Test BroadcastEvent dataclass."""

    def test_event_creation(self):
        """Test creating a broadcast event."""
        event = BroadcastEvent(
            event_type=EventType.APPROVAL_PENDING.value,
            timestamp=1234567890.0,
            data={"request_id": "appr_123"},
            priority="high"
        )
        assert event.event_type == "approval_pending"
        assert event.timestamp == 1234567890.0
        assert event.data["request_id"] == "appr_123"
        assert event.priority == "high"

    def test_event_to_dict(self):
        """Test event serialization to dict."""
        event = BroadcastEvent(
            event_type=EventType.RUN_COMPLETED.value,
            timestamp=1234567890.0,
            data={"run_id": "run_456"},
            priority="normal"
        )
        event_dict = event.to_dict()
        assert event_dict["event_type"] == "run_completed"
        assert event_dict["data"]["run_id"] == "run_456"

    def test_event_to_json(self):
        """Test event serialization to JSON."""
        event = BroadcastEvent(
            event_type=EventType.SYSTEM_ALERT.value,
            timestamp=1234567890.0,
            data={"message": "test alert"},
            priority="urgent"
        )
        json_str = event.to_json()
        assert "approval_pending" in json_str or "system_alert" in json_str
        assert '"message": "test alert"' in json_str


class TestEventBroadcaster:
    """Test EventBroadcaster core functionality."""

    def test_broadcaster_creation(self):
        """Test creating a broadcaster instance."""
        broadcaster = EventBroadcaster()
        assert broadcaster is not None
        assert len(broadcaster._subscribers) == 0
        assert len(broadcaster._websocket_clients) == 0

    @pytest.mark.asyncio
    async def test_subscribe_and_broadcast(self):
        """Test subscribing to events and broadcasting."""
        broadcaster = EventBroadcaster()
        received_events = []

        async def subscriber_callback(event: BroadcastEvent):
            received_events.append(event)

        # Subscribe to approval pending events
        await broadcaster.subscribe(EventType.APPROVAL_PENDING.value, subscriber_callback)

        # Broadcast an event
        event = BroadcastEvent(
            event_type=EventType.APPROVAL_PENDING.value,
            timestamp=1234567890.0,
            data={"request_id": "appr_123"}
        )
        await broadcaster.broadcast(event)

        # Verify event was received
        await asyncio.sleep(0.1)
        assert len(received_events) == 1
        assert received_events[0].event_type == "approval_pending"

    @pytest.mark.asyncio
    async def test_multiple_subscribers(self):
        """Test multiple subscribers for same event."""
        broadcaster = EventBroadcaster()
        received_1 = []
        received_2 = []

        async def subscriber_1(event: BroadcastEvent):
            received_1.append(event)

        async def subscriber_2(event: BroadcastEvent):
            received_2.append(event)

        await broadcaster.subscribe(EventType.APPROVAL_RESOLVED.value, subscriber_1)
        await broadcaster.subscribe(EventType.APPROVAL_RESOLVED.value, subscriber_2)

        event = BroadcastEvent(
            event_type=EventType.APPROVAL_RESOLVED.value,
            timestamp=1234567890.0,
            data={"approved": True}
        )
        await broadcaster.broadcast(event)

        await asyncio.sleep(0.1)
        assert len(received_1) == 1
        assert len(received_2) == 1

    @pytest.mark.asyncio
    async def test_event_history(self):
        """Test event history storage."""
        broadcaster = EventBroadcaster()

        # Broadcast multiple events
        for i in range(5):
            event = BroadcastEvent(
                event_type=EventType.RUN_STARTED.value,
                timestamp=1234567890.0 + i,
                data={"run_id": f"run_{i}"}
            )
            await broadcaster.broadcast(event)

        # Get history
        history = await broadcaster.get_event_history(limit=10)
        assert len(history) == 5
        assert history[0]["event_type"] == "run_started"

    @pytest.mark.asyncio
    async def test_event_history_with_filter(self):
        """Test event history filtering by type."""
        broadcaster = EventBroadcaster()

        # Broadcast mixed events
        for i in range(3):
            event1 = BroadcastEvent(
                event_type=EventType.RUN_STARTED.value,
                timestamp=1234567890.0 + i,
                data={"run_id": f"run_{i}"}
            )
            await broadcaster.broadcast(event1)

            event2 = BroadcastEvent(
                event_type=EventType.SYSTEM_ALERT.value,
                timestamp=1234567890.0 + i + 0.5,
                data={"message": f"alert_{i}"}
            )
            await broadcaster.broadcast(event2)

        # Get only system alerts
        history = await broadcaster.get_event_history(
            event_type=EventType.SYSTEM_ALERT.value,
            limit=10
        )
        assert all(e["event_type"] == "system_alert" for e in history)

    @pytest.mark.asyncio
    async def test_websocket_client_registration(self):
        """Test registering WebSocket clients."""
        broadcaster = EventBroadcaster()

        # Mock WebSocket client
        class MockWebSocket:
            def __init__(self):
                self.sent_messages = []

            async def send(self, data):
                self.sent_messages.append(data)

        client = MockWebSocket()
        await broadcaster.register_websocket(client)

        count = await broadcaster.get_websocket_count()
        assert count == 1

        await broadcaster.unregister_websocket(client)
        count = await broadcaster.get_websocket_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_unsubscribe(self):
        """Test unsubscribing from events."""
        broadcaster = EventBroadcaster()
        received = []

        async def callback(event: BroadcastEvent):
            received.append(event)

        await broadcaster.subscribe(EventType.RUN_COMPLETED.value, callback)
        await broadcaster.unsubscribe(EventType.RUN_COMPLETED.value, callback)

        event = BroadcastEvent(
            event_type=EventType.RUN_COMPLETED.value,
            timestamp=1234567890.0,
            data={"run_id": "run_123"}
        )
        await broadcaster.broadcast(event)

        await asyncio.sleep(0.1)
        assert len(received) == 0

    @pytest.mark.asyncio
    async def test_history_limit(self):
        """Test that history respects the limit."""
        broadcaster = EventBroadcaster()
        broadcaster._history_limit = 5

        # Broadcast more events than the limit
        for i in range(10):
            event = BroadcastEvent(
                event_type=EventType.RUN_STARTED.value,
                timestamp=1234567890.0 + i,
                data={"run_id": f"run_{i}"}
            )
            await broadcaster.broadcast(event)

        # History should only contain the most recent 5
        assert len(broadcaster._event_history) <= 5

    @pytest.mark.asyncio
    async def test_clear_history(self):
        """Test clearing event history."""
        broadcaster = EventBroadcaster()

        # Broadcast some events
        for i in range(3):
            event = BroadcastEvent(
                event_type=EventType.RUN_STARTED.value,
                timestamp=1234567890.0 + i,
                data={"run_id": f"run_{i}"}
            )
            await broadcaster.broadcast(event)

        assert len(broadcaster._event_history) > 0

        # Clear history
        await broadcaster.clear_history()
        assert len(broadcaster._event_history) == 0


class TestConvenienceFunctions:
    """Test convenience broadcast functions."""

    @pytest.mark.asyncio
    async def test_broadcast_approval_pending(self):
        """Test broadcasting approval pending event."""
        broadcaster = get_event_broadcaster()
        received = []

        async def callback(event: BroadcastEvent):
            received.append(event)

        await broadcaster.subscribe(EventType.APPROVAL_PENDING.value, callback)

        await broadcast_approval_pending(
            request_id="appr_123",
            action_type="execute_shell",
            risk_level="destructive",
            reason="Testing"
        )

        await asyncio.sleep(0.1)
        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_broadcast_approval_resolved(self):
        """Test broadcasting approval resolved event."""
        broadcaster = get_event_broadcaster()
        received = []

        async def callback(event: BroadcastEvent):
            received.append(event)

        await broadcaster.subscribe(EventType.APPROVAL_RESOLVED.value, callback)

        await broadcast_approval_resolved(
            request_id="appr_123",
            approved=True,
            resolver_id="user_123"
        )

        await asyncio.sleep(0.1)
        assert len(received) >= 1

    @pytest.mark.asyncio
    async def test_broadcast_run_events(self):
        """Test broadcasting run events."""
        broadcaster = get_event_broadcaster()
        received_started = []
        received_completed = []

        async def callback_started(event: BroadcastEvent):
            received_started.append(event)

        async def callback_completed(event: BroadcastEvent):
            received_completed.append(event)

        await broadcaster.subscribe(EventType.RUN_STARTED.value, callback_started)
        await broadcaster.subscribe(EventType.RUN_COMPLETED.value, callback_completed)

        await broadcast_run_started(
            run_id="run_123",
            session_id="sess_456",
            intent="Test intent"
        )
        await broadcast_run_completed(
            run_id="run_123",
            status="success",
            steps_count=5
        )

        await asyncio.sleep(0.1)
        assert len(received_started) >= 1
        assert len(received_completed) >= 1

    @pytest.mark.asyncio
    async def test_broadcast_system_alert(self):
        """Test broadcasting system alerts."""
        broadcaster = get_event_broadcaster()
        received = []

        async def callback(event: BroadcastEvent):
            received.append(event)

        await broadcaster.subscribe(EventType.SYSTEM_ALERT.value, callback)

        await broadcast_system_alert(
            alert_type="memory_full",
            message="Memory usage is high",
            severity="warning"
        )

        await asyncio.sleep(0.1)
        assert len(received) >= 1


class TestSingleton:
    """Test broadcaster singleton pattern."""

    def test_singleton_instance(self):
        """Test that get_event_broadcaster returns singleton."""
        broadcaster1 = get_event_broadcaster()
        broadcaster2 = get_event_broadcaster()
        assert broadcaster1 is broadcaster2

    @pytest.mark.asyncio
    async def test_singleton_state_persistence(self):
        """Test that singleton maintains state across calls."""
        broadcaster = get_event_broadcaster()
        received = []

        async def callback(event: BroadcastEvent):
            received.append(event)

        await broadcaster.subscribe(EventType.RUN_STARTED.value, callback)

        # Get the same singleton and broadcast
        broadcaster2 = get_event_broadcaster()
        event = BroadcastEvent(
            event_type=EventType.RUN_STARTED.value,
            timestamp=1234567890.0,
            data={"run_id": "run_123"}
        )
        await broadcaster2.broadcast(event)

        await asyncio.sleep(0.1)
        assert len(received) >= 1
