"""
ELYAN Multi-Agent Orchestration v2 - Phase 7
Agent coordination, inter-agent messaging, collaborative planning, conflict resolution.
"""

import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set


class AgentRole(Enum):
    COORDINATOR = "coordinator"
    PLANNER = "planner"
    EXECUTOR = "executor"
    REVIEWER = "reviewer"
    RESEARCHER = "researcher"
    CODER = "coder"
    TESTER = "tester"
    DOCUMENTER = "documenter"
    SECURITY = "security"
    OPTIMIZER = "optimizer"


class TaskStatus(Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    REVIEW = "review"
    COMPLETED = "completed"
    FAILED = "failed"


class MessageType(Enum):
    TASK_ASSIGNMENT = "task_assignment"
    STATUS_UPDATE = "status_update"
    RESULT = "result"
    QUERY = "query"
    RESPONSE = "response"
    CONFLICT = "conflict"
    RESOLUTION = "resolution"
    HEARTBEAT = "heartbeat"
    HANDOFF = "handoff"


class Priority(Enum):
    CRITICAL = 1
    HIGH = 2
    MEDIUM = 3
    LOW = 4


@dataclass
class AgentProfile:
    agent_id: str
    name: str
    role: AgentRole
    capabilities: List[str]
    max_concurrent_tasks: int = 3
    current_tasks: int = 0
    performance_score: float = 1.0
    is_available: bool = True
    created_at: float = 0.0
    last_heartbeat: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def load(self) -> float:
        if self.max_concurrent_tasks == 0:
            return 1.0
        return self.current_tasks / self.max_concurrent_tasks

    @property
    def is_overloaded(self) -> bool:
        return self.load >= 0.9


@dataclass
class AgentMessage:
    message_id: str
    sender_id: str
    receiver_id: str
    message_type: MessageType
    content: Dict[str, Any]
    priority: Priority = Priority.MEDIUM
    timestamp: float = 0.0
    reply_to: Optional[str] = None
    requires_ack: bool = False
    acked: bool = False

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


@dataclass
class TaskPacket:
    task_id: str
    title: str
    description: str
    required_capabilities: List[str]
    priority: Priority = Priority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)
    result: Optional[Dict[str, Any]] = None
    created_at: float = 0.0
    started_at: float = 0.0
    completed_at: float = 0.0
    deadline: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def duration_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at) * 1000
        return 0.0


@dataclass
class CollaborativePlan:
    plan_id: str
    goal: str
    tasks: List[TaskPacket] = field(default_factory=list)
    parallel_waves: List[List[str]] = field(default_factory=list)
    created_at: float = 0.0
    status: str = "draft"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConflictRecord:
    conflict_id: str
    agents: List[str]
    resource: str
    description: str
    resolution: str = ""
    resolved: bool = False
    created_at: float = 0.0
    resolved_at: float = 0.0


class MessageBus:
    """Inter-agent message passing system."""

    def __init__(self):
        self._queues: Dict[str, List[AgentMessage]] = defaultdict(list)
        self._history: List[AgentMessage] = []
        self._subscribers: Dict[str, List[Callable]] = defaultdict(list)

    def send(self, message: AgentMessage):
        self._queues[message.receiver_id].append(message)
        self._history.append(message)
        for callback in self._subscribers.get(message.receiver_id, []):
            callback(message)

    def receive(self, agent_id: str, limit: int = 10) -> List[AgentMessage]:
        messages = self._queues.get(agent_id, [])[:limit]
        self._queues[agent_id] = self._queues.get(agent_id, [])[limit:]
        return messages

    def peek(self, agent_id: str) -> int:
        return len(self._queues.get(agent_id, []))

    def subscribe(self, agent_id: str, callback: Callable):
        self._subscribers[agent_id].append(callback)

    def broadcast(self, sender_id: str, agents: List[str], message_type: MessageType, content: Dict):
        for agent_id in agents:
            if agent_id != sender_id:
                msg = AgentMessage(
                    message_id=f"msg_{uuid.uuid4().hex[:8]}",
                    sender_id=sender_id,
                    receiver_id=agent_id,
                    message_type=message_type,
                    content=content,
                )
                self.send(msg)

    def get_history(self, agent_id: Optional[str] = None, limit: int = 50) -> List[AgentMessage]:
        if agent_id:
            filtered = [m for m in self._history if m.sender_id == agent_id or m.receiver_id == agent_id]
            return filtered[-limit:]
        return self._history[-limit:]


class TaskScheduler:
    """Assign tasks to agents based on capabilities and load."""

    def __init__(self):
        self._agents: Dict[str, AgentProfile] = {}
        self._tasks: Dict[str, TaskPacket] = {}

    def register_agent(self, agent: AgentProfile):
        self._agents[agent.agent_id] = agent

    def unregister_agent(self, agent_id: str):
        self._agents.pop(agent_id, None)

    def add_task(self, task: TaskPacket):
        self._tasks[task.task_id] = task

    def assign(self, task_id: str) -> Optional[str]:
        task = self._tasks.get(task_id)
        if not task:
            return None
        candidates = self._find_candidates(task)
        if not candidates:
            return None
        best = max(candidates, key=lambda a: self._score_agent(a, task))
        task.assigned_agent = best.agent_id
        task.status = TaskStatus.ASSIGNED
        best.current_tasks += 1
        return best.agent_id

    def complete_task(self, task_id: str, result: Optional[Dict] = None):
        task = self._tasks.get(task_id)
        if task and task.assigned_agent:
            task.status = TaskStatus.COMPLETED
            task.completed_at = time.time()
            task.result = result
            agent = self._agents.get(task.assigned_agent)
            if agent:
                agent.current_tasks = max(0, agent.current_tasks - 1)

    def fail_task(self, task_id: str, reason: str = ""):
        task = self._tasks.get(task_id)
        if task and task.assigned_agent:
            task.status = TaskStatus.FAILED
            task.result = {"error": reason}
            agent = self._agents.get(task.assigned_agent)
            if agent:
                agent.current_tasks = max(0, agent.current_tasks - 1)
                agent.performance_score = max(0.1, agent.performance_score - 0.05)

    def _find_candidates(self, task: TaskPacket) -> List[AgentProfile]:
        candidates = []
        for agent in self._agents.values():
            if not agent.is_available or agent.is_overloaded:
                continue
            if task.required_capabilities:
                agent_caps = set(agent.capabilities)
                required = set(task.required_capabilities)
                if not required.intersection(agent_caps):
                    continue
            candidates.append(agent)
        return candidates

    @staticmethod
    def _score_agent(agent: AgentProfile, task: TaskPacket) -> float:
        score = agent.performance_score
        score -= agent.load * 0.3
        agent_caps = set(agent.capabilities)
        required = set(task.required_capabilities) if task.required_capabilities else set()
        if required:
            overlap = len(agent_caps & required) / len(required)
            score += overlap * 0.5
        return score

    def get_queue(self) -> List[TaskPacket]:
        return [t for t in self._tasks.values() if t.status == TaskStatus.PENDING]

    def get_agent_tasks(self, agent_id: str) -> List[TaskPacket]:
        return [t for t in self._tasks.values() if t.assigned_agent == agent_id]

    def get_stats(self) -> Dict[str, Any]:
        all_tasks = list(self._tasks.values())
        by_status = defaultdict(int)
        for t in all_tasks:
            by_status[t.status.value] += 1
        return {
            "total_tasks": len(all_tasks),
            "by_status": dict(by_status),
            "active_agents": sum(1 for a in self._agents.values() if a.is_available),
            "total_agents": len(self._agents),
            "avg_agent_load": sum(a.load for a in self._agents.values()) / max(1, len(self._agents)),
        }


class ConflictResolver:
    """Resolve conflicts between agents competing for shared resources."""

    def __init__(self):
        self._conflicts: List[ConflictRecord] = []

    def detect_conflict(self, agents: List[str], resource: str, description: str) -> ConflictRecord:
        conflict = ConflictRecord(
            conflict_id=f"conf_{uuid.uuid4().hex[:8]}",
            agents=agents,
            resource=resource,
            description=description,
            created_at=time.time(),
        )
        self._conflicts.append(conflict)
        return conflict

    def resolve_by_priority(
        self,
        conflict: ConflictRecord,
        agent_priorities: Dict[str, int],
    ) -> str:
        winner = min(conflict.agents, key=lambda a: agent_priorities.get(a, 999))
        conflict.resolution = f"Resolved by priority: {winner} wins"
        conflict.resolved = True
        conflict.resolved_at = time.time()
        return winner

    def resolve_by_load(
        self,
        conflict: ConflictRecord,
        agent_loads: Dict[str, float],
    ) -> str:
        winner = min(conflict.agents, key=lambda a: agent_loads.get(a, 1.0))
        conflict.resolution = f"Resolved by load balancing: {winner} (lowest load)"
        conflict.resolved = True
        conflict.resolved_at = time.time()
        return winner

    def get_unresolved(self) -> List[ConflictRecord]:
        return [c for c in self._conflicts if not c.resolved]

    def get_history(self, limit: int = 20) -> List[ConflictRecord]:
        return self._conflicts[-limit:]


class CollaborativePlanner:
    """Create and manage collaborative execution plans."""

    def __init__(self):
        self._plans: Dict[str, CollaborativePlan] = {}

    def create_plan(self, goal: str, tasks: List[Dict[str, Any]]) -> CollaborativePlan:
        plan_id = f"plan_{uuid.uuid4().hex[:8]}"
        task_packets = []
        for i, t in enumerate(tasks):
            packet = TaskPacket(
                task_id=f"{plan_id}_t{i}",
                title=t.get("title", f"Task {i+1}"),
                description=t.get("description", ""),
                required_capabilities=t.get("capabilities", []),
                priority=Priority(t.get("priority", 3)),
                dependencies=t.get("dependencies", []),
                created_at=time.time(),
            )
            task_packets.append(packet)
        waves = self._compute_waves(task_packets)
        plan = CollaborativePlan(
            plan_id=plan_id,
            goal=goal,
            tasks=task_packets,
            parallel_waves=waves,
            created_at=time.time(),
            status="ready",
        )
        self._plans[plan_id] = plan
        return plan

    def _compute_waves(self, tasks: List[TaskPacket]) -> List[List[str]]:
        task_map = {t.task_id: t for t in tasks}
        completed: Set[str] = set()
        waves = []
        remaining = set(task_map.keys())
        max_iterations = len(tasks) + 1
        for _ in range(max_iterations):
            if not remaining:
                break
            wave = []
            for tid in list(remaining):
                task = task_map[tid]
                deps = set(task.dependencies)
                if deps.issubset(completed):
                    wave.append(tid)
            if not wave:
                wave = list(remaining)[:1]
            waves.append(wave)
            for tid in wave:
                remaining.discard(tid)
                completed.add(tid)
        return waves

    def get_plan(self, plan_id: str) -> Optional[CollaborativePlan]:
        return self._plans.get(plan_id)

    def list_plans(self) -> List[CollaborativePlan]:
        return list(self._plans.values())


class MultiAgentOrchestrator:
    """Main orchestrator coordinating all multi-agent components."""

    def __init__(self):
        self.message_bus = MessageBus()
        self.scheduler = TaskScheduler()
        self.conflict_resolver = ConflictResolver()
        self.planner = CollaborativePlanner()
        self._coordinator_id = "coordinator_main"

    def register_agent(
        self,
        name: str,
        role: AgentRole,
        capabilities: List[str],
        max_tasks: int = 3,
    ) -> AgentProfile:
        agent = AgentProfile(
            agent_id=f"agent_{uuid.uuid4().hex[:8]}",
            name=name,
            role=role,
            capabilities=capabilities,
            max_concurrent_tasks=max_tasks,
            created_at=time.time(),
            last_heartbeat=time.time(),
        )
        self.scheduler.register_agent(agent)
        return agent

    def submit_task(
        self,
        title: str,
        description: str,
        capabilities: Optional[List[str]] = None,
        priority: Priority = Priority.MEDIUM,
        dependencies: Optional[List[str]] = None,
    ) -> TaskPacket:
        task = TaskPacket(
            task_id=f"task_{uuid.uuid4().hex[:8]}",
            title=title,
            description=description,
            required_capabilities=capabilities or [],
            priority=priority,
            dependencies=dependencies or [],
            created_at=time.time(),
        )
        self.scheduler.add_task(task)
        assigned = self.scheduler.assign(task.task_id)
        if assigned:
            self.message_bus.send(AgentMessage(
                message_id=f"msg_{uuid.uuid4().hex[:8]}",
                sender_id=self._coordinator_id,
                receiver_id=assigned,
                message_type=MessageType.TASK_ASSIGNMENT,
                content={"task_id": task.task_id, "title": title},
                priority=priority,
            ))
        return task

    def submit_plan(self, goal: str, tasks: List[Dict[str, Any]]) -> CollaborativePlan:
        plan = self.planner.create_plan(goal, tasks)
        for task in plan.tasks:
            self.scheduler.add_task(task)
        for wave in plan.parallel_waves:
            for task_id in wave:
                self.scheduler.assign(task_id)
        return plan

    def complete_task(self, task_id: str, result: Optional[Dict] = None):
        self.scheduler.complete_task(task_id, result)

    def fail_task(self, task_id: str, reason: str = ""):
        self.scheduler.fail_task(task_id, reason)

    def get_status(self) -> Dict[str, Any]:
        return {
            "scheduler": self.scheduler.get_stats(),
            "pending_messages": sum(
                self.message_bus.peek(a) for a in self.scheduler._agents
            ),
            "unresolved_conflicts": len(self.conflict_resolver.get_unresolved()),
            "active_plans": len([p for p in self.planner.list_plans() if p.status != "completed"]),
        }
