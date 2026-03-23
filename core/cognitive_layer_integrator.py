"""
Cognitive Layer Integrator - Orchestrates all Phase 4 cognitive components.

Coordinates:
1. CEO Planner - Pre-execution simulation
2. Deadlock Detector - Stuck loop detection and recovery
3. Focused-Diffuse Modes - Dynamic mode switching
4. Time-Boxed Scheduler - Resource quota management
5. Sleep Consolidator - Offline learning and optimization

This integrator is called from task_engine.py execute_task() to:
- Simulate tasks before execution (CEO)
- Assign time budgets (Scheduler)
- Monitor execution for deadlocks (Deadlock Detector)
- Switch modes based on failures (Focused-Diffuse)
- Schedule offline consolidation (Sleep)
"""

import asyncio
import json
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

from .ceo_planner import CEOPlanner, CausalNode
from .agent_deadlock_detector import DeadlockDetector, FailurePattern
from .cognitive_state_machine import CognitiveStateMachine
from .time_boxed_scheduler import TimeBoxedScheduler, TimeBudget
from .sleep_consolidator import SleepConsolidator, SleepReport
from .execution_modes import ExecutionMode

logger = logging.getLogger(__name__)


@dataclass
class CognitiveTrace:
    """Complete cognitive layer decision trace for logging"""
    timestamp: str
    task_id: str
    action: str

    # CEO simulation
    ceo_simulation_result: Optional[Dict[str, Any]] = None
    ceo_conflicts_detected: List[str] = None
    ceo_error_scenarios: List[str] = None

    # Time budgeting
    assigned_budget_seconds: Optional[float] = None
    budget_type: Optional[str] = None

    # Execution monitoring
    execution_success: Optional[bool] = None
    execution_duration_ms: Optional[float] = None
    execution_error: Optional[str] = None

    # Deadlock detection
    deadlock_detected: bool = False
    deadlock_recovery_action: Optional[str] = None

    # Mode switching
    mode_before: Optional[str] = None
    mode_after: Optional[str] = None
    mode_switch_reason: Optional[str] = None

    # Consolidation
    sleep_scheduled: bool = False
    sleep_time: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging"""
        d = asdict(self)
        if self.ceo_conflicts_detected is None:
            d['ceo_conflicts_detected'] = []
        if self.ceo_error_scenarios is None:
            d['ceo_error_scenarios'] = []
        return d


class CognitiveLayerIntegrator:
    """
    Orchestrator for all cognitive layers.

    Ensures:
    - CEO simulates before execution
    - Time budgets are respected
    - Deadlocks are detected early
    - Modes switch appropriately
    - Sleep consolidation happens offline
    - All decisions are logged for audit
    """

    def __init__(self):
        """Initialize all cognitive components"""
        self.ceo = CEOPlanner()
        self.deadlock_detector = DeadlockDetector()
        self.state_machine = CognitiveStateMachine()
        self.scheduler = TimeBoxedScheduler()
        self.sleep_consolidator = SleepConsolidator()

        # For tracking daily errors and patterns (reset daily)
        self.daily_errors: List[Dict[str, Any]] = []
        self.daily_patterns: List[List[str]] = []
        self.execution_q_table: Dict[str, Dict[str, float]] = {}

        logger.info("Cognitive Layer Integrator initialized")

    async def simulate_task_execution(
        self,
        task_id: str,
        action: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Phase 1: CEO Planner - Simulate task before execution.

        Returns:
            Dict with simulation results, conflicts, error scenarios
        """
        try:
            # Create task object for CEO
            class Task:
                def __init__(self, action_name, task_id_val):
                    self.action = action_name
                    self.id = task_id_val

            task = Task(action, task_id)
            ctx = context or {}

            # Build causal tree (simulates execution path)
            tree = self.ceo.build_causal_tree(task, ctx)
            if not tree:
                logger.warning(f"CEO simulation failed for {action}")
                return {"success": False, "reason": "CEO simulation failed"}

            # Detect conflicts in execution path
            conflicts = self.ceo.detect_conflicting_loops(tree)

            # Predict error scenarios (timeout, permission, etc)
            errors = self.ceo.predict_error_scenarios(tree)

            return {
                "success": True,
                "tree_depth": tree.depth if hasattr(tree, 'depth') else 0,
                "conflicts_detected": conflicts or [],
                "error_scenarios": errors or [],
                "confidence": 0.9  # CEO confidence in simulation
            }
        except Exception as e:
            logger.error(f"CEO simulation error: {e}")
            return {"success": False, "reason": str(e)}

    def assign_time_budget(
        self,
        task_id: str,
        action: str,
        task_type: str = "general"
    ) -> Dict[str, Any]:
        """
        Phase 2: Time-Boxed Scheduler - Assign resource quota.

        Returns:
            Dict with budget seconds and quota info
        """
        try:
            self.scheduler.assign_budget(task_id, task_type)
            budget = self.scheduler.get_task_budget(task_id)

            logger.info(f"Budget assigned: {task_id} = {budget}s ({task_type})")

            return {
                "success": True,
                "task_id": task_id,
                "budget_seconds": budget,
                "task_type": task_type
            }
        except Exception as e:
            logger.error(f"Budget assignment error: {e}")
            return {"success": False, "reason": str(e)}

    async def monitor_execution(
        self,
        task_id: str,
        execution_success: bool,
        execution_duration_ms: float,
        error_code: Optional[str] = None,
        agent_id: str = "default"
    ) -> Dict[str, Any]:
        """
        Phase 3: Monitor execution and detect deadlocks.

        Returns:
            Dict with deadlock status and recovery actions
        """
        try:
            # Create result object for deadlock detector
            class ExecutionResult:
                def __init__(self, success, duration, error, agent):
                    self.success = success
                    self.duration = duration / 1000  # Convert ms to seconds
                    self.error_code = error
                    self.agent_id = agent

            result = ExecutionResult(execution_success, execution_duration_ms, error_code, agent_id)

            # Check if task is stuck
            is_stuck = self.deadlock_detector.is_stuck(result)

            if is_stuck:
                logger.warning(f"Deadlock detected for {agent_id}")
                recovery = self.deadlock_detector.suggest_recovery_action(agent_id, [])

                # Track failure for daily analysis
                self.daily_errors.append({
                    "agent_id": agent_id,
                    "error_code": error_code,
                    "success": False,
                    "timestamp": datetime.now().isoformat()
                })

                return {
                    "deadlock_detected": True,
                    "recovery_action": recovery.get("action") if recovery else "none",
                    "recovery_details": recovery or {}
                }
            else:
                # Track success
                if execution_success:
                    self.daily_errors.append({
                        "agent_id": agent_id,
                        "error_code": None,
                        "success": True,
                        "timestamp": datetime.now().isoformat()
                    })

                return {"deadlock_detected": False}
        except Exception as e:
            logger.error(f"Execution monitoring error: {e}")
            return {"deadlock_detected": False, "error": str(e)}

    async def check_execution_timeout(
        self,
        task_id: str,
        duration_ms: float
    ) -> Dict[str, Any]:
        """
        Check if task exceeded time budget.

        Returns:
            Dict with timeout status and remaining budget
        """
        try:
            exceeded = self.scheduler.check_timeout(task_id, duration_ms / 1000)
            budget = self.scheduler.get_task_budget(task_id)
            remaining = budget - (duration_ms / 1000) if budget else None

            if exceeded:
                logger.warning(f"Task {task_id} exceeded budget: {duration_ms}ms > {budget}s")

            return {
                "timeout": exceeded,
                "duration_seconds": duration_ms / 1000,
                "budget_seconds": budget,
                "remaining_seconds": remaining
            }
        except Exception as e:
            logger.error(f"Timeout check error: {e}")
            return {"timeout": False, "error": str(e)}

    async def evaluate_mode_switch(
        self,
        execution_success: bool,
        execution_duration_ms: float,
        error_code: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Phase 4: Focused-Diffuse Modes - Switch based on performance.

        Returns:
            Dict with mode before/after and switch reason
        """
        try:
            mode_before = self.state_machine.current_mode

            # Create result for mode switching logic
            class ModeResult:
                def __init__(self, success, duration, error):
                    self.success = success
                    self.duration = duration / 1000
                    self.error_code = error

            result = ModeResult(execution_success, execution_duration_ms, error_code)

            # Create dummy deadlock detector for mode switch
            class DummyDetector:
                def is_stuck(self, r):
                    return not r.success and r.error_code

            # Trigger mode switch if needed
            await self.state_machine.toggle_mode_if_needed(result, DummyDetector())

            mode_after = self.state_machine.current_mode
            reason = None
            if mode_before != mode_after:
                reason = f"Switched from {mode_before} to {mode_after}"
                logger.info(reason)

            return {
                "mode_before": str(mode_before),
                "mode_after": str(mode_after),
                "switched": mode_before != mode_after,
                "reason": reason
            }
        except Exception as e:
            logger.error(f"Mode switch error: {e}")
            return {
                "mode_before": str(self.state_machine.current_mode),
                "mode_after": str(self.state_machine.current_mode),
                "switched": False,
                "error": str(e)
            }

    async def consolidate_daily_learning(
        self,
        force: bool = False
    ) -> Optional[SleepReport]:
        """
        Phase 5: Sleep Consolidator - Offline learning and optimization.

        Args:
            force: Force consolidation even if not scheduled

        Returns:
            SleepReport with consolidation metrics
        """
        try:
            if not self.daily_errors and not force:
                logger.debug("No daily data for consolidation")
                return None

            # Analyze daily errors
            logger.info(f"Consolidating {len(self.daily_errors)} daily errors")

            report = self.sleep_consolidator.enter_sleep_mode(
                daily_errors=self.daily_errors,
                q_table=self.execution_q_table,
                patterns=self.daily_patterns
            )

            # Reset daily tracking
            self.daily_errors.clear()
            self.daily_patterns.clear()

            logger.info("Sleep consolidation complete")
            return report
        except Exception as e:
            logger.error(f"Sleep consolidation error: {e}")
            return None

    async def process_task_cognitive_flow(
        self,
        task_id: str,
        action: str,
        params: Dict[str, Any],
        context: Optional[Dict[str, Any]] = None
    ) -> CognitiveTrace:
        """
        Complete cognitive flow for a single task.

        Runs: CEO → Budget → Monitor → Timeout → Mode Switch → Log

        Returns:
            CognitiveTrace with all decisions
        """
        trace = CognitiveTrace(
            timestamp=datetime.now().isoformat(),
            task_id=task_id,
            action=action
        )

        try:
            # Phase 1: CEO Simulation
            logger.info(f"CEO: Simulating {action}")
            ceo_result = await self.simulate_task_execution(task_id, action, params, context)
            trace.ceo_simulation_result = ceo_result

            if ceo_result.get("conflicts_detected"):
                trace.ceo_conflicts_detected = ceo_result["conflicts_detected"]
            if ceo_result.get("error_scenarios"):
                trace.ceo_error_scenarios = ceo_result["error_scenarios"]

            # Phase 2: Time Budget Assignment
            logger.info(f"Scheduler: Assigning budget for {action}")
            task_type = context.get("task_type", "general") if context else "general"
            budget_result = self.assign_time_budget(task_id, action, task_type)
            trace.assigned_budget_seconds = budget_result.get("budget_seconds")
            trace.budget_type = task_type

            return trace
        except Exception as e:
            logger.error(f"Cognitive flow error: {e}")
            return trace

    def record_execution_result(
        self,
        trace: CognitiveTrace,
        success: bool,
        duration_ms: float,
        error: Optional[str] = None,
        agent_id: str = "default"
    ) -> None:
        """
        Record execution result in cognitive trace.

        Called after task execution completes.
        """
        trace.execution_success = success
        trace.execution_duration_ms = duration_ms
        trace.execution_error = error

    async def finalize_cognitive_decisions(
        self,
        trace: CognitiveTrace,
        agent_id: str = "default"
    ) -> CognitiveTrace:
        """
        Complete remaining cognitive phases after execution.

        Runs: Monitor → Timeout → Mode Switch
        """
        try:
            if trace.execution_success is None:
                logger.warning("Execution result not recorded in trace")
                return trace

            # Phase 3: Deadlock Detection
            logger.info("Deadlock: Monitoring execution")
            deadlock_result = await self.monitor_execution(
                trace.task_id,
                trace.execution_success,
                trace.execution_duration_ms or 0,
                trace.execution_error,
                agent_id
            )
            trace.deadlock_detected = deadlock_result.get("deadlock_detected", False)
            trace.deadlock_recovery_action = deadlock_result.get("recovery_action")

            # Phase 4: Timeout Check
            timeout_result = await self.check_execution_timeout(
                trace.task_id,
                trace.execution_duration_ms or 0
            )
            if timeout_result.get("timeout"):
                trace.execution_error = trace.execution_error or "TIMEOUT"

            # Phase 4b: Mode Switching
            logger.info("Mode: Evaluating mode switch")
            mode_result = await self.evaluate_mode_switch(
                trace.execution_success,
                trace.execution_duration_ms or 0,
                trace.execution_error
            )
            trace.mode_before = mode_result.get("mode_before")
            trace.mode_after = mode_result.get("mode_after")
            trace.mode_switch_reason = mode_result.get("reason")

            return trace
        except Exception as e:
            logger.error(f"Cognitive finalization error: {e}")
            return trace

    def log_cognitive_trace(self, trace: CognitiveTrace) -> None:
        """Log complete cognitive trace to cognitive_trace.log"""
        try:
            # Log in structured format
            trace_dict = trace.to_dict()
            logger.info(f"COGNITIVE_TRACE: {json.dumps(trace_dict)}")
        except Exception as e:
            logger.error(f"Trace logging error: {e}")

    async def check_pomodoro_break(self) -> bool:
        """Check if Pomodoro break is needed"""
        try:
            # Get accumulated focus time (simplified)
            needs_break = self.state_machine.needs_pomodoro_break()
            if needs_break:
                logger.info("Pomodoro break needed - take 5 second break")
            return needs_break
        except Exception as e:
            logger.error(f"Pomodoro check error: {e}")
            return False


# Singleton instance
_integrator: Optional[CognitiveLayerIntegrator] = None


def get_cognitive_integrator() -> CognitiveLayerIntegrator:
    """Get or create singleton cognitive layer integrator"""
    global _integrator
    if _integrator is None:
        _integrator = CognitiveLayerIntegrator()
    return _integrator


def reset_cognitive_integrator() -> None:
    """Reset integrator (for testing)"""
    global _integrator
    _integrator = None
