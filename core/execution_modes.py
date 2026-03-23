"""
Focused-Diffuse Execution Modes — Cognitive Toggle.

Implements two complementary execution modes:
- FOCUSED: Exploitation via Q-learning (high success probability actions)
- DIFFUSE: Exploration via parallel brainstorming (discovery + alternatives)

Principles:
- Focused mode: Fast, proven actions (latency < 10ms)
- Diffuse mode: Async parallel proposals from multiple agents
- Dynamic switching: Success → stay focused, repeated failure → diffuse
- Pomodoro timer: 5 min focused blocks with 5s breaks

Based on dual-process cognition theory (Kahneman) and Q-learning exploitation/exploration.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from enum import Enum
import asyncio
import logging
import time

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Data Models
# ============================================================================

class ExecutionMode(Enum):
    """Execution mode types"""
    FOCUSED = "focused"    # Exploitation: high-confidence, routine actions
    DIFFUSE = "diffuse"    # Exploration: brainstorming, parallel proposals
    SLEEP = "sleep"        # Offline consolidation (not used in this module)


@dataclass
class ModeMetrics:
    """Track performance metrics per mode"""
    mode: ExecutionMode
    action_count: int = 0
    success_count: int = 0
    avg_latency_ms: float = 0.0
    failure_rate: float = 0.0


# ============================================================================
# Focused Mode Engine
# ============================================================================

class FocusedModeEngine:
    """
    Focused (exploitation) mode using Q-learning table lookup.

    Selects actions with highest Q-value for routine, high-confidence execution.
    Guarantees low latency (< 10ms per action).

    Q-table structure:
    {
        "task_type": {
            "action_1": 0.95,  # Success probability
            "action_2": 0.85,
        },
        ...
    }
    """

    def __init__(self, q_table: Dict[str, Dict[str, float]]):
        """
        Initialize focused mode engine.

        Args:
            q_table: Dict mapping task_type → {action → q_value}
        """
        self.q_table = q_table
        self.metrics = ModeMetrics(mode=ExecutionMode.FOCUSED)

    def _best_action(self, task_type: str) -> str:
        """
        Select action with highest Q-value for task type.

        Args:
            task_type: The type of task to perform

        Returns:
            Action name with highest Q-value, or "fallback" if not found
        """
        if task_type not in self.q_table:
            logger.debug(f"Task type '{task_type}' not in Q-table, returning fallback")
            return "fallback"

        actions = self.q_table[task_type]
        if not actions:
            return "fallback"

        # Return action with highest Q-value
        best_action = max(actions.items(), key=lambda x: x[1])[0]
        logger.debug(f"Selected action '{best_action}' for task '{task_type}'")
        return best_action

    def get_metrics(self) -> ModeMetrics:
        """Get performance metrics for focused mode."""
        return self.metrics

    def update_q_value(self, task_type: str, action: str, new_q_value: float) -> None:
        """
        Update Q-value for an action (post-execution learning).

        Args:
            task_type: Task type
            action: Action name
            new_q_value: Updated Q-value (0.0 to 1.0)
        """
        if task_type not in self.q_table:
            self.q_table[task_type] = {}
        self.q_table[task_type][action] = new_q_value
        logger.debug(f"Updated Q-value: {task_type}/{action} = {new_q_value}")


# ============================================================================
# Diffuse Mode Engine
# ============================================================================

class DiffuseBackgroundEngine:
    """
    Diffuse (exploration) mode with parallel agent brainstorming.

    Spawns multiple agents asynchronously to propose alternative solutions.
    Implements timeout handling to prevent hangs from slow agents.

    Agents must implement:
    - async propose_solution(problem: str) → Dict
    - async collaborate(other_agent, problem: str) → Dict
    """

    def __init__(self, agents: Dict[str, Any], timeout_seconds: float = 2.0):
        """
        Initialize diffuse mode engine.

        Args:
            agents: Dict mapping agent_id → agent_instance
            timeout_seconds: Max time to wait for each agent (default 2.0s)
        """
        self.agents = agents
        self.timeout = timeout_seconds
        self.metrics = ModeMetrics(mode=ExecutionMode.DIFFUSE)

    async def explore_alternative_solutions(self, problem: str) -> List[Dict]:
        """
        Explore alternative solutions via parallel agent proposals.

        Spawns all agents asynchronously to propose solutions.
        Uses timeout to prevent hangs from slow agents.
        Returns successful proposals only.

        Args:
            problem: Problem description for agents to solve

        Returns:
            List of solution proposals from agents (len >= 1)
        """
        if not self.agents:
            logger.warning("No agents available for exploration")
            return []

        # Create tasks for all agents
        tasks = []
        for agent_id, agent in self.agents.items():
            task = asyncio.create_task(
                self._safe_propose(agent_id, agent, problem)
            )
            tasks.append(task)

        # Wait for all tasks with timeout
        done, pending = await asyncio.wait(
            tasks,
            timeout=self.timeout,
            return_when=asyncio.ALL_COMPLETED
        )

        # Cancel any pending tasks (slow agents)
        for task in pending:
            task.cancel()
            logger.debug("Cancelled slow agent proposal")

        # Collect results from completed tasks
        solutions = []
        for task in done:
            try:
                result = task.result()
                if result is not None:
                    solutions.append(result)
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.debug(f"Agent proposal failed: {e}")

        logger.info(f"Diffuse exploration: {len(solutions)} proposals from {len(self.agents)} agents")
        return solutions

    async def _safe_propose(
        self,
        agent_id: str,
        agent: Any,
        problem: str
    ) -> Optional[Dict]:
        """
        Safely call agent's propose_solution method with timeout.

        Args:
            agent_id: Agent identifier
            agent: Agent instance
            problem: Problem to solve

        Returns:
            Solution proposal from agent, or None on failure
        """
        try:
            if not hasattr(agent, 'propose_solution'):
                logger.debug(f"Agent {agent_id} has no propose_solution method")
                return None

            # Call with implicit timeout from explore_alternative_solutions
            solution = await agent.propose_solution(problem)
            logger.debug(f"Agent {agent_id} proposed solution")
            return solution

        except asyncio.CancelledError:
            raise  # Let parent handle cancellation
        except Exception as e:
            logger.debug(f"Agent {agent_id} proposal error: {e}")
            return None

    async def brainstorm_combinations(self, problem: str) -> List[Dict]:
        """
        Brainstorm creative combinations of agent pairs.

        Tries unexpected agent combinations for creative problem-solving.

        Args:
            problem: Problem to solve

        Returns:
            List of creative combination proposals
        """
        if len(self.agents) < 2:
            logger.debug("Need at least 2 agents for brainstorm combinations")
            return []

        agent_list = list(self.agents.values())
        combinations = []

        # Create pair-wise collaborations
        for i in range(len(agent_list)):
            for j in range(i + 1, len(agent_list)):
                agent_a = agent_list[i]
                agent_b = agent_list[j]

                try:
                    if hasattr(agent_a, 'collaborate'):
                        result = await asyncio.wait_for(
                            agent_a.collaborate(agent_b, problem),
                            timeout=self.timeout
                        )
                        if result:
                            combinations.append(result)
                except (asyncio.TimeoutError, Exception) as e:
                    logger.debug(f"Collaboration failed: {e}")

        logger.info(f"Brainstorm combinations: {len(combinations)} ideas")
        return combinations

    def get_metrics(self) -> ModeMetrics:
        """Get performance metrics for diffuse mode."""
        return self.metrics


# ============================================================================
# Mode Selector (Helper)
# ============================================================================

class ModeSelector:
    """Helper to decide between focused and diffuse modes based on context."""

    @staticmethod
    def should_switch_to_diffuse(
        consecutive_failures: int,
        failure_rate: float,
        failure_threshold: int = 3
    ) -> bool:
        """
        Decide if should switch to diffuse mode.

        Switches when:
        - 3+ consecutive failures with same error, OR
        - >70% failure rate in recent window

        Args:
            consecutive_failures: Number of consecutive failures
            failure_rate: Failure rate (0.0 to 1.0)
            failure_threshold: Threshold for consecutive failures

        Returns:
            True if should switch to diffuse
        """
        if consecutive_failures >= failure_threshold:
            return True
        if failure_rate >= 0.7:
            return True
        return False

    @staticmethod
    def should_return_to_focused(
        recent_successes: int,
        success_threshold: int = 2
    ) -> bool:
        """
        Decide if should return to focused mode.

        Returns to focused after 2+ consecutive successes in diffuse mode.

        Args:
            recent_successes: Number of recent successes
            success_threshold: Threshold for return

        Returns:
            True if should return to focused
        """
        return recent_successes >= success_threshold


if __name__ == "__main__":
    # Simple smoke test
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    # Test Focused Mode
    q_table = {
        "read": {"file.read": 0.95, "memory.read": 0.85},
        "write": {"file.write": 0.90, "db.write": 0.70},
    }
    focused = FocusedModeEngine(q_table)
    print(f"Best action for 'read': {focused._best_action('read')}")
    print(f"Best action for 'unknown': {focused._best_action('unknown')}")

    # Test Diffuse Mode
    class MockAgent:
        def __init__(self, name: str):
            self.name = name

        async def propose_solution(self, problem: str):
            await asyncio.sleep(0.01)
            return {"agent": self.name, "solution": f"{self.name}_fix"}

    agents = {
        "cache_agent": MockAgent("cache"),
        "retry_agent": MockAgent("retry"),
    }

    diffuse = DiffuseBackgroundEngine(agents)
    solutions = asyncio.run(diffuse.explore_alternative_solutions("rate_limit"))
    print(f"Diffuse solutions: {len(solutions)} proposals")
