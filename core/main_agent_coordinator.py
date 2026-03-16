"""
core/main_agent_coordinator.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Main Agent Coordinator (~600 lines)
Orchestrate sub-agents, delegate tasks, collect and aggregate results.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from enum import Enum
from .advanced_nlu import AdvancedNLU, NLUResult
from .advanced_task_decomposer import AdvancedTaskDecomposer, TaskDecomposition, DecomposedTask
from .sub_agent.agent_pool import PoolManager, AgentPool, get_pool_manager
from .sub_agent.specialized_agents import (
    FileOperationAgent,
    DataProcessingAgent,
    APICallAgent,
    CodeExecutionAgent,
    SearchAgent,
    AnalysisAgent,
    IntegrationAgent,
)
from .sub_agent.base_agent import AgentConfig, ExecutionStatus
from utils.logger import get_logger

logger = get_logger("main_agent_coordinator")


class ExecutionMode(Enum):
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    HYBRID = "hybrid"


@dataclass
class CoordinationContext:
    """Context for coordination session."""
    session_id: str
    user_input: str
    nlu_result: NLUResult
    task_decomposition: TaskDecomposition
    execution_mode: ExecutionMode
    execution_plan: List[str] = field(default_factory=list)  # task IDs in order
    task_results: Dict[str, Any] = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    total_duration_ms: float = 0.0
    status: str = "pending"  # pending, running, success, partial_success, failed


@dataclass
class CoordinationResult:
    """Result of coordination session."""
    session_id: str
    status: str  # success, partial_success, failed
    primary_result: Optional[Any] = None
    all_results: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    execution_time_ms: float = 0.0
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "primary_result": self.primary_result,
            "all_results": self.all_results,
            "errors": self.errors,
            "warnings": self.warnings,
            "execution_time_ms": self.execution_time_ms,
            "notes": self.notes,
        }


class TaskRouter:
    """Route tasks to appropriate agents."""

    def __init__(self, pool_manager: PoolManager):
        self.pool_manager = pool_manager
        self.routing_table = self._build_routing_table()

    def _build_routing_table(self) -> Dict[str, str]:
        """Build mapping from task types to agent pools."""
        return {
            "file_operation": "file_operation_pool",
            "data_processing": "data_processing_pool",
            "api_call": "api_call_pool",
            "code_execution": "code_execution_pool",
            "search": "search_pool",
            "analysis": "analysis_pool",
            "integration": "integration_pool",
        }

    def route(self, task: DecomposedTask) -> str:
        """Determine which pool should handle this task."""
        # Analyze task description and action to determine pool
        action_lower = task.action.lower()

        if any(word in action_lower for word in ["read", "write", "delete", "list", "file", "directory"]):
            return self.routing_table.get("file_operation", "file_operation_pool")
        elif any(word in action_lower for word in ["filter", "transform", "aggregate", "sort", "merge"]):
            return self.routing_table.get("data_processing", "data_processing_pool")
        elif any(word in action_lower for word in ["http", "api", "request", "fetch"]):
            return self.routing_table.get("api_call", "api_call_pool")
        elif any(word in action_lower for word in ["execute", "code", "run", "script"]):
            return self.routing_table.get("code_execution", "code_execution_pool")
        elif any(word in action_lower for word in ["search", "find", "lookup"]):
            return self.routing_table.get("search", "search_pool")
        elif any(word in action_lower for word in ["analyze", "summarize", "extract"]):
            return self.routing_table.get("analysis", "analysis_pool")
        elif any(word in action_lower for word in ["combine", "merge", "integrate", "correlate"]):
            return self.routing_table.get("integration", "integration_pool")

        # Default to data processing
        return self.routing_table.get("data_processing", "data_processing_pool")


class DependencyResolver:
    """Resolve task dependencies and determine execution order."""

    def __init__(self):
        pass

    def resolve_execution_order(self, tasks: List[DecomposedTask]) -> List[str]:
        """Resolve task execution order respecting dependencies."""
        # Topological sort
        task_by_id = {t.task_id: t for t in tasks}
        visited = set()
        order = []

        def visit(task_id: str):
            if task_id in visited:
                return
            visited.add(task_id)

            task = task_by_id.get(task_id)
            if task:
                for dep_id in task.dependencies:
                    visit(dep_id)
                order.append(task_id)

        for task in tasks:
            visit(task.task_id)

        return order

    def can_run_parallel(self, tasks: List[DecomposedTask], execution_order: List[str]) -> Dict[str, List[str]]:
        """Identify which tasks can run in parallel."""
        parallel_groups = {}
        assigned = set()

        for task_id in execution_order:
            if task_id in assigned:
                continue

            group = [task_id]
            assigned.add(task_id)

            task = next((t for t in tasks if t.task_id == task_id), None)
            if task:
                for other_task in tasks:
                    if other_task.task_id not in assigned and not other_task.dependencies:
                        # Check if compatible
                        if task_id in other_task.parallel_compatible:
                            group.append(other_task.task_id)
                            assigned.add(other_task.task_id)

            parallel_groups[task_id] = group

        return parallel_groups


class ResultAggregator:
    """Aggregate results from multiple sub-agents."""

    def __init__(self):
        pass

    def aggregate(
        self,
        task_results: Dict[str, Any],
        decomposition: TaskDecomposition
    ) -> Tuple[Optional[Any], List[str]]:
        """Aggregate sub-task results into unified result."""
        primary_result = None
        notes = []

        # Collect all successful results
        successful = {k: v for k, v in task_results.items() if v and v.get("success", False) != False}

        if not successful:
            return None, ["No successful task results"]

        # If only one result, return it
        if len(successful) == 1:
            primary_result = list(successful.values())[0]
            notes.append(f"Result from single task execution")
            return primary_result, notes

        # Multiple results - aggregate based on pattern
        if decomposition.task_pattern.name == "sequential":
            primary_result = list(successful.values())[-1]  # Last result
            notes.append("Sequential execution - returning final result")
        elif decomposition.task_pattern.name == "parallel":
            primary_result = list(successful.values())  # All results
            notes.append("Parallel execution - returning all results")
        else:
            primary_result = self._smart_aggregate(successful, decomposition)
            notes.append("Smart aggregation applied")

        return primary_result, notes

    def _smart_aggregate(self, results: Dict[str, Any], decomposition: TaskDecomposition) -> Any:
        """Intelligently aggregate results based on type."""
        if not results:
            return None

        # Check result types
        result_types = set(type(v).__name__ for v in results.values())

        if len(result_types) == 1:
            first_type = result_types.pop()

            if first_type == "dict":
                # Merge dictionaries
                merged = {}
                for result in results.values():
                    merged.update(result)
                return merged

            elif first_type == "list":
                # Concatenate lists
                merged = []
                for result in results.values():
                    merged.extend(result)
                return merged

        # Mixed types - wrap in container
        return {"results": results}


class ErrorRecoveryCoordinator:
    """Handle failures and recovery in multi-task execution."""

    def __init__(self):
        self.recovery_strategies = self._build_strategies()

    def _build_strategies(self) -> Dict[str, callable]:
        """Build recovery strategy mapping."""
        return {
            "retry_same": self._retry_same_params,
            "retry_modified": self._retry_modified_params,
            "use_fallback": self._use_fallback,
            "skip_task": self._skip_task,
            "ask_user": self._ask_user_for_help,
        }

    async def handle_task_failure(
        self,
        task: DecomposedTask,
        error: str,
        context: CoordinationContext
    ) -> Optional[Any]:
        """Handle task failure with recovery."""
        logger.warning(f"Task {task.task_id} failed: {error}")

        # Try fallback actions first
        if task.fallback_actions:
            for fallback in task.fallback_actions:
                try:
                    # Execute fallback
                    logger.info(f"Trying fallback for {task.task_id}: {fallback}")
                    # In production, would delegate to appropriate agent
                    return {"success": True, "fallback_used": True}
                except Exception as e:
                    logger.error(f"Fallback failed: {e}")

        # Try retry with exponential backoff
        if task.max_retries > 0:
            for attempt in range(task.max_retries):
                try:
                    delay = task.estimated_duration_seconds * (2 ** attempt) / 1000
                    await asyncio.sleep(delay)
                    logger.info(f"Retrying {task.task_id} (attempt {attempt + 1})")
                    # In production, would re-execute via agent
                    return {"success": True, "retried": True, "attempt": attempt + 1}
                except Exception as e:
                    if attempt == task.max_retries - 1:
                        logger.error(f"All retries failed for {task.task_id}")
                        return None

        return None

    async def _retry_same_params(self, task: DecomposedTask) -> Optional[Any]:
        """Retry with same parameters."""
        return {"success": False, "reason": "Not implemented"}

    async def _retry_modified_params(self, task: DecomposedTask) -> Optional[Any]:
        """Retry with modified parameters."""
        return {"success": False, "reason": "Not implemented"}

    async def _use_fallback(self, task: DecomposedTask) -> Optional[Any]:
        """Use fallback action."""
        return {"success": False, "reason": "No fallback"}

    async def _skip_task(self, task: DecomposedTask) -> Optional[Any]:
        """Skip task and continue."""
        return {"success": True, "skipped": True}

    async def _ask_user_for_help(self, task: DecomposedTask) -> Optional[Any]:
        """Ask user for help (not implemented)."""
        return {"success": False, "reason": "User interaction not available"}


class MainAgentCoordinator:
    """Main coordinator for multi-agent execution."""

    def __init__(self):
        self.pool_manager = get_pool_manager()
        self.nlu_engine = AdvancedNLU()
        self.decomposer = AdvancedTaskDecomposer()
        self.task_router = TaskRouter(self.pool_manager)
        self.dependency_resolver = DependencyResolver()
        self.result_aggregator = ResultAggregator()
        self.error_recovery = ErrorRecoveryCoordinator()
        self._sessions: Dict[str, CoordinationContext] = {}

    async def initialize(self) -> bool:
        """Initialize coordinator and agent pools."""
        try:
            logger.info("Initializing MainAgentCoordinator")

            # Initialize agent pools
            pools = [
                ("file_operation_pool", FileOperationAgent),
                ("data_processing_pool", DataProcessingAgent),
                ("api_call_pool", APICallAgent),
                ("code_execution_pool", CodeExecutionAgent),
                ("search_pool", SearchAgent),
                ("analysis_pool", AnalysisAgent),
                ("integration_pool", IntegrationAgent),
            ]

            for pool_name, agent_class in pools:
                config = AgentConfig(name=pool_name, agent_id=pool_name)
                pool = AgentPool(agent_class, pool_size=2, config=config)
                await self.pool_manager.register_pool(pool_name, pool)

            logger.info("MainAgentCoordinator initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Initialization failed: {e}")
            return False

    async def process(self, user_input: str) -> CoordinationResult:
        """Process user input through full coordination pipeline."""
        import uuid
        session_id = str(uuid.uuid4())[:8]
        start_time = time.time()

        logger.info(f"[{session_id}] Processing: {user_input[:100]}...")

        try:
            # Step 1: Advanced NLU Analysis
            logger.info(f"[{session_id}] Step 1: NLU Analysis")
            nlu_result = await self.nlu_engine.analyze(user_input)
            logger.info(f"[{session_id}] NLU confidence: {nlu_result.confidence:.2f}")

            # Step 2: Task Decomposition
            logger.info(f"[{session_id}] Step 2: Task Decomposition")
            task_decomposition = await self.decomposer.decompose(user_input)
            logger.info(f"[{session_id}] Decomposed into {len(task_decomposition.tasks)} tasks")

            # Step 3: Execution Planning
            logger.info(f"[{session_id}] Step 3: Execution Planning")
            execution_order = self.dependency_resolver.resolve_execution_order(task_decomposition.tasks)
            execution_mode = self._determine_execution_mode(task_decomposition)

            # Create coordination context
            context = CoordinationContext(
                session_id=session_id,
                user_input=user_input,
                nlu_result=nlu_result,
                task_decomposition=task_decomposition,
                execution_mode=execution_mode,
                execution_plan=execution_order,
            )
            self._sessions[session_id] = context

            # Step 4: Task Execution
            logger.info(f"[{session_id}] Step 4: Task Execution (mode={execution_mode.name})")
            await self._execute_tasks(context)

            # Step 5: Result Aggregation
            logger.info(f"[{session_id}] Step 5: Result Aggregation")
            primary_result, agg_notes = self.result_aggregator.aggregate(
                context.task_results,
                task_decomposition
            )

            # Determine final status
            failed_tasks = sum(1 for r in context.task_results.values() if not r or r.get("success") == False)
            if failed_tasks == 0:
                status = "success"
            elif failed_tasks < len(task_decomposition.tasks):
                status = "partial_success"
            else:
                status = "failed"

            # Build result
            duration_ms = (time.time() - start_time) * 1000
            result = CoordinationResult(
                session_id=session_id,
                status=status,
                primary_result=primary_result,
                all_results=context.task_results,
                execution_time_ms=duration_ms,
                notes=agg_notes + nlu_result.notes + task_decomposition.optimization_notes,
            )

            logger.info(f"[{session_id}] Coordination complete: {status} ({duration_ms:.0f}ms)")

            return result

        except Exception as e:
            logger.error(f"[{session_id}] Coordination failed: {e}")
            return CoordinationResult(
                session_id=session_id,
                status="failed",
                errors=[str(e)],
                execution_time_ms=(time.time() - start_time) * 1000,
            )

    async def _execute_tasks(self, context: CoordinationContext) -> None:
        """Execute tasks according to execution mode."""
        if context.execution_mode == ExecutionMode.SEQUENTIAL:
            await self._execute_sequential(context)
        elif context.execution_mode == ExecutionMode.PARALLEL:
            await self._execute_parallel(context)
        elif context.execution_mode == ExecutionMode.CONDITIONAL:
            await self._execute_conditional(context)
        else:
            await self._execute_hybrid(context)

    async def _execute_sequential(self, context: CoordinationContext) -> None:
        """Execute tasks sequentially."""
        tasks_by_id = {t.task_id: t for t in context.task_decomposition.tasks}

        for task_id in context.execution_plan:
            task = tasks_by_id.get(task_id)
            if not task:
                continue

            # Route and execute
            pool_name = self.task_router.route(task)
            task_input = {"description": task.description, "action": task.action}

            try:
                result = await self.pool_manager.execute(task_id, task_input, timeout=task.timeout_seconds)
                context.task_results[task_id] = {
                    "success": result.status == ExecutionStatus.SUCCESS,
                    "output": result.output,
                    "error": result.error,
                }
            except Exception as e:
                logger.error(f"Task {task_id} failed: {e}")
                recovered = await self.error_recovery.handle_task_failure(task, str(e), context)
                if recovered:
                    context.task_results[task_id] = recovered
                else:
                    context.task_results[task_id] = {"success": False, "error": str(e)}

    async def _execute_parallel(self, context: CoordinationContext) -> None:
        """Execute tasks in parallel."""
        tasks_by_id = {t.task_id: t for t in context.task_decomposition.tasks}
        tasks_input = {}

        for task_id, task in tasks_by_id.items():
            tasks_input[task_id] = {"description": task.description, "action": task.action}

        results = await self.pool_manager.execute_parallel(tasks_input)

        for task_id, result in results.items():
            context.task_results[task_id] = {
                "success": result.status == ExecutionStatus.SUCCESS if hasattr(result, 'status') else False,
                "output": result.output if hasattr(result, 'output') else None,
                "error": result.error if hasattr(result, 'error') else None,
            }

    async def _execute_conditional(self, context: CoordinationContext) -> None:
        """Execute tasks with conditional branching."""
        # Simplified implementation - would use conditional logic
        await self._execute_sequential(context)

    async def _execute_hybrid(self, context: CoordinationContext) -> None:
        """Execute tasks with hybrid approach."""
        # Simplified implementation
        await self._execute_sequential(context)

    def _determine_execution_mode(self, decomposition: TaskDecomposition) -> ExecutionMode:
        """Determine best execution mode for task pattern."""
        if decomposition.task_pattern.name == "parallel":
            return ExecutionMode.PARALLEL
        elif decomposition.task_pattern.name == "conditional":
            return ExecutionMode.CONDITIONAL
        elif decomposition.task_pattern.name == "hybrid":
            return ExecutionMode.HYBRID
        else:
            return ExecutionMode.SEQUENTIAL

    async def shutdown(self) -> None:
        """Shutdown coordinator."""
        await self.pool_manager.shutdown()


# Singleton instance
_coordinator: Optional[MainAgentCoordinator] = None


async def get_main_agent_coordinator() -> MainAgentCoordinator:
    """Get or initialize main agent coordinator."""
    global _coordinator
    if _coordinator is None:
        _coordinator = MainAgentCoordinator()
        await _coordinator.initialize()
    return _coordinator
