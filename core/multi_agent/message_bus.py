"""
core/multi_agent/message_bus.py
───────────────────────────────────────────────────────────────────────────────
Agent Message Bus — the nervous system of the multi-agent runtime.

Design principles:
  - Topic-based pub/sub with pattern matching (fnmatch)
  - Async-first, single-writer ring buffer per topic
  - SQLite WAL-mode persistence for crash recovery
  - Bounded memory: ring buffer evicts oldest on overflow
  - Request-reply built on top of pub/sub (no special wiring)
  - Zero coupling to Agent class — any component can publish/subscribe

Capacity model:
  Let N = number of agents, M = messages/sec, B = buffer size.
  Memory ≈ N × B × avg_message_bytes.
  Default B = 4096, avg ≈ 512 bytes → ~2 MB per topic at saturation.
  SQLite WAL flush is batched every 500ms to amortize I/O.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Any, Awaitable, Callable

from core.observability.logger import get_structured_logger
from core.storage_paths import resolve_elyan_data_dir

slog = get_structured_logger("agent_message_bus")

# ── Message contract ────────────────────────────────────────────────────────


@dataclass(slots=True, frozen=True)
class AgentMessage:
    """Immutable message flowing through the bus.

    Fields are ordered by read frequency so hot-path attribute access
    benefits from slot layout on CPython.
    """

    topic: str
    from_agent: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    to_agent: str = ""  # empty = broadcast
    correlation_id: str = ""  # links related messages in a task chain
    reply_to: str = ""  # topic to send reply to (request-reply pattern)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AgentMessage":
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:16]),
            topic=str(data.get("topic") or ""),
            from_agent=str(data.get("from_agent") or ""),
            to_agent=str(data.get("to_agent") or ""),
            payload=dict(data.get("payload") or {}),
            correlation_id=str(data.get("correlation_id") or ""),
            reply_to=str(data.get("reply_to") or ""),
            timestamp=float(data.get("timestamp") or time.time()),
        )


# Type alias for subscriber callbacks
MessageHandler = Callable[[AgentMessage], Awaitable[None]]


# ── Subscription ────────────────────────────────────────────────────────────


@dataclass(slots=True)
class _Subscription:
    subscriber_id: str
    topic_pattern: str  # fnmatch pattern, e.g. "task.result.*"
    handler: MessageHandler


# ── Ring buffer ─────────────────────────────────────────────────────────────

_DEFAULT_BUFFER_SIZE = 4096


class _RingBuffer:
    """Bounded deque with O(1) append and automatic eviction."""

    __slots__ = ("_buf", "_capacity")

    def __init__(self, capacity: int = _DEFAULT_BUFFER_SIZE):
        self._capacity = max(64, capacity)
        self._buf: deque[AgentMessage] = deque(maxlen=self._capacity)

    def append(self, msg: AgentMessage) -> None:
        self._buf.append(msg)

    def recent(self, n: int = 50) -> list[AgentMessage]:
        start = max(0, len(self._buf) - n)
        return list(self._buf)[start:]

    def __len__(self) -> int:
        return len(self._buf)


# ── SQLite persistence ──────────────────────────────────────────────────────


class _MessageStore:
    """WAL-mode SQLite store for crash recovery.

    Only messages younger than TTL_SECONDS are retained on startup.
    Older messages are pruned to keep the DB lean.
    """

    TTL_SECONDS = 86400  # 24 hours

    def __init__(self, db_path: Path):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._db_path = str(db_path)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path, timeout=5)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id          TEXT PRIMARY KEY,
                    topic       TEXT NOT NULL,
                    from_agent  TEXT NOT NULL,
                    to_agent    TEXT NOT NULL DEFAULT '',
                    payload     TEXT NOT NULL,
                    correlation_id TEXT NOT NULL DEFAULT '',
                    reply_to    TEXT NOT NULL DEFAULT '',
                    timestamp   REAL NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_topic_ts ON messages(topic, timestamp DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_msg_correlation ON messages(correlation_id, timestamp)"
            )
            # Prune old messages
            cutoff = time.time() - self.TTL_SECONDS
            conn.execute("DELETE FROM messages WHERE timestamp < ?", (cutoff,))
            conn.commit()

    def persist(self, msg: AgentMessage) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO messages
                    (id, topic, from_agent, to_agent, payload, correlation_id, reply_to, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    msg.id,
                    msg.topic,
                    msg.from_agent,
                    msg.to_agent,
                    json.dumps(msg.payload, ensure_ascii=False, default=str),
                    msg.correlation_id,
                    msg.reply_to,
                    msg.timestamp,
                ),
            )
            conn.commit()

    def persist_batch(self, messages: list[AgentMessage]) -> None:
        if not messages:
            return
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR IGNORE INTO messages
                    (id, topic, from_agent, to_agent, payload, correlation_id, reply_to, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        m.id, m.topic, m.from_agent, m.to_agent,
                        json.dumps(m.payload, ensure_ascii=False, default=str),
                        m.correlation_id, m.reply_to, m.timestamp,
                    )
                    for m in messages
                ],
            )
            conn.commit()

    def load_recent(self, topic_pattern: str = "*", limit: int = 200) -> list[AgentMessage]:
        with self._connect() as conn:
            if topic_pattern == "*":
                rows = conn.execute(
                    "SELECT * FROM messages ORDER BY timestamp DESC LIMIT ?", (limit,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM messages WHERE topic GLOB ? ORDER BY timestamp DESC LIMIT ?",
                    (topic_pattern.replace("*", "*"), limit),
                ).fetchall()
        return [
            AgentMessage(
                id=str(r["id"]),
                topic=str(r["topic"]),
                from_agent=str(r["from_agent"]),
                to_agent=str(r["to_agent"]),
                payload=json.loads(str(r["payload"] or "{}")),
                correlation_id=str(r["correlation_id"] or ""),
                reply_to=str(r["reply_to"] or ""),
                timestamp=float(r["timestamp"]),
            )
            for r in rows
        ]

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            topics = conn.execute("SELECT COUNT(DISTINCT topic) FROM messages").fetchone()[0]
        return {"total_messages": int(total), "distinct_topics": int(topics), "db_path": self._db_path}


# ── Agent Message Bus ───────────────────────────────────────────────────────


class AgentMessageBus:
    """Singleton message bus for inter-agent communication.

    Publish-subscribe with fnmatch topic patterns.
    Async-safe: all mutations go through an asyncio.Lock.

    Usage:
        bus = get_message_bus()
        await bus.subscribe("agent-a", "task.result.*", my_handler)
        await bus.publish(AgentMessage(topic="task.result.done", from_agent="b", payload={...}))
    """

    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []
        self._buffers: dict[str, _RingBuffer] = {}
        self._lock = asyncio.Lock()
        self._store = _MessageStore(
            resolve_elyan_data_dir() / "multi_agent" / "message_bus.sqlite3"
        )
        self._flush_queue: list[AgentMessage] = []
        self._flush_task: asyncio.Task[None] | None = None
        self._stats = _BusStats()

    # ── Publish ──────────────────────────────────────────────────────────

    async def publish(self, message: AgentMessage) -> None:
        """Publish a message to the bus.

        Delivery semantics:
        1. Append to ring buffer (topic-keyed)
        2. Fan-out to matching subscribers (async, non-blocking)
        3. Queue for SQLite persistence (batched flush)
        """
        async with self._lock:
            # Buffer
            buf = self._buffers.get(message.topic)
            if buf is None:
                buf = _RingBuffer()
                self._buffers[message.topic] = buf
            buf.append(message)

            # Persistence queue
            self._flush_queue.append(message)
            self._ensure_flush_loop()

            # Stats
            self._stats.messages_published += 1

        # Fan-out (outside lock to avoid holding it during handler execution)
        await self._fan_out(message)

        slog.log_event(
            "message_published",
            {
                "id": message.id,
                "topic": message.topic,
                "from": message.from_agent,
                "to": message.to_agent or "*",
                "correlation": message.correlation_id,
            },
        )

    async def _fan_out(self, message: AgentMessage) -> None:
        """Deliver message to all matching subscribers."""
        handlers: list[MessageHandler] = []
        for sub in self._subscriptions:
            if not fnmatch(message.topic, sub.topic_pattern):
                continue
            if message.to_agent and message.to_agent != sub.subscriber_id:
                continue  # directed message, not for this subscriber
            handlers.append(sub.handler)

        for handler in handlers:
            try:
                await handler(message)
                self._stats.messages_delivered += 1
            except Exception as exc:
                self._stats.delivery_errors += 1
                slog.log_event(
                    "message_delivery_error",
                    {"topic": message.topic, "error": str(exc)},
                    level="warning",
                )

    # ── Subscribe ────────────────────────────────────────────────────────

    async def subscribe(
        self,
        subscriber_id: str,
        topic_pattern: str,
        handler: MessageHandler,
    ) -> None:
        """Register a handler for messages matching the topic pattern.

        Pattern uses fnmatch: "task.*" matches "task.assign", "task.result", etc.
        """
        async with self._lock:
            # Deduplicate: same subscriber + same pattern → replace handler
            self._subscriptions = [
                s for s in self._subscriptions
                if not (s.subscriber_id == subscriber_id and s.topic_pattern == topic_pattern)
            ]
            self._subscriptions.append(
                _Subscription(
                    subscriber_id=subscriber_id,
                    topic_pattern=topic_pattern,
                    handler=handler,
                )
            )
        slog.log_event(
            "subscription_added",
            {"subscriber": subscriber_id, "pattern": topic_pattern},
        )

    async def unsubscribe(self, subscriber_id: str, topic_pattern: str = "*") -> int:
        """Remove subscriptions. Returns number removed."""
        async with self._lock:
            before = len(self._subscriptions)
            if topic_pattern == "*":
                self._subscriptions = [
                    s for s in self._subscriptions if s.subscriber_id != subscriber_id
                ]
            else:
                self._subscriptions = [
                    s for s in self._subscriptions
                    if not (s.subscriber_id == subscriber_id and s.topic_pattern == topic_pattern)
                ]
            removed = before - len(self._subscriptions)
        return removed

    # ── Request-Reply ────────────────────────────────────────────────────

    async def request(
        self,
        message: AgentMessage,
        *,
        timeout_s: float = 30.0,
    ) -> AgentMessage | None:
        """Send a message and wait for a reply on the reply_to topic.

        Returns the first reply message, or None on timeout.
        Uses an asyncio.Event for efficient waiting (no polling).
        """
        reply_topic = message.reply_to or f"_reply.{message.id}"
        if not message.reply_to:
            message = AgentMessage(
                id=message.id,
                topic=message.topic,
                from_agent=message.from_agent,
                to_agent=message.to_agent,
                payload=message.payload,
                correlation_id=message.correlation_id,
                reply_to=reply_topic,
                timestamp=message.timestamp,
            )

        reply_box: list[AgentMessage] = []
        event = asyncio.Event()

        async def _catch_reply(msg: AgentMessage) -> None:
            reply_box.append(msg)
            event.set()

        await self.subscribe(f"_reply_{message.id}", reply_topic, _catch_reply)
        try:
            await self.publish(message)
            try:
                await asyncio.wait_for(event.wait(), timeout=timeout_s)
            except asyncio.TimeoutError:
                self._stats.request_timeouts += 1
                return None
            return reply_box[0] if reply_box else None
        finally:
            await self.unsubscribe(f"_reply_{message.id}")

    # ── Query ────────────────────────────────────────────────────────────

    def recent(self, topic: str, n: int = 50) -> list[AgentMessage]:
        """Get recent messages from the in-memory ring buffer."""
        buf = self._buffers.get(topic)
        return buf.recent(n) if buf else []

    def history(self, topic_pattern: str = "*", limit: int = 200) -> list[AgentMessage]:
        """Query persisted message history from SQLite."""
        return self._store.load_recent(topic_pattern, limit)

    # ── Flush loop ───────────────────────────────────────────────────────

    def _ensure_flush_loop(self) -> None:
        if self._flush_task is None or self._flush_task.done():
            self._flush_task = asyncio.ensure_future(self._flush_loop())

    async def _flush_loop(self) -> None:
        """Batch-flush queued messages to SQLite every 500ms."""
        while True:
            await asyncio.sleep(0.5)
            async with self._lock:
                batch = list(self._flush_queue)
                self._flush_queue.clear()
            if batch:
                try:
                    self._store.persist_batch(batch)
                except Exception as exc:
                    slog.log_event(
                        "flush_error", {"count": len(batch), "error": str(exc)}, level="error"
                    )
            if not self._flush_queue:
                break  # No new messages queued during flush — exit loop

    # ── Stats ────────────────────────────────────────────────────────────

    def stats(self) -> dict[str, Any]:
        store_stats = self._store.stats()
        return {
            "messages_published": self._stats.messages_published,
            "messages_delivered": self._stats.messages_delivered,
            "delivery_errors": self._stats.delivery_errors,
            "request_timeouts": self._stats.request_timeouts,
            "active_subscriptions": len(self._subscriptions),
            "buffer_topics": len(self._buffers),
            "buffer_total_messages": sum(len(b) for b in self._buffers.values()),
            **store_stats,
        }

    # ── Shutdown ─────────────────────────────────────────────────────────

    async def shutdown(self) -> None:
        """Flush remaining messages and stop the flush loop."""
        if self._flush_task and not self._flush_task.done():
            self._flush_task.cancel()
        async with self._lock:
            if self._flush_queue:
                try:
                    self._store.persist_batch(self._flush_queue)
                except Exception:
                    pass
                self._flush_queue.clear()


@dataclass
class _BusStats:
    messages_published: int = 0
    messages_delivered: int = 0
    delivery_errors: int = 0
    request_timeouts: int = 0


# ── Singleton ───────────────────────────────────────────────────────────────

_bus_instance: AgentMessageBus | None = None


def get_message_bus() -> AgentMessageBus:
    """Get or create the singleton AgentMessageBus."""
    global _bus_instance
    if _bus_instance is None:
        _bus_instance = AgentMessageBus()
    return _bus_instance


__all__ = ["AgentMessage", "AgentMessageBus", "MessageHandler", "get_message_bus"]
