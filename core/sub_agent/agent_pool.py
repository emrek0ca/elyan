"""
core/sub_agent/agent_pool.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Agent Pool Management (~150 lines)
Manage agent instances with load balancing and health monitoring.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Type, Any
from .base_agent import SubAgent, AgentConfig, ExecutionResult
from utils.logger import get_logger

logger = get_logger("agent_pool")


@dataclass
class PoolMetrics:
    """Metrics for agent pool."""
    total_agents: int = 0
    active_agents: int = 0
    idle_agents: int = 0
    busy_agents: int = 0
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    avg_response_time_ms: float = 0.0
    pool_utilization: float = 0.0
    timestamp: float = field(default_factory=time.time)


class AgentPool:
    """Manage a pool of agents."""

    def __init__(self, agent_class: Type[SubAgent], pool_size: int = 3, config: Optional[AgentConfig] = None):
        """Initialize agent pool."""
        self.agent_class = agent_class
        self.pool_size = pool_size
        self.config = config or AgentConfig()
        self.agents: List[SubAgent] = []
        self.agent_queues: Dict[str, asyncio.Queue] = {}
        self.metrics = PoolMetrics()
        self._lock = asyncio.Lock()

    async def initialize(self) -> bool:
        """Initialize agent pool."""
        try:
            logger.info(f"Initializing {self.agent_class.__name__} pool with {self.pool_size} agents")

            for i in range(self.pool_size):
                agent_config = AgentConfig(
                    agent_id=f"{self.config.agent_id}_pool_{i}",
                    name=f"{self.config.name}_Agent_{i}",
                    description=self.config.description,
                )
                agent = self.agent_class(agent_config)
                success = await agent.initialize()
                if success:
                    self.agents.append(agent)
                    self.agent_queues[agent.config.agent_id] = asyncio.Queue()

            self.metrics.total_agents = len(self.agents)
            logger.info(f"Initialized {len(self.agents)} agents")
            return len(self.agents) > 0
        except Exception as e:
            logger.error(f"Failed to initialize pool: {e}")
            return False

    async def execute(self, task_id: str, task_input: Dict[str, Any], timeout: Optional[float] = None) -> ExecutionResult:
        """Execute task using an available agent."""
        if not self.agents:
            return ExecutionResult(
                task_id=task_id,
                status="FAILED",
                error="No agents available",
            )

        # Find the agent with the smallest queue
        agent = min(self.agents, key=lambda a: self.agent_queues[a.config.agent_id].qsize())

        # Execute task
        result = await agent.execute(task_id, task_input, timeout)
        self.metrics.total_tasks += 1

        if result.is_success:
            self.metrics.completed_tasks += 1
        else:
            self.metrics.failed_tasks += 1

        return result

    async def execute_parallel(
        self,
        tasks: Dict[str, Dict[str, Any]],
        timeout: Optional[float] = None
    ) -> Dict[str, ExecutionResult]:
        """Execute multiple tasks in parallel."""
        results = {}
        coroutines = []

        for task_id, task_input in tasks.items():
            coroutines.append(self.execute(task_id, task_input, timeout))

        responses = await asyncio.gather(*coroutines, return_exceptions=True)

        for i, (task_id, _) in enumerate(tasks.items()):
            if isinstance(responses[i], Exception):
                results[task_id] = ExecutionResult(
                    task_id=task_id,
                    status="FAILED",
                    error=str(responses[i]),
                )
            else:
                results[task_id] = responses[i]

        return results

    async def shutdown(self) -> None:
        """Shutdown all agents."""
        logger.info(f"Shutting down {len(self.agents)} agents")
        for agent in self.agents:
            await agent.shutdown()
        self.agents.clear()

    def get_metrics(self) -> PoolMetrics:
        """Get pool metrics."""
        idle_count = sum(1 for agent in self.agents if agent.current_task_id is None)
        busy_count = len(self.agents) - idle_count

        self.metrics.idle_agents = idle_count
        self.metrics.busy_agents = busy_count
        self.metrics.active_agents = len(self.agents)
        self.metrics.pool_utilization = (
            busy_count / len(self.agents) if self.agents else 0.0
        )
        self.metrics.avg_response_time_ms = (
            self.metrics.total_tasks / max(1, self.metrics.completed_tasks)
            if self.metrics.total_tasks > 0 else 0.0
        )

        return self.metrics


class PoolManager:
    """Manage multiple agent pools."""

    def __init__(self):
        """Initialize pool manager."""
        self.pools: Dict[str, AgentPool] = {}
        self._lock = asyncio.Lock()

    async def register_pool(self, pool_name: str, pool: AgentPool) -> None:
        """Register an agent pool."""
        async with self._lock:
            self.pools[pool_name] = pool
            await pool.initialize()
            logger.info(f"Registered pool: {pool_name}")

    async def execute(
        self,
        pool_name: str,
        task_id: str,
        task_input: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> ExecutionResult:
        """Execute task on specific pool."""
        if pool_name not in self.pools:
            return ExecutionResult(
                task_id=task_id,
                status="FAILED",
                error=f"Pool not found: {pool_name}",
            )

        return await self.pools[pool_name].execute(task_id, task_input, timeout)

    async def execute_on_best_pool(
        self,
        task_id: str,
        task_input: Dict[str, Any],
        timeout: Optional[float] = None
    ) -> ExecutionResult:
        """Execute task on pool with best utilization."""
        if not self.pools:
            return ExecutionResult(
                task_id=task_id,
                status="FAILED",
                error="No pools available",
            )

        # Find pool with lowest utilization
        best_pool = min(self.pools.values(), key=lambda p: p.get_metrics().pool_utilization)
        return await best_pool.execute(task_id, task_input, timeout)

    async def shutdown(self) -> None:
        """Shutdown all pools."""
        logger.info(f"Shutting down {len(self.pools)} pools")
        for pool in self.pools.values():
            await pool.shutdown()
        self.pools.clear()

    def get_status(self) -> Dict[str, Any]:
        """Get overall status of all pools."""
        status = {"pools": {}}

        for pool_name, pool in self.pools.items():
            metrics = pool.get_metrics()
            status["pools"][pool_name] = {
                "total_agents": metrics.total_agents,
                "idle_agents": metrics.idle_agents,
                "busy_agents": metrics.busy_agents,
                "utilization": metrics.pool_utilization,
                "total_tasks": metrics.total_tasks,
                "completed_tasks": metrics.completed_tasks,
                "failed_tasks": metrics.failed_tasks,
            }

        return status


# Singleton instance
_pool_manager: Optional[PoolManager] = None


def get_pool_manager() -> PoolManager:
    """Get or create pool manager instance."""
    global _pool_manager
    if _pool_manager is None:
        _pool_manager = PoolManager()
    return _pool_manager


async def shutdown_pools() -> None:
    """Shutdown all pools."""
    global _pool_manager
    if _pool_manager:
        await _pool_manager.shutdown()
        _pool_manager = None
