"""
Real-Time Event System & Pub/Sub
Event bus, publisher/subscriber pattern, event streaming
"""

import asyncio
import time
import json
from typing import Dict, List, Optional, Any, Callable, Set
from dataclasses import dataclass, field
from enum import Enum
from collections import deque, defaultdict
import uuid

from utils.logger import get_logger

logger = get_logger("event_system")


class EventPriority(Enum):
    """Event priority levels"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Event:
    """Represents an event"""
    event_id: str
    event_type: str
    data: Dict[str, Any]
    priority: EventPriority = EventPriority.NORMAL
    timestamp: float = field(default_factory=time.time)
    source: Optional[str] = None
    tags: Set[str] = field(default_factory=set)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Subscription:
    """Represents an event subscription"""
    subscription_id: str
    event_types: List[str]  # Event types to listen for (supports wildcards)
    callback: Callable
    filters: Dict[str, Any] = field(default_factory=dict)
    priority_threshold: EventPriority = EventPriority.LOW
    active: bool = True


class EventBus:
    """
    Real-Time Event System
    - Publish/Subscribe pattern
    - Event filtering
    - Event history
    - Webhook triggers
    - Priority-based delivery
    - Async event processing
    """

    def __init__(self):
        self.subscriptions: Dict[str, Subscription] = {}
        self.event_history: deque = deque(maxlen=1000)
        self.event_queue: asyncio.Queue = asyncio.Queue()
        self.processing_active = False
        self.event_stats: Dict[str, int] = defaultdict(int)
        self.webhook_endpoints: Dict[str, str] = {}

        logger.info("Event System initialized")

    def subscribe(
        self,
        event_types: List[str],
        callback: Callable,
        filters: Optional[Dict[str, Any]] = None,
        priority_threshold: EventPriority = EventPriority.LOW
    ) -> str:
        """Subscribe to events"""
        subscription_id = str(uuid.uuid4())[:8]

        subscription = Subscription(
            subscription_id=subscription_id,
            event_types=event_types,
            callback=callback,
            filters=filters or {},
            priority_threshold=priority_threshold
        )

        self.subscriptions[subscription_id] = subscription
        logger.info(f"Subscription created: {subscription_id} for types: {event_types}")

        return subscription_id

    def unsubscribe(self, subscription_id: str):
        """Unsubscribe from events"""
        if subscription_id in self.subscriptions:
            del self.subscriptions[subscription_id]
            logger.info(f"Subscription removed: {subscription_id}")

    async def publish(
        self,
        event_type: str,
        data: Dict[str, Any],
        priority: EventPriority = EventPriority.NORMAL,
        source: Optional[str] = None,
        tags: Optional[Set[str]] = None
    ) -> str:
        """Publish an event"""
        event_id = str(uuid.uuid4())[:8]

        event = Event(
            event_id=event_id,
            event_type=event_type,
            data=data,
            priority=priority,
            source=source,
            tags=tags or set()
        )

        # Store in history
        self.event_history.append(event)

        # Update stats
        self.event_stats[event_type] += 1

        # Queue for processing
        await self.event_queue.put(event)

        logger.debug(f"Event published: {event_type} (ID: {event_id})")

        return event_id

    async def start_processing(self):
        """Start event processing loop"""
        self.processing_active = True
        logger.info("Event processing started")

        while self.processing_active:
            try:
                # Get event from queue
                event = await asyncio.wait_for(
                    self.event_queue.get(),
                    timeout=1.0
                )

                # Process event
                await self._process_event(event)

            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Event processing error: {e}")

    def stop_processing(self):
        """Stop event processing"""
        self.processing_active = False
        logger.info("Event processing stopped")

    async def _process_event(self, event: Event):
        """Process a single event by notifying subscribers"""
        matching_subscriptions = self._find_matching_subscriptions(event)

        # Sort by priority
        matching_subscriptions.sort(
            key=lambda s: s.priority_threshold.value,
            reverse=True
        )

        # Notify subscribers
        for subscription in matching_subscriptions:
            try:
                if asyncio.iscoroutinefunction(subscription.callback):
                    await subscription.callback(event)
                else:
                    subscription.callback(event)

                logger.debug(f"Notified subscription: {subscription.subscription_id}")

            except Exception as e:
                logger.error(f"Callback error for {subscription.subscription_id}: {e}")

        # Trigger webhooks
        await self._trigger_webhooks(event)

    def _find_matching_subscriptions(self, event: Event) -> List[Subscription]:
        """Find subscriptions that match the event"""
        matching = []

        for subscription in self.subscriptions.values():
            if not subscription.active:
                continue

            # Check priority threshold
            if event.priority.value < subscription.priority_threshold.value:
                continue

            # Check event type match
            type_match = False
            for event_type_pattern in subscription.event_types:
                if self._match_event_type(event.event_type, event_type_pattern):
                    type_match = True
                    break

            if not type_match:
                continue

            # Check filters
            if not self._match_filters(event, subscription.filters):
                continue

            matching.append(subscription)

        return matching

    def _match_event_type(self, event_type: str, pattern: str) -> bool:
        """Match event type against pattern (supports wildcards)"""
        # Exact match
        if event_type == pattern:
            return True

        # Wildcard match
        if pattern == "*":
            return True

        # Prefix match (e.g., "user.*" matches "user.created", "user.updated")
        if pattern.endswith(".*"):
            prefix = pattern[:-2]
            if event_type.startswith(prefix + "."):
                return True

        return False

    def _match_filters(self, event: Event, filters: Dict[str, Any]) -> bool:
        """Check if event matches subscription filters"""
        if not filters:
            return True

        for key, value in filters.items():
            # Check in event data
            if key in event.data:
                if event.data[key] != value:
                    return False
            # Check in metadata
            elif key in event.metadata:
                if event.metadata[key] != value:
                    return False
            # Check tags
            elif key == "tags":
                if not (set(value) & event.tags):  # Intersection check
                    return False
            else:
                return False

        return True

    async def _trigger_webhooks(self, event: Event):
        """Trigger webhook endpoints for event"""
        for webhook_id, url in self.webhook_endpoints.items():
            try:
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    payload = {
                        "event_id": event.event_id,
                        "event_type": event.event_type,
                        "data": event.data,
                        "timestamp": event.timestamp,
                        "source": event.source
                    }

                    async with session.post(url, json=payload, timeout=5) as response:
                        if response.status >= 400:
                            logger.warning(f"Webhook {webhook_id} failed: {response.status}")

            except Exception as e:
                logger.error(f"Webhook trigger error for {webhook_id}: {e}")

    def add_webhook(self, webhook_id: str, url: str):
        """Register a webhook endpoint"""
        self.webhook_endpoints[webhook_id] = url
        logger.info(f"Webhook registered: {webhook_id} -> {url}")

    def remove_webhook(self, webhook_id: str):
        """Remove a webhook endpoint"""
        if webhook_id in self.webhook_endpoints:
            del self.webhook_endpoints[webhook_id]
            logger.info(f"Webhook removed: {webhook_id}")

    def get_event_history(
        self,
        event_type: Optional[str] = None,
        limit: int = 100,
        since: Optional[float] = None
    ) -> List[Event]:
        """Get event history with filters"""
        events = list(self.event_history)

        # Filter by type
        if event_type:
            events = [e for e in events if e.event_type == event_type]

        # Filter by time
        if since:
            events = [e for e in events if e.timestamp >= since]

        # Sort by timestamp (newest first)
        events.sort(key=lambda e: e.timestamp, reverse=True)

        return events[:limit]

    def replay_events(
        self,
        subscription_id: str,
        since: Optional[float] = None
    ):
        """Replay historical events to a subscription"""
        if subscription_id not in self.subscriptions:
            logger.warning(f"Subscription not found: {subscription_id}")
            return

        subscription = self.subscriptions[subscription_id]
        events = self.get_event_history(since=since)

        # Filter matching events
        matching_events = [
            e for e in events
            if any(self._match_event_type(e.event_type, pattern) for pattern in subscription.event_types)
        ]

        logger.info(f"Replaying {len(matching_events)} events to {subscription_id}")

        # Replay events
        for event in reversed(matching_events):  # Oldest first
            try:
                if asyncio.iscoroutinefunction(subscription.callback):
                    asyncio.create_task(subscription.callback(event))
                else:
                    subscription.callback(event)
            except Exception as e:
                logger.error(f"Replay error: {e}")

    def pause_subscription(self, subscription_id: str):
        """Pause a subscription"""
        if subscription_id in self.subscriptions:
            self.subscriptions[subscription_id].active = False
            logger.info(f"Subscription paused: {subscription_id}")

    def resume_subscription(self, subscription_id: str):
        """Resume a subscription"""
        if subscription_id in self.subscriptions:
            self.subscriptions[subscription_id].active = True
            logger.info(f"Subscription resumed: {subscription_id}")

    def get_stats(self) -> Dict[str, Any]:
        """Get event statistics"""
        return {
            "total_subscriptions": len(self.subscriptions),
            "active_subscriptions": sum(1 for s in self.subscriptions.values() if s.active),
            "total_events": sum(self.event_stats.values()),
            "events_by_type": dict(self.event_stats),
            "webhooks": len(self.webhook_endpoints),
            "queue_size": self.event_queue.qsize(),
            "history_size": len(self.event_history)
        }

    def clear_history(self):
        """Clear event history"""
        self.event_history.clear()
        logger.info("Event history cleared")


# Global instance
_event_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get or create global event bus instance"""
    global _event_bus
    if _event_bus is None:
        _event_bus = EventBus()
    return _event_bus
