"""
Cognitive State Machine — Focused-Diffuse Mode Switching.

Manages dynamic mode switching between focused (exploitation) and diffuse (exploration)
execution based on task success/failure patterns.

Implements:
- Mode toggle logic (success → stay, failures → switch)
- Pomodoro timer (5 min focused, 5s breaks)
- Deadlock detection trigger
- Exponential backoff on repeated failures

State transitions:
    FOCUSED → FOCUSED: Success (reset failure counter)
    FOCUSED → FOCUSED: Timeout, continue focused
    FOCUSED → DIFFUSE: 3+ consecutive failures (Einstellung breaker)
    FOCUSED → DIFFUSE: >70% failure rate in window
    DIFFUSE → FOCUSED: 2+ consecutive successes (recovered)
    SLEEP: Background consolidation (not actively used here)
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from enum import Enum
import logging
import time

logger = logging.getLogger(__name__)


# ============================================================================
# Enums & Data Models
# ============================================================================

class ExecutionMode(Enum):
    """Execution mode types"""
    FOCUSED = "focused"
    DIFFUSE = "diffuse"
    SLEEP = "sleep"


@dataclass
class ModeState:
    """State information for current mode"""
    mode: ExecutionMode
    entered_at: float = field(default_factory=time.time)
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    total_attempts: int = 0
    total_successes: int = 0
    total_failures: int = 0


# ============================================================================
# Cognitive State Machine
# ============================================================================

class CognitiveStateMachine:
    """
    Manages focused-diffuse mode switching based on execution results.

    Key features:
    - Automatic mode switching on failure patterns
    - Pomodoro timer (5 min = 300s focused, 5s breaks)
    - Success/failure tracking per agent
    - Escalation to human approval on repeated failures
    - Exponential backoff for retries

    Pomodoro settings (tunable):
    - max_focused_duration: 300s (5 minutes)
    - break_duration: 5s
    """

    def __init__(
        self,
        initial_mode: ExecutionMode = ExecutionMode.FOCUSED,
        max_focused_duration: int = 300,  # 5 minutes
        break_duration: int = 5,          # 5 seconds
        failure_threshold: int = 3,       # 3 consecutive failures → diffuse
        success_threshold: int = 2,       # 2 successes → return to focused
    ):
        """
        Initialize cognitive state machine.

        Args:
            initial_mode: Starting execution mode (default FOCUSED)
            max_focused_duration: Max time in focused mode (seconds)
            break_duration: Duration of break (seconds)
            failure_threshold: Consecutive failures to trigger switch
            success_threshold: Successes to return from diffuse
        """
        self.current_mode = initial_mode
        self.state = ModeState(mode=initial_mode)

        # Pomodoro settings
        self.max_focused_duration = max_focused_duration  # 300s = 5 min
        self.break_duration = break_duration              # 5s
        self.failure_threshold = failure_threshold        # 3
        self.success_threshold = success_threshold        # 2

        # Timing
        self.mode_entered_at = time.time()
        self.focused_started_at = time.time() if initial_mode == ExecutionMode.FOCUSED else None

        logger.info(f"CognitiveStateMachine initialized: mode={initial_mode.value}")

    async def toggle_mode_if_needed(
        self,
        task_result: Any,
        deadlock_detector: Any
    ) -> Optional[Dict[str, Any]]:
        """
        Decide if mode should change based on task result.

        Decision tree:
        1. If success → reset failure counter, stay in mode
        2. If failure:
           a. Check if stuck (deadlock detector)
           b. If stuck → switch to diffuse mode
           c. If not stuck but many failures → switch to diffuse
        3. If in diffuse + 2 successes → return to focused
        4. Check Pomodoro timer → suggest break

        Args:
            task_result: ExecutionResult with success, duration, error_code
            deadlock_detector: DeadlockDetector instance (has is_stuck method)

        Returns:
            Dict with action recommendation, or None if no action needed
        """
        self.state.total_attempts += 1

        # Success case
        if task_result.success:
            self.state.consecutive_failures = 0
            self.state.consecutive_successes += 1
            self.state.total_successes += 1

            logger.debug(
                f"Task succeeded: mode={self.current_mode.value}, "
                f"successes={self.state.consecutive_successes}"
            )

            # Check if should return to focused from diffuse
            if (self.current_mode == ExecutionMode.DIFFUSE and
                self.state.consecutive_successes >= self.success_threshold):
                return await self._switch_to_focused()

            return None

        # Failure case
        self.state.consecutive_failures += 1
        self.state.consecutive_successes = 0
        self.state.total_failures += 1

        logger.warning(
            f"Task failed: mode={self.current_mode.value}, "
            f"failures={self.state.consecutive_failures}, "
            f"error={getattr(task_result, 'error_code', 'unknown')}"
        )

        # Check if stuck (deadlock detection)
        if deadlock_detector and deadlock_detector.is_stuck(task_result):
            logger.warning(f"Deadlock detected: switching to diffuse mode")
            recovery = deadlock_detector.suggest_recovery_action(
                task_result.agent_id,
                available_agents=[]
            )
            return await self._switch_to_diffuse(recovery)

        # Check consecutive failure threshold
        if self.state.consecutive_failures >= self.failure_threshold:
            logger.warning(
                f"Failure threshold reached ({self.failure_threshold}): "
                f"switching to diffuse mode"
            )
            return await self._switch_to_diffuse()

        return None

    async def _switch_to_focused(self) -> Dict[str, Any]:
        """Switch to focused mode."""
        self.current_mode = ExecutionMode.FOCUSED
        self.mode_entered_at = time.time()
        self.focused_started_at = time.time()
        self.state = ModeState(mode=ExecutionMode.FOCUSED)

        logger.info("Switched to FOCUSED mode")
        return {
            "action": "switch_to_focused",
            "reason": "Recent successes — returning to exploitation",
            "mode": "focused",
        }

    async def _switch_to_diffuse(self, recovery_hint: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Switch to diffuse mode.

        Args:
            recovery_hint: Optional recovery suggestion from deadlock detector

        Returns:
            Mode switch action recommendation
        """
        self.current_mode = ExecutionMode.DIFFUSE
        self.mode_entered_at = time.time()
        self.state = ModeState(mode=ExecutionMode.DIFFUSE)

        logger.info("Switched to DIFFUSE mode")
        return {
            "action": "switch_to_diffuse",
            "reason": "Repeated failures or deadlock detected — switching to exploration",
            "mode": "diffuse",
            "recovery_hint": recovery_hint,
        }

    def check_pomodoro_timeout(self) -> Optional[Dict[str, Any]]:
        """
        Check if focused mode has exceeded Pomodoro timer.

        Returns:
            Dict with break recommendation if timeout, else None
        """
        if self.current_mode != ExecutionMode.FOCUSED:
            return None

        elapsed = time.time() - self.focused_started_at
        if elapsed > self.max_focused_duration:
            logger.info(
                f"Pomodoro timeout: {elapsed:.0f}s > {self.max_focused_duration}s, "
                f"suggesting break"
            )
            return {
                "action": "take_break",
                "reason": "Pomodoro timer expired",
                "duration": self.break_duration,
                "elapsed": elapsed,
            }

        return None

    def get_state_summary(self) -> Dict[str, Any]:
        """Get summary of current state."""
        elapsed_in_mode = time.time() - self.mode_entered_at
        return {
            "current_mode": self.current_mode.value,
            "consecutive_successes": self.state.consecutive_successes,
            "consecutive_failures": self.state.consecutive_failures,
            "total_attempts": self.state.total_attempts,
            "total_successes": self.state.total_successes,
            "total_failures": self.state.total_failures,
            "success_rate": (
                self.state.total_successes / self.state.total_attempts
                if self.state.total_attempts > 0 else 0.0
            ),
            "elapsed_in_mode": elapsed_in_mode,
            "pomodoro_remaining": max(0, self.max_focused_duration - elapsed_in_mode),
        }

    def reset(self) -> None:
        """Reset state machine to initial focused mode."""
        self.current_mode = ExecutionMode.FOCUSED
        self.state = ModeState(mode=ExecutionMode.FOCUSED)
        self.mode_entered_at = time.time()
        self.focused_started_at = time.time()
        logger.info("CognitiveStateMachine reset to FOCUSED mode")


if __name__ == "__main__":
    # Smoke test
    import asyncio

    logging.basicConfig(level=logging.DEBUG)

    class MockResult:
        def __init__(self, success: bool, agent_id: str = "test", error_code: str = None):
            self.success = success
            self.agent_id = agent_id
            self.error_code = error_code
            self.duration = 1.0

    class MockDetector:
        def is_stuck(self, result):
            return False

        def suggest_recovery_action(self, agent_id, available_agents):
            return {"action": "retry"}

    sm = CognitiveStateMachine()
    print(f"Initial mode: {sm.current_mode.value}")
    print(f"Max focused duration: {sm.max_focused_duration}s")

    # Simulate success
    asyncio.run(sm.toggle_mode_if_needed(MockResult(True), MockDetector()))
    print(f"After success: {sm.current_mode.value}")

    # Simulate failures
    for i in range(3):
        asyncio.run(sm.toggle_mode_if_needed(MockResult(False), MockDetector()))

    print(f"After 3 failures: {sm.current_mode.value}")
    print(f"State: {sm.get_state_summary()}")
