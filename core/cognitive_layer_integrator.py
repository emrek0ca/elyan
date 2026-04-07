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
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict
from datetime import datetime

from .consensus_engine import AgentProposal, get_consensus_engine
from .ceo_planner import CEOPlanner, CausalNode
from .agent_deadlock_detector import DeadlockDetector, FailurePattern
from .cognitive_state_machine import CognitiveStateMachine
from .time_boxed_scheduler import TimeBoxedScheduler, TimeBudget
from .sleep_consolidator import SleepConsolidator, SleepReport
from .execution_modes import ExecutionMode
from .personalization.policy_learning import get_policy_learning_store
from security.audit import get_audit_logger

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
        self.consensus_engine = get_consensus_engine()
        self.policy_learning = get_policy_learning_store()
        self.audit = get_audit_logger()

        # For tracking daily errors and patterns (reset daily)
        self.daily_errors: List[Dict[str, Any]] = []
        self.daily_patterns: List[List[str]] = []
        self.execution_q_table: Dict[str, Dict[str, float]] = {}
        self._total_executions = 0
        self._deadlock_count = 0
        self._consensus_count = 0
        self._consensus_override_count = 0

        logger.info("Cognitive Layer Integrator initialized")

    @property
    def current_mode(self) -> str:
        mode = getattr(self.state_machine, "current_mode", None)
        if hasattr(mode, "value"):
            return str(getattr(mode, "value", "focused")).upper()
        return str(mode or "focused").upper()

    def calculate_success_rate(self) -> float:
        if not self.daily_errors:
            return 100.0
        total = len(self.daily_errors)
        successes = sum(1 for item in self.daily_errors if bool(item.get("success")))
        return round((successes / max(1, total)) * 100.0, 2)

    def _standardize_recovery_action(self, action: str, *, fallback: str = "safe_fallback") -> str:
        token = str(action or "").strip().lower()
        if token in {"switch_to_diffuse_mode", "switch_to_diffuse"}:
            return "switch_to_diffuse"
        if token in {"increase_timeout_and_retry", "queue_task", "retry", "exponential_backoff"}:
            return "queue_with_backoff"
        if token in {"escalate_to_approval", "escalate_to_human_approval", "escalate_approval"}:
            return "escalate_approval"
        if token in {"safe_fallback", "fallback"}:
            return "safe_fallback"
        return fallback

    async def evaluate_consensus(
        self,
        *,
        task_id: str,
        user_id: str,
        task_type: str,
        proposals: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Phase 2 (new): Weighted consensus + security veto.
        """
        ctx = dict(context or {})
        veto_policy = str(ctx.get("consensus_veto_policy") or "require_approval")
        explore_exploit = float(ctx.get("consensus_explore_exploit_level", 0.25) or 0.25)
        latency_budget_ms = float(ctx.get("latency_budget_ms", 120000.0) or 120000.0)
        proposal_objs: List[AgentProposal] = []
        for raw in list(proposals or []):
            if not isinstance(raw, dict):
                continue
            proposal_objs.append(
                AgentProposal(
                    agent_id=str(raw.get("agent_id") or "unknown"),
                    action=str(raw.get("action") or ""),
                    confidence=float(raw.get("confidence", 0.0) or 0.0),
                    risk=str(raw.get("risk") or "low"),
                    rationale=str(raw.get("rationale") or ""),
                    est_cost=float(raw.get("est_cost", 0.0) or 0.0),
                    est_latency=float(raw.get("est_latency", 0.0) or 0.0),
                    domain_match=float(raw.get("domain_match", 1.0) or 1.0),
                    stability=float(raw.get("stability", 0.8) or 0.8),
                    role=str(raw.get("role") or "worker"),
                    metadata=dict(raw.get("metadata") or {}),
                )
            )
        self.audit.log_action(
            user_id=0,
            action="ConsensusProposed",
            details={
                "task_id": str(task_id or ""),
                "user_id": str(user_id or "local"),
                "task_type": str(task_type or "general"),
                "proposal_count": len(proposal_objs),
            },
            success=True,
        )
        decision = self.consensus_engine.resolve(
            task_id=str(task_id or ""),
            user_id=str(user_id or "local"),
            task_type=str(task_type or "general"),
            proposals=proposal_objs,
            veto_policy=veto_policy,
            explore_exploit_level=explore_exploit,
            latency_budget_ms=latency_budget_ms,
            metadata={"context": ctx},
        )
        self._consensus_count += 1
        if proposal_objs:
            original_action = str(proposal_objs[0].action or "").strip().lower()
            if original_action and original_action != str(decision.selected_action or "").strip().lower():
                self._consensus_override_count += 1
        self.audit.log_action(
            user_id=0,
            action="ConsensusResolved",
            details={"task_id": str(task_id or ""), "decision": decision.to_dict()},
            success=not bool(decision.blocked),
        )
        return decision.to_dict()

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
                standardized = self._standardize_recovery_action(str((recovery or {}).get("action") or ""))

                # Track failure for daily analysis
                self.daily_errors.append({
                    "agent_id": agent_id,
                    "error_code": error_code,
                    "success": False,
                    "timestamp": datetime.now().isoformat()
                })
                self.audit.log_action(
                    user_id=0,
                    action="DeadlockRecovered",
                    details={"task_id": task_id, "agent_id": agent_id, "recovery_action": standardized},
                    success=True,
                )

                return {
                    "deadlock_detected": True,
                    "recovery_action": standardized,
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
        finally:
            self._total_executions += 1
            if "is_stuck" in locals() and bool(is_stuck):
                self._deadlock_count += 1

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
                    return bool((not r.success) and r.error_code)

                def suggest_recovery_action(self, agent_id, available_agents=None):
                    return {"action": "switch_to_diffuse_mode", "reason": "mode_switch_heuristic"}

            # Trigger mode switch if needed
            await self.state_machine.toggle_mode_if_needed(result, DummyDetector())

            mode_after = self.state_machine.current_mode
            reason = None
            if mode_before != mode_after:
                reason = f"Switched from {mode_before} to {mode_after}"
                logger.info(reason)
                self.audit.log_action(
                    user_id=0,
                    action="ModeSwitched",
                    details={
                        "mode_before": str(getattr(mode_before, "value", mode_before)),
                        "mode_after": str(getattr(mode_after, "value", mode_after)),
                        "reason": reason,
                    },
                    success=True,
                )

            return {
                "mode_before": str(getattr(mode_before, "value", mode_before)),
                "mode_after": str(getattr(mode_after, "value", mode_after)),
                "switched": mode_before != mode_after,
                "reason": reason
            }
        except Exception as e:
            logger.error(f"Mode switch error: {e}")
            return {
                "mode_before": str(getattr(self.state_machine.current_mode, "value", self.state_machine.current_mode)),
                "mode_after": str(getattr(self.state_machine.current_mode, "value", self.state_machine.current_mode)),
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
            break_state = self.state_machine.check_pomodoro_timeout()
            needs_break = bool(break_state)
            if needs_break:
                logger.info("Pomodoro break needed - take 5 second break")
            return needs_break
        except Exception as e:
            logger.error(f"Pomodoro check error: {e}")
            return False

    def force_mode(self, mode: str) -> dict[str, Any]:
        token = str(mode or "").strip().lower()
        if token in {"focused", "focus"}:
            self.state_machine.reset()
            return {"success": True, "mode": self.current_mode}
        if token in {"diffuse", "explore"}:
            self.state_machine.current_mode = ExecutionMode.DIFFUSE
            self.state_machine.mode_entered_at = time.time()
            self.state_machine.state.mode = ExecutionMode.DIFFUSE
            return {"success": True, "mode": self.current_mode}
        return {"success": False, "error": "invalid_mode"}

    def get_runtime_metrics(self, user_id: str = "local") -> Dict[str, Any]:
        deadlock_rate = (
            (self._deadlock_count / max(1, self._total_executions)) * 100.0
            if self._total_executions > 0
            else 0.0
        )
        return {
            "mode": self.current_mode,
            "success_rate": self.calculate_success_rate(),
            "deadlock_rate": round(deadlock_rate, 2),
            "consensus_runs": int(self._consensus_count),
            "consensus_overrides": int(self._consensus_override_count),
            "learning_score": float(self.policy_learning.get_learning_score(user_id)),
            "totals": {
                "executions": int(self._total_executions),
                "deadlocks": int(self._deadlock_count),
            },
        }


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
