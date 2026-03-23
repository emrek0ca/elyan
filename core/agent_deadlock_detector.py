"""
Deadlock Detector — Einstellung Breaker.

Detects when agents are stuck in failing loops (Einstellung effect) and
suggests recovery actions to break the cycle.

Patterns detected:
- 3+ consecutive failures with same error code
- Timeout cascades
- Resource exhaustion loops
- Permission denied patterns

Recovery strategies:
- Switch execution mode (Focused → Diffuse)
- Escalate to human approval
- Queue for later retry with backoff
- Use fallback capability
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from collections import deque
import logging

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================

@dataclass
class FailurePattern:
    """
    Records a pattern of repeated failures for an agent.

    Tracks:
    - agent_id: Which agent failed
    - error_code: Type of error (RATE_LIMIT, TIMEOUT, etc.)
    - consecutive_failures: Count of successive failures
    - last_attempted_action: Most recent action
    - attempted_alternative_actions: Fallback strategies tried
    """
    agent_id: str
    error_code: str
    consecutive_failures: int
    last_attempted_action: str
    attempted_alternative_actions: List[str] = field(default_factory=list)


# ============================================================================
# Deadlock Detector Class
# ============================================================================

class DeadlockDetector:
    """
    Detects and breaks agent deadlock cycles (Einstellung effect).

    When an agent is stuck repeating the same failing operation,
    the detector triggers recovery actions:
    1. Switch to diffuse mode (brainstorm)
    2. Escalate to human approval
    3. Queue for retry with exponential backoff
    4. Use fallback capability
    """

    def __init__(self, failure_window_size: int = 5, failure_threshold: int = 3):
        """
        Initialize deadlock detector.

        Args:
            failure_window_size: Number of recent results to track per agent
            failure_threshold: How many consecutive failures trigger detection
        """
        self.window_size = failure_window_size
        self.threshold = failure_threshold

        # Track failure history per agent
        # Key: agent_id, Value: deque of ExecutionResult objects
        self.failure_history: Dict[str, deque] = {}

    def is_stuck(self, task_result: Any) -> bool:
        """
        Check if an agent is stuck in a failing loop.

        Args:
            task_result: ExecutionResult from latest task

        Returns:
            True if agent is stuck, False otherwise
        """
        agent_id = task_result.agent_id

        # Initialize history for new agents
        if agent_id not in self.failure_history:
            self.failure_history[agent_id] = deque(maxlen=self.window_size)

        history = self.failure_history[agent_id]
        history.append(task_result)

        # Check conditions for "stuck"
        if len(history) < self.threshold:
            return False  # Not enough data yet

        # Condition 1: Recent N-1 CONSECUTIVE failures all have same error code
        # Count consecutive failures from the end
        consecutive_failures = []
        for r in reversed(list(history)):
            if r.success:
                break  # Success breaks the chain
            consecutive_failures.append(r)

        if len(consecutive_failures) >= self.threshold - 1:
            error_codes = [f.error_code for f in reversed(consecutive_failures)]
            # All same error code?
            if len(set(error_codes)) == 1:
                logger.warning(
                    f"Agent {agent_id} stuck: {len(consecutive_failures)} consecutive {error_codes[0]} errors"
                )
                return True

        # Condition 2: Failure rate in window > 70% AND consecutive failures at the end
        # But ONLY if recent consecutive failures cause the high rate
        # (don't trigger if a success broke the pattern earlier)
        if len(consecutive_failures) >= self.threshold:
            # We already have threshold consecutive failures, but check the failure rate too
            failure_rate = sum(1 for r in history if not r.success) / len(history)
            if failure_rate >= 0.7:
                error_codes = [f.error_code for f in reversed(consecutive_failures)]
                if len(set(error_codes)) == 1:
                    logger.warning(
                        f"Agent {agent_id} stuck: {failure_rate*100:.0f}% failure rate ({len(consecutive_failures)} consecutive {error_codes[0]} errors)"
                    )
                    return True

        return False

    def suggest_recovery_action(
        self,
        stuck_agent: str,
        available_agents: List[str] = None,
        error_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Suggest recovery action for a stuck agent.

        Args:
            stuck_agent: Agent ID that is stuck
            available_agents: List of alternative agents to use
            error_code: Explicit error code (if not in history)

        Returns:
            Dict with action, reason, and metadata
        """
        if available_agents is None:
            available_agents = []

        history = self.failure_history.get(stuck_agent, deque())
        last_error = error_code  # Use explicit error code if provided

        # If no explicit error code, try to get from history
        if not last_error and history:
            recent_failures = [r for r in history if not r.success]
            if recent_failures:
                last_error = recent_failures[-1].error_code

        # If still no error code, try to infer from agent_id
        if not last_error:
            # Heuristic fallback: infer error type from agent name
            agent_lower = stuck_agent.lower()
            if "api" in agent_lower or "rate" in agent_lower:
                last_error = "RATE_LIMIT"
            elif "slow" in agent_lower or "timeout" in agent_lower:
                last_error = "TIMEOUT"
            elif "fs" in agent_lower or "file" in agent_lower or "permission" in agent_lower:
                last_error = "PERMISSION_DENIED"
            else:
                # Default recovery when no specific error is known
                return {
                    "action": "escalate_to_human_approval",
                    "reason": "Unknown agent state; request manual intervention",
                    "requires_manual_intervention": True,
                    "fallback": "Request human decision"
                }

        # Choose recovery based on error type
        if last_error == "RATE_LIMIT":
            return {
                "action": "switch_to_diffuse_mode",
                "reason": "API rate limit; implement caching/queuing",
                "fallback_agents": available_agents,
                "strategy": "exponential_backoff",
                "next_retry_delay": 5.0  # seconds
            }

        elif last_error == "TIMEOUT":
            return {
                "action": "increase_timeout_and_retry",
                "reason": "Task too slow; increase timeout",
                "suggested_timeout": 60,  # seconds
                "strategy": "chunking",
                "fallback": "Queue for background processing"
            }

        elif last_error == "PERMISSION_DENIED":
            return {
                "action": "escalate_to_approval",
                "reason": "Permission required; request approval",
                "requires_manual_intervention": True,
                "fallback": "Use read-only mode or skip"
            }

        elif last_error == "RESOURCE_EXHAUSTED":
            return {
                "action": "switch_to_diffuse_mode",
                "reason": "Resource limit reached; reduce parallelism",
                "strategy": "rate_limiting",
                "fallback": "Queue for later when resources available"
            }

        else:
            # Generic recovery
            return {
                "action": "escalate_to_human_approval",
                "reason": f"Unknown error: {last_error}",
                "requires_manual_intervention": True,
                "fallback": "Request human decision"
            }

    def get_failure_summary(self, agent_id: str) -> Dict[str, Any]:
        """
        Get summary of failures for an agent.

        Args:
            agent_id: Agent to summarize

        Returns:
            Dict with failure counts and patterns
        """
        history = self.failure_history.get(agent_id, deque())

        if not history:
            return {"agent_id": agent_id, "failure_count": 0}

        failures = [r for r in history if not r.success]
        error_codes = [f.error_code for f in failures]

        return {
            "agent_id": agent_id,
            "total_attempts": len(history),
            "failure_count": len(failures),
            "failure_rate": len(failures) / len(history) if history else 0,
            "most_common_error": max(set(error_codes), key=error_codes.count) if error_codes else None,
            "recent_errors": error_codes[-3:] if error_codes else [],
        }

    def reset_agent_history(self, agent_id: str) -> None:
        """
        Clear failure history for an agent (used after successful recovery).

        Args:
            agent_id: Agent to reset
        """
        if agent_id in self.failure_history:
            self.failure_history[agent_id].clear()
            logger.info(f"Reset failure history for agent {agent_id}")

    def reset_all(self) -> None:
        """Clear all failure histories."""
        self.failure_history.clear()
        logger.info("Reset all failure histories")


# ============================================================================
# Module Helpers
# ============================================================================

def is_retryable_error(error_code: str) -> bool:
    """
    Check if error is worth retrying.

    Args:
        error_code: Error type

    Returns:
        True if retry could help, False if retrying would repeat failure
    """
    retryable = {
        "TIMEOUT",
        "RATE_LIMIT",
        "CONNECTION_TIMEOUT",
        "TEMPORARY_FAILURE",
    }
    return error_code in retryable


def is_escalation_error(error_code: str) -> bool:
    """
    Check if error requires human escalation.

    Args:
        error_code: Error type

    Returns:
        True if needs human decision
    """
    escalation = {
        "PERMISSION_DENIED",
        "AUTHENTICATION_FAILED",
        "UNKNOWN_ERROR",
        "RESOURCE_LIMIT_EXCEEDED",
    }
    return error_code in escalation


if __name__ == "__main__":
    # Simple smoke test
    logging.basicConfig(level=logging.DEBUG)

    class SimpleResult:
        def __init__(self, agent_id, success, error_code=None):
            self.agent_id = agent_id
            self.success = success
            self.error_code = error_code

    detector = DeadlockDetector()

    # Test stuck detection
    for i in range(3):
        result = SimpleResult("api_agent", False, "RATE_LIMIT")
        stuck = detector.is_stuck(result)
        print(f"Attempt {i+1}: stuck={stuck}")

    # Test recovery suggestion
    recovery = detector.suggest_recovery_action("api_agent")
    print(f"Recovery: {recovery}")

    # Test summary
    summary = detector.get_failure_summary("api_agent")
    print(f"Summary: {summary}")
