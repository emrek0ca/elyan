from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TeamTask:
    title: str
    specialist: str
    action: str
    params: Dict[str, Any] = field(default_factory=dict)
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

    def _queue(self, agent_id: str) -> asyncio.Queue:
        key = str(agent_id or "")
        if key not in self._queues:
            self._queues[key] = asyncio.Queue()
        return self._queues[key]

    async def send(self, from_agent: str, to_agent: str, message: TeamMessage) -> None:
        msg = TeamMessage(
            from_agent=str(from_agent or message.from_agent),
            to_agent=str(to_agent or message.to_agent),
            body=str(message.body),
            payload=dict(message.payload or {}),
        )
        await self._queue(msg.to_agent).put(msg)

    async def broadcast(self, from_agent: str, message: TeamMessage) -> None:
        sender = str(from_agent or message.from_agent)
        for agent_id in list(self._queues.keys()):
            if agent_id == sender:
                continue
            await self.send(sender, agent_id, message)

    async def receive(self, agent_id: str, timeout: int = 30) -> Optional[TeamMessage]:
        try:
            return await asyncio.wait_for(self._queue(agent_id).get(), timeout=max(1, int(timeout or 30)))
        except asyncio.TimeoutError:
            return None


__all__ = ["TeamTask", "TeamMessage", "SharedTaskBoard", "TeamMessageBus"]
