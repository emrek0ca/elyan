"""Tests for core/multi_agent/message_bus.py — Agent Message Bus."""
from __future__ import annotations

import asyncio

import pytest

from core.multi_agent.message_bus import AgentMessage, AgentMessageBus


@pytest.fixture
def bus(tmp_path, monkeypatch):
    """Fresh bus instance with temp SQLite path."""
    monkeypatch.setattr(
        "core.multi_agent.message_bus.resolve_elyan_data_dir",
        lambda: tmp_path,
    )
    return AgentMessageBus()


# ── Message dataclass ────────────────────────────────────────────────────────


def test_message_roundtrip():
    msg = AgentMessage(
        topic="task.assign",
        from_agent="orchestrator",
        to_agent="builder",
        payload={"objective": "write code"},
        correlation_id="c1",
    )
    d = msg.to_dict()
    restored = AgentMessage.from_dict(d)
    assert restored.topic == msg.topic
    assert restored.from_agent == msg.from_agent
    assert restored.payload == msg.payload
    assert restored.correlation_id == msg.correlation_id


def test_message_immutable():
    msg = AgentMessage(topic="x", from_agent="a", payload={})
    with pytest.raises(AttributeError):
        msg.topic = "y"  # frozen=True


# ── Publish / Subscribe ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_delivers_to_subscriber(bus):
    received = []

    async def handler(msg: AgentMessage):
        received.append(msg)

    await bus.subscribe("agent-a", "task.*", handler)
    await bus.publish(AgentMessage(topic="task.assign", from_agent="orch", payload={"x": 1}))

    assert len(received) == 1
    assert received[0].payload == {"x": 1}


@pytest.mark.asyncio
async def test_directed_message_only_reaches_target(bus):
    received_a = []
    received_b = []

    async def handler_a(msg):
        received_a.append(msg)

    async def handler_b(msg):
        received_b.append(msg)

    await bus.subscribe("agent-a", "task.*", handler_a)
    await bus.subscribe("agent-b", "task.*", handler_b)

    # Directed to agent-b only
    await bus.publish(AgentMessage(
        topic="task.assign", from_agent="orch", to_agent="agent-b", payload={},
    ))

    assert len(received_a) == 0
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_broadcast_reaches_all_subscribers(bus):
    received_a = []
    received_b = []

    async def ha(msg):
        received_a.append(msg)

    async def hb(msg):
        received_b.append(msg)

    await bus.subscribe("a", "event.*", ha)
    await bus.subscribe("b", "event.*", hb)

    await bus.publish(AgentMessage(topic="event.update", from_agent="sys", payload={}))

    assert len(received_a) == 1
    assert len(received_b) == 1


@pytest.mark.asyncio
async def test_pattern_matching(bus):
    received = []

    async def handler(msg):
        received.append(msg.topic)

    await bus.subscribe("a", "task.result.*", handler)

    await bus.publish(AgentMessage(topic="task.result.done", from_agent="x", payload={}))
    await bus.publish(AgentMessage(topic="task.assign.new", from_agent="x", payload={}))

    assert received == ["task.result.done"]


@pytest.mark.asyncio
async def test_unsubscribe(bus):
    received = []

    async def handler(msg):
        received.append(msg)

    await bus.subscribe("a", "x.*", handler)
    removed = await bus.unsubscribe("a", "x.*")
    assert removed == 1

    await bus.publish(AgentMessage(topic="x.y", from_agent="z", payload={}))
    assert len(received) == 0


# ── Ring buffer ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recent_returns_buffer(bus):
    for i in range(5):
        await bus.publish(AgentMessage(topic="t", from_agent="a", payload={"i": i}))

    recent = bus.recent("t", 3)
    assert len(recent) == 3
    assert recent[-1].payload["i"] == 4


# ── Request-reply ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_request_reply(bus):
    async def responder(msg: AgentMessage):
        if msg.reply_to:
            await bus.publish(AgentMessage(
                topic=msg.reply_to,
                from_agent="responder",
                payload={"answer": 42},
                correlation_id=msg.correlation_id,
            ))

    await bus.subscribe("responder", "question.*", responder)

    reply = await bus.request(
        AgentMessage(topic="question.math", from_agent="asker", payload={"q": "6*7"}),
        timeout_s=5.0,
    )

    assert reply is not None
    assert reply.payload["answer"] == 42


@pytest.mark.asyncio
async def test_request_timeout(bus):
    # No responder registered
    reply = await bus.request(
        AgentMessage(topic="void.topic", from_agent="a", payload={}),
        timeout_s=0.1,
    )
    assert reply is None


# ── Stats ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_stats(bus):
    await bus.publish(AgentMessage(topic="s", from_agent="a", payload={}))
    stats = bus.stats()
    assert stats["messages_published"] >= 1
    assert stats["buffer_topics"] >= 1


# ── Handler error isolation ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_handler_error_does_not_break_bus(bus):
    good_received = []

    async def bad_handler(msg):
        raise RuntimeError("boom")

    async def good_handler(msg):
        good_received.append(msg)

    await bus.subscribe("bad", "e.*", bad_handler)
    await bus.subscribe("good", "e.*", good_handler)

    await bus.publish(AgentMessage(topic="e.x", from_agent="a", payload={}))

    assert len(good_received) == 1  # Good handler still received the message
