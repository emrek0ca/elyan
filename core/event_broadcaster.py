"""
Real-time Event Broadcasting System

WebSocket-ready event system for approval notifications, system alerts, and live updates.
"""

import json
import asyncio
from typing import Dict, Set, Any, Callable, List, Optional
from dataclasses import dataclass, asdict
from datetime import datetime
from enum import Enum

from core.observability.logger import get_structured_logger

slog = get_structured_logger("event_broadcaster")


class EventType(Enum):
    """Event types for broadcasting."""
    APPROVAL_PENDING = "approval_pending"
    APPROVAL_RESOLVED = "approval_resolved"
    RUN_STARTED = "run_started"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    SYSTEM_ALERT = "system_alert"
    PREFERENCE_UPDATED = "preference_updated"
    METRICS_UPDATED = "metrics_updated"


@dataclass
class BroadcastEvent:
    """Single broadcast event."""
    event_type: str
    timestamp: float
    data: Dict[str, Any]
    priority: str = "normal"  # normal, high, urgent

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), default=str)


class EventBroadcaster:
    """Central event broadcasting system with WebSocket support."""

    def __init__(self):
        """Initialize broadcaster."""
        self._subscribers: Dict[str, Set[Callable]] = {}
        self._websocket_clients: Set[Any] = set()
        self._event_history: List[BroadcastEvent] = []
        self._history_limit = 100
        self._lock = asyncio.Lock()

    async def subscribe(self, event_type: str, callback: Callable) -> None:
        """Subscribe to event type.

        Args:
            event_type: EventType.X.value
            callback: async or sync function(event: BroadcastEvent)
        """
        async with self._lock:
            if event_type not in self._subscribers:
                self._subscribers[event_type] = set()
            self._subscribers[event_type].add(callback)
            slog.log_event("event_subscriber_added", {
                "event_type": event_type,
                "total_subscribers": len(self._subscribers.get(event_type, set()))
            })

    async def unsubscribe(self, event_type: str, callback: Callable) -> None:
        """Unsubscribe from event type."""
        async with self._lock:
            if event_type in self._subscribers:
                self._subscribers[event_type].discard(callback)

    async def broadcast(self, event: BroadcastEvent) -> None:
        """Broadcast event to all subscribers and WebSocket clients.

        Args:
            event: BroadcastEvent to broadcast
        """
        async with self._lock:
            # Store in history
            self._event_history.append(event)
            if len(self._event_history) > self._history_limit:
                self._event_history.pop(0)

            # Notify subscribers
            subscribers = self._subscribers.get(event.event_type, set()).copy()

        # Async callback execution (outside lock)
        for callback in subscribers:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(event)
                else:
                    callback(event)
            except Exception as e:
                slog.log_event("event_callback_error", {
                    "event_type": event.event_type,
                    "error": str(e)
                }, level="error")

        # Broadcast to WebSocket clients
        await self._broadcast_to_websockets(event)

    async def register_websocket(self, client: Any) -> None:
        """Register WebSocket client.

        Args:
            client: WebSocket connection object (must have send() method)
        """
        async with self._lock:
            self._websocket_clients.add(client)

        slog.log_event("websocket_client_connected", {
            "total_clients": len(self._websocket_clients)
        })

    async def unregister_websocket(self, client: Any) -> None:
        """Unregister WebSocket client."""
        async with self._lock:
            self._websocket_clients.discard(client)

        slog.log_event("websocket_client_disconnected", {
            "total_clients": len(self._websocket_clients)
        })

    async def _broadcast_to_websockets(self, event: BroadcastEvent) -> None:
        """Send event to all WebSocket clients."""
        async with self._lock:
            clients = self._websocket_clients.copy()

        disconnected = []
        for client in clients:
            try:
                # Try to send JSON message
                if hasattr(client, 'send'):
                    await client.send(event.to_json())
            except Exception as e:
                slog.log_event("websocket_send_error", {
                    "error": str(e)
                }, level="warning")
                disconnected.append(client)

        # Clean up disconnected clients
        for client in disconnected:
            await self.unregister_websocket(client)

    async def get_event_history(self, event_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent events from history.

        Args:
            event_type: Filter by type (optional)
            limit: Max events to return

        Returns:
            List of recent events
        """
        async with self._lock:
            events = list(reversed(self._event_history))

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        return [e.to_dict() for e in events[:limit]]

    async def get_websocket_count(self) -> int:
        """Get number of connected WebSocket clients."""
        async with self._lock:
            return len(self._websocket_clients)

    async def clear_history(self) -> None:
        """Clear event history."""
        async with self._lock:
            self._event_history.clear()
        slog.log_event("event_history_cleared", {})


# Global broadcaster instance
_broadcaster: Optional[EventBroadcaster] = None


def get_event_broadcaster() -> EventBroadcaster:
    """Get or create event broadcaster singleton."""
    global _broadcaster
    if _broadcaster is None:
        _broadcaster = EventBroadcaster()
    return _broadcaster


# Convenience functions for common events
async def broadcast_approval_pending(request_id: str, action_type: str, risk_level: str, reason: str = "") -> None:
    """Broadcast approval pending event."""
    broadcaster = get_event_broadcaster()
    event = BroadcastEvent(
        event_type=EventType.APPROVAL_PENDING.value,
        timestamp=datetime.now().timestamp(),
        data={
            "request_id": request_id,
            "action_type": action_type,
            "risk_level": risk_level,
            "reason": reason
        },
        priority="high"
    )
    await broadcaster.broadcast(event)


async def broadcast_approval_resolved(request_id: str, approved: bool, resolver_id: str) -> None:
    """Broadcast approval resolved event."""
    broadcaster = get_event_broadcaster()
    event = BroadcastEvent(
        event_type=EventType.APPROVAL_RESOLVED.value,
        timestamp=datetime.now().timestamp(),
        data={
            "request_id": request_id,
            "approved": approved,
            "resolver_id": resolver_id
        },
        priority="high"
    )
    await broadcaster.broadcast(event)


async def broadcast_run_started(run_id: str, session_id: str, intent: str) -> None:
    """Broadcast run started event."""
    broadcaster = get_event_broadcaster()
    event = BroadcastEvent(
        event_type=EventType.RUN_STARTED.value,
        timestamp=datetime.now().timestamp(),
        data={
            "run_id": run_id,
            "session_id": session_id,
            "intent": intent
        },
        priority="normal"
    )
    await broadcaster.broadcast(event)


async def broadcast_run_completed(run_id: str, status: str, steps_count: int) -> None:
    """Broadcast run completed event."""
    broadcaster = get_event_broadcaster()
    event = BroadcastEvent(
        event_type=EventType.RUN_COMPLETED.value,
        timestamp=datetime.now().timestamp(),
        data={
            "run_id": run_id,
            "status": status,
            "steps_count": steps_count
        },
        priority="normal"
    )
    await broadcaster.broadcast(event)


async def broadcast_system_alert(alert_type: str, message: str, severity: str = "warning") -> None:
    """Broadcast system alert."""
    broadcaster = get_event_broadcaster()
    event = BroadcastEvent(
        event_type=EventType.SYSTEM_ALERT.value,
        timestamp=datetime.now().timestamp(),
        data={
            "alert_type": alert_type,
            "message": message,
            "severity": severity
        },
        priority="high" if severity == "critical" else "normal"
    )
    await broadcaster.broadcast(event)
