"""
core/error_recovery_engine.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Advanced Error Recovery Engine (~500 lines)
Categorize errors, plan recovery, and execute fallback strategies.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Dict, Optional, List, Callable
from enum import Enum
import asyncio
import traceback
import time
from utils.logger import get_logger

logger = get_logger("error_recovery_engine")


class ErrorCategory(Enum):
    """Error categories."""
    TIMEOUT = "timeout"
    NETWORK = "network"
    RESOURCE = "resource"
    VALIDATION = "validation"
    PERMISSION = "permission"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    UNKNOWN = "unknown"


class RecoveryStrategy(Enum):
    """Recovery strategies."""
    RETRY_SAME = "retry_same"
    RETRY_MODIFIED = "retry_modified"
    USE_ALTERNATIVE = "use_alternative"
    SKIP_CONTINUE = "skip_continue"
    ASK_USER = "ask_user"
    PARTIAL_SUCCESS = "partial_success"


@dataclass
class ErrorAnalysis:
    """Analysis of an error."""
    error_message: str
    error_type: str
    category: ErrorCategory
    severity: float  # 0.0-1.0
    stack_trace: str
    context: Dict[str, Any]
    suggested_recovery: RecoveryStrategy


@dataclass
class RecoveryPlan:
    """Plan for error recovery."""
    strategy: RecoveryStrategy
    steps: List[str]
    expected_outcome: str
    timeout: int  # seconds
    max_attempts: int


class ErrorCategorizer:
    """Categorize errors by type."""

    def __init__(self):
        self.error_patterns = self._build_patterns()

    def _build_patterns(self) -> Dict[str, ErrorCategory]:
        """Build error type to category mapping."""
        return {
            "TimeoutError": ErrorCategory.TIMEOUT,
            "asyncio.TimeoutError": ErrorCategory.TIMEOUT,
            "ConnectionError": ErrorCategory.NETWORK,
            "HTTPError": ErrorCategory.NETWORK,
            "RequestException": ErrorCategory.NETWORK,
            "MemoryError": ErrorCategory.RESOURCE,
            "ResourceWarning": ErrorCategory.RESOURCE,
            "ValidationError": ErrorCategory.VALIDATION,
            "ValueError": ErrorCategory.VALIDATION,
            "PermissionError": ErrorCategory.PERMISSION,
            "FileNotFoundError": ErrorCategory.NOT_FOUND,
            "KeyError": ErrorCategory.NOT_FOUND,
            "RateLimitError": ErrorCategory.RATE_LIMIT,
            "HTTP429": ErrorCategory.RATE_LIMIT,
        }

    def categorize(self, error: Exception) -> ErrorCategory:
        """Categorize an error."""
        error_type = type(error).__name__
        error_message = str(error)

        # Check exact match
        if error_type in self.error_patterns:
            return self.error_patterns[error_type]

        # Check message patterns
        if "timeout" in error_message.lower():
            return ErrorCategory.TIMEOUT
        elif "network" in error_message.lower() or "connection" in error_message.lower():
            return ErrorCategory.NETWORK
        elif "permission" in error_message.lower():
            return ErrorCategory.PERMISSION
        elif "not found" in error_message.lower():
            return ErrorCategory.NOT_FOUND
        elif "rate limit" in error_message.lower() or "429" in error_message:
            return ErrorCategory.RATE_LIMIT

        return ErrorCategory.UNKNOWN

    def calculate_severity(self, category: ErrorCategory, error: Exception) -> float:
        """Calculate error severity (0.0-1.0)."""
        severity_map = {
            ErrorCategory.TIMEOUT: 0.6,
            ErrorCategory.NETWORK: 0.7,
            ErrorCategory.RESOURCE: 0.8,
            ErrorCategory.VALIDATION: 0.4,
            ErrorCategory.PERMISSION: 0.9,
            ErrorCategory.NOT_FOUND: 0.5,
            ErrorCategory.RATE_LIMIT: 0.5,
            ErrorCategory.UNKNOWN: 0.7,
        }
        return severity_map.get(category, 0.7)


class RecoveryPlanner:
    """Plan error recovery strategies."""

    def __init__(self):
        self.recovery_mappings = self._build_recovery_mappings()

    def _build_recovery_mappings(self) -> Dict[ErrorCategory, RecoveryStrategy]:
        """Build error category to recovery strategy mapping."""
        return {
            ErrorCategory.TIMEOUT: RecoveryStrategy.RETRY_SAME,
            ErrorCategory.NETWORK: RecoveryStrategy.RETRY_SAME,
            ErrorCategory.RESOURCE: RecoveryStrategy.SKIP_CONTINUE,
            ErrorCategory.VALIDATION: RecoveryStrategy.RETRY_MODIFIED,
            ErrorCategory.PERMISSION: RecoveryStrategy.ASK_USER,
            ErrorCategory.NOT_FOUND: RecoveryStrategy.USE_ALTERNATIVE,
            ErrorCategory.RATE_LIMIT: RecoveryStrategy.RETRY_MODIFIED,
            ErrorCategory.UNKNOWN: RecoveryStrategy.RETRY_SAME,
        }

    def plan_recovery(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Create recovery plan for error."""
        strategy = analysis.suggested_recovery

        plans = {
            RecoveryStrategy.RETRY_SAME: self._plan_retry_same(analysis),
            RecoveryStrategy.RETRY_MODIFIED: self._plan_retry_modified(analysis),
            RecoveryStrategy.USE_ALTERNATIVE: self._plan_use_alternative(analysis),
            RecoveryStrategy.SKIP_CONTINUE: self._plan_skip_continue(analysis),
            RecoveryStrategy.ASK_USER: self._plan_ask_user(analysis),
            RecoveryStrategy.PARTIAL_SUCCESS: self._plan_partial_success(analysis),
        }

        return plans.get(strategy, self._plan_default(analysis))

    def _plan_retry_same(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Plan retry with same parameters."""
        return RecoveryPlan(
            strategy=RecoveryStrategy.RETRY_SAME,
            steps=[
                "Wait briefly for transient error to clear",
                "Re-execute task with same parameters",
                "Check if error persists",
            ],
            expected_outcome="Task succeeds on retry",
            timeout=60,
            max_attempts=3,
        )

    def _plan_retry_modified(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Plan retry with modified parameters."""
        return RecoveryPlan(
            strategy=RecoveryStrategy.RETRY_MODIFIED,
            steps=[
                "Analyze error and identify parameter issue",
                "Modify parameters for recovery",
                "Re-execute with modified parameters",
            ],
            expected_outcome="Task succeeds with modified parameters",
            timeout=90,
            max_attempts=2,
        )

    def _plan_use_alternative(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Plan using alternative approach."""
        return RecoveryPlan(
            strategy=RecoveryStrategy.USE_ALTERNATIVE,
            steps=[
                "Identify alternative resource or method",
                "Execute using alternative",
                "Compare results",
            ],
            expected_outcome="Alternative resource available",
            timeout=120,
            max_attempts=1,
        )

    def _plan_skip_continue(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Plan skipping task and continuing."""
        return RecoveryPlan(
            strategy=RecoveryStrategy.SKIP_CONTINUE,
            steps=[
                "Log error and skip this task",
                "Continue with next task",
                "Report partial completion",
            ],
            expected_outcome="Remaining tasks complete successfully",
            timeout=30,
            max_attempts=1,
        )

    def _plan_ask_user(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Plan asking user for help."""
        return RecoveryPlan(
            strategy=RecoveryStrategy.ASK_USER,
            steps=[
                "Inform user of error",
                "Request clarification or guidance",
                "Resume with user input",
            ],
            expected_outcome="User provides guidance",
            timeout=300,
            max_attempts=1,
        )

    def _plan_partial_success(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Plan partial success continuation."""
        return RecoveryPlan(
            strategy=RecoveryStrategy.PARTIAL_SUCCESS,
            steps=[
                "Collect partial results",
                "Continue with valid portions",
                "Report what succeeded",
            ],
            expected_outcome="Partial results delivered",
            timeout=60,
            max_attempts=1,
        )

    def _plan_default(self, analysis: ErrorAnalysis) -> RecoveryPlan:
        """Default recovery plan."""
        return self._plan_retry_same(analysis)


class RecoveryExecutor:
    """Execute error recovery plans."""

    def __init__(self):
        self.execution_history: List[Dict[str, Any]] = []

    async def execute(
        self,
        plan: RecoveryPlan,
        task_fn: Callable,
        context: Dict[str, Any],
    ) -> Optional[Any]:
        """Execute recovery plan."""
        logger.info(f"Executing recovery: {plan.strategy.name}")

        for attempt in range(plan.max_attempts):
            try:
                if plan.strategy == RecoveryStrategy.RETRY_SAME:
                    return await self._execute_retry_same(task_fn, context, plan)
                elif plan.strategy == RecoveryStrategy.RETRY_MODIFIED:
                    return await self._execute_retry_modified(task_fn, context, plan)
                elif plan.strategy == RecoveryStrategy.USE_ALTERNATIVE:
                    return await self._execute_use_alternative(task_fn, context, plan)
                elif plan.strategy == RecoveryStrategy.SKIP_CONTINUE:
                    return await self._execute_skip_continue(context, plan)
                elif plan.strategy == RecoveryStrategy.ASK_USER:
                    return await self._execute_ask_user(context, plan)
                elif plan.strategy == RecoveryStrategy.PARTIAL_SUCCESS:
                    return await self._execute_partial_success(context, plan)

            except Exception as e:
                logger.error(f"Recovery attempt {attempt + 1} failed: {e}")
                if attempt == plan.max_attempts - 1:
                    return None
                await asyncio.sleep(2 ** attempt)

        return None

    async def _execute_retry_same(self, task_fn: Callable, context: Dict[str, Any], plan: RecoveryPlan) -> Any:
        """Retry with same parameters."""
        await asyncio.sleep(1)  # Brief wait
        return await asyncio.wait_for(task_fn(**context), timeout=plan.timeout)

    async def _execute_retry_modified(self, task_fn: Callable, context: Dict[str, Any], plan: RecoveryPlan) -> Any:
        """Retry with modified parameters."""
        modified_context = context.copy()
        # Modify parameters (increase timeout, reduce data size, etc.)
        if "timeout" in modified_context:
            modified_context["timeout"] = int(modified_context["timeout"] * 1.5)
        return await asyncio.wait_for(task_fn(**modified_context), timeout=plan.timeout)

    async def _execute_use_alternative(self, task_fn: Callable, context: Dict[str, Any], plan: RecoveryPlan) -> Any:
        """Use alternative method."""
        # In production, would use alternative implementation
        logger.info("Using alternative method")
        return {"success": False, "alternative_used": True}

    async def _execute_skip_continue(self, context: Dict[str, Any], plan: RecoveryPlan) -> Any:
        """Skip task and continue."""
        logger.info("Skipping task and continuing")
        return {"success": True, "skipped": True}

    async def _execute_ask_user(self, context: Dict[str, Any], plan: RecoveryPlan) -> Any:
        """Ask user for help."""
        logger.info("Would ask user for help")
        return None

    async def _execute_partial_success(self, context: Dict[str, Any], plan: RecoveryPlan) -> Any:
        """Return partial results."""
        logger.info("Returning partial results")
        return {"success": True, "partial": True, "completed": context.get("completed", [])}


class FallbackProvider:
    """Provide fallback alternatives."""

    def __init__(self):
        self.fallback_registry: Dict[str, List[str]] = {}

    def register_fallback(self, task_type: str, fallback_actions: List[str]) -> None:
        """Register fallback actions for task type."""
        self.fallback_registry[task_type] = fallback_actions

    def get_fallbacks(self, task_type: str) -> List[str]:
        """Get fallback actions for task type."""
        return self.fallback_registry.get(task_type, [])

    def suggest_alternatives(self, error_context: Dict[str, Any]) -> List[str]:
        """Suggest alternative approaches."""
        suggestions = []

        if error_context.get("category") == "not_found":
            suggestions.extend([
                "Check if resource name is correct",
                "Use search to find alternative resource",
                "Request user to provide resource location",
            ])

        elif error_context.get("category") == "permission":
            suggestions.extend([
                "Request user to authenticate",
                "Try with elevated privileges",
                "Use alternative authorized method",
            ])

        elif error_context.get("category") == "timeout":
            suggestions.extend([
                "Increase timeout threshold",
                "Break task into smaller chunks",
                "Use caching for repeated requests",
            ])

        return suggestions


class ErrorRecoveryEngine:
    """Complete error recovery engine."""

    def __init__(self):
        self.categorizer = ErrorCategorizer()
        self.planner = RecoveryPlanner()
        self.executor = RecoveryExecutor()
        self.fallback_provider = FallbackProvider()
        self.recovery_log: List[Dict[str, Any]] = []

    async def handle_error(
        self,
        error: Exception,
        task_fn: Optional[Callable] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[Any]:
        """Handle error with full recovery pipeline."""
        context = context or {}
        start_time = time.time()

        # Analyze error
        category = self.categorizer.categorize(error)
        severity = self.categorizer.calculate_severity(category, error)

        analysis = ErrorAnalysis(
            error_message=str(error),
            error_type=type(error).__name__,
            category=category,
            severity=severity,
            stack_trace=traceback.format_exc(),
            context=context,
            suggested_recovery=self.planner.recovery_mappings.get(
                category,
                RecoveryStrategy.RETRY_SAME
            ),
        )

        logger.warning(f"Error categorized: {category.name} (severity: {severity:.2f})")

        # Plan recovery
        plan = self.planner.plan_recovery(analysis)
        logger.info(f"Recovery plan: {plan.strategy.name}")

        # Execute recovery
        result = None
        if task_fn:
            result = await self.executor.execute(plan, task_fn, context)

        # Log recovery attempt
        self.recovery_log.append({
            "timestamp": time.time(),
            "error_type": analysis.error_type,
            "category": analysis.category.name,
            "strategy": plan.strategy.name,
            "success": result is not None,
            "duration_ms": (time.time() - start_time) * 1000,
        })

        return result

    def get_recovery_statistics(self) -> Dict[str, Any]:
        """Get recovery statistics."""
        total = len(self.recovery_log)
        successful = sum(1 for r in self.recovery_log if r.get("success"))

        return {
            "total_recovery_attempts": total,
            "successful_recoveries": successful,
            "success_rate": successful / total if total > 0 else 0.0,
            "by_category": self._group_by_category(),
            "by_strategy": self._group_by_strategy(),
        }

    def _group_by_category(self) -> Dict[str, int]:
        """Group recovery attempts by error category."""
        grouped = {}
        for entry in self.recovery_log:
            cat = entry.get("category", "unknown")
            grouped[cat] = grouped.get(cat, 0) + 1
        return grouped

    def _group_by_strategy(self) -> Dict[str, int]:
        """Group recovery attempts by strategy."""
        grouped = {}
        for entry in self.recovery_log:
            strat = entry.get("strategy", "unknown")
            grouped[strat] = grouped.get(strat, 0) + 1
        return grouped
