from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.security.contracts import classify_value, contains_sensitive_data


@dataclass
class TeamTask:
    title: str
    specialist: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
    objective: str = ""
    success_criteria: List[str] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    gates: List[str] = field(default_factory=list)
    task_id: str = field(default_factory=lambda: f"team_task_{uuid.uuid4().hex[:8]}")
    status: str = "pending"
    result: Any = None
    retry_count: int = 0
    max_retries: int = 1
    notes: List[str] = field(default_factory=list)


@dataclass
class TeamMessage:
    from_agent: str
    to_agent: str
    body: str
    payload: Dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:10]}")


class SharedTaskBoard:
    """Lock-protected task board used by AgentTeam workers."""

    def __init__(self):
        self._lock = asyncio.Lock()
        self._tasks: Dict[str, TeamTask] = {}
        self._claims: Dict[str, str] = {}

    async def post_task(self, task: TeamTask) -> str:
        async with self._lock:
            self._tasks[task.task_id] = task
            return task.task_id

    async def claim_task(self, agent_id: str, task_id: str) -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            if task.status != "pending":
                return False
            if task_id in self._claims:
                return False
            self._claims[task_id] = str(agent_id)
            task.status = "running"
            return True

    async def complete_task(self, task_id: str, result: Any) -> None:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return
            task.status = "completed"
            task.result = result
            self._claims.pop(task_id, None)

    async def retry_task(self, task_id: str, note: str = "") -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.status = "pending"
            if note:
                task.notes.append(str(note))
            self._claims.pop(task_id, None)
            return True

    async def fail_task(self, task_id: str, result: Any = None, note: str = "") -> bool:
        async with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return False
            task.status = "failed"
            task.result = result
            if note:
                task.notes.append(str(note))
            self._claims.pop(task_id, None)
            return True

    async def get_available(self, agent_id: str) -> List[TeamTask]:
        _ = agent_id
        async with self._lock:
            done = {tid for tid, t in self._tasks.items() if t.status == "completed"}
            available: List[TeamTask] = []
            for task in self._tasks.values():
                if task.status != "pending":
                    continue
                deps = [d for d in task.depends_on if d]
                if all(dep in done for dep in deps):
                    available.append(task)
            return available

    async def snapshot(self) -> List[TeamTask]:
        async with self._lock:
            return list(self._tasks.values())


class TeamMessageBus:
    """Simple queue bus for inter-agent messages."""

    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}
        self._hydrated_message_ids: set[str] = set()

    def _queue(self, agent_id: str) -> asyncio.Queue:
        key = str(agent_id or "")
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
        return self._queues[key]

    @staticmethod
    def _to_handoff_packet(message: TeamMessage) -> Any:
        from core.multi_agent.handoff import AgentHandoffPacket

        handoff_payload = message.payload.get("handoff") if isinstance(message.payload.get("handoff"), dict) else None
        if handoff_payload:
            packet = AgentHandoffPacket.from_dict(handoff_payload)
            if not packet.handoff_id:
                packet.handoff_id = message.message_id
            if not packet.from_agent:
                packet.from_agent = message.from_agent
            if not packet.to_agent:
                packet.to_agent = message.to_agent
            if not packet.summary:
                packet.summary = message.body
            if not packet.integrity_hash:
                packet.integrity_hash = packet.compute_integrity_hash()
            return packet
        classification = classify_value(message.payload or {}, key="payload").value
        return AgentHandoffPacket(
            handoff_id=message.message_id,
            from_agent=message.from_agent,
            to_agent=message.to_agent,
            objective=str(message.payload.get("objective") or message.body),
            summary=message.body,
            constraints=[str(item) for item in list(message.payload.get("constraints") or []) if str(item).strip()],
            artifacts=[str(item) for item in list(message.payload.get("artifacts") or []) if str(item).strip()],
            memory_refs=[str(item) for item in list(message.payload.get("memory_refs") or []) if str(item).strip()],
            metadata={"payload": dict(message.payload or {})},
            classification=classification,
            provenance={"channel": "agent_bus", "message_id": message.message_id},
            cloud_allowed=bool(message.payload.get("cloud_allowed", not contains_sensitive_data(message.payload or {}))),
            requires_redaction=contains_sensitive_data(message.payload or {}),
            created_at=float(message.ts or time.time()),
        )

    async def send(self, from_agent: str, to_agent: str, message: TeamMessage) -> None:
        from core.multi_agent.handoff import get_handoff_store

        msg = TeamMessage(
            message_id=str(message.message_id or f"msg_{uuid.uuid4().hex[:10]}"),
            from_agent=str(from_agent or message.from_agent),
            to_agent=str(to_agent or message.to_agent),
            body=str(message.body),
            payload=dict(message.payload or {}),
            ts=float(message.ts or time.time()),
        )
        packet = self._to_handoff_packet(msg)
        get_handoff_store().record(packet)
        self._hydrated_message_ids.add(msg.message_id)
        await self._queue(msg.to_agent).put(msg)

    async def broadcast(self, from_agent: str, message: TeamMessage) -> None:
        sender = str(from_agent or message.from_agent)
        for agent_id in list(self._queues.keys()):
            if agent_id == sender:
                continue
            await self.send(sender, agent_id, message)

    async def hydrate(self, agent_id: str, limit: int = 50) -> int:
        from core.multi_agent.handoff import get_handoff_store

        loaded = 0
        for packet in get_handoff_store().list_pending(agent_id, limit=limit):
            if packet.handoff_id in self._hydrated_message_ids:
                continue
            msg = TeamMessage(
                message_id=packet.handoff_id,
                from_agent=packet.from_agent,
                to_agent=packet.to_agent,
                body=packet.summary or packet.objective,
                payload={"handoff": packet.to_dict(), **dict(packet.metadata.get("payload") or {})},
                ts=packet.created_at,
            )
            self._hydrated_message_ids.add(msg.message_id)
            await self._queue(msg.to_agent).put(msg)
            loaded += 1
        return loaded

    async def receive(self, agent_id: str, timeout: int = 30) -> Optional[TeamMessage]:
        from core.multi_agent.handoff import get_handoff_store

        await self.hydrate(agent_id, limit=20)
        try:
            message = await asyncio.wait_for(self._queue(agent_id).get(), timeout=max(1, int(timeout or 30)))
            if message and message.message_id:
                get_handoff_store().mark_delivered(message.message_id)
            return message
        except asyncio.TimeoutError:
            return None


# Process-level singleton AgentBus
_agent_bus: Optional["TeamMessageBus"] = None


def get_agent_bus() -> "TeamMessageBus":
    """Get or create the process-level singleton AgentBus."""
    global _agent_bus
    if _agent_bus is None:
        _agent_bus = TeamMessageBus()
    return _agent_bus


def reset_agent_bus() -> None:
    """Reset the singleton AgentBus (for testing/teardown)."""
    global _agent_bus
    _agent_bus = None


__all__ = ["TeamTask", "TeamMessage", "SharedTaskBoard", "TeamMessageBus", "get_agent_bus", "reset_agent_bus"]
