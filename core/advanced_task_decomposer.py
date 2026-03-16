"""
core/advanced_task_decomposer.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Advanced Multi-Task Decomposition (~700 lines)
Break complex tasks into optimal sub-tasks with dependency analysis.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import json
import asyncio
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Set, Optional, Tuple, Any
from enum import Enum
import time
from utils.logger import get_logger

logger = get_logger("advanced_decomposer")


class TaskPatternType(Enum):
    SEQUENTIAL = "sequential"  # A -> B -> C
    PARALLEL = "parallel"  # A, B, C (independent)
    CONDITIONAL = "conditional"  # if A then B
    LOOP = "loop"  # repeat A until B
    HYBRID = "hybrid"  # combination


class TaskPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    MEDIUM = 2
    LOW = 3


@dataclass
class Checkpoint:
    """Verification checkpoint for a task."""
    id: str
    description: str
    verification_type: str  # command, file_exists, content_check, manual
    criteria: str  # How to verify
    timeout_seconds: int = 30

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DecomposedTask:
    """Decomposed sub-task."""
    task_id: str
    description: str
    action: str  # The actual action to take
    priority: TaskPriority = TaskPriority.MEDIUM
    estimated_duration_seconds: int = 60
    timeout_seconds: int = 300
    dependencies: List[str] = field(default_factory=list)
    parallel_compatible: Set[str] = field(default_factory=set)
    estimated_complexity: float = 0.5
    success_probability: float = 0.9
    checkpoints: List[Checkpoint] = field(default_factory=list)
    fallback_actions: List[str] = field(default_factory=list)
    retry_strategy: str = "exponential_backoff"  # none, immediate, linear, exponential
    max_retries: int = 3
    status: str = "pending"  # pending, running, success, failed, skipped
    error_message: Optional[str] = None
    result: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "description": self.description,
            "action": self.action,
            "priority": self.priority.name,
            "estimated_duration_seconds": self.estimated_duration_seconds,
            "timeout_seconds": self.timeout_seconds,
            "dependencies": self.dependencies,
            "parallel_compatible": list(self.parallel_compatible),
            "estimated_complexity": self.estimated_complexity,
            "success_probability": self.success_probability,
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "fallback_actions": self.fallback_actions,
            "retry_strategy": self.retry_strategy,
            "max_retries": self.max_retries,
            "status": self.status,
            "error_message": self.error_message,
            "result": self.result,
        }


@dataclass
class TaskDecomposition:
    """Complete task decomposition result."""
    original_request: str
    task_pattern: TaskPatternType
    overall_complexity: float  # 0.0-1.0
    estimated_total_duration_seconds: int
    tasks: List[DecomposedTask] = field(default_factory=list)
    circular_dependencies: List[Tuple[str, str]] = field(default_factory=list)
    parallelizable_chains: List[List[str]] = field(default_factory=list)
    critical_path: List[str] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    success_probability: float = 0.95
    optimization_notes: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "original_request": self.original_request,
            "task_pattern": self.task_pattern.name,
            "overall_complexity": self.overall_complexity,
            "estimated_total_duration_seconds": self.estimated_total_duration_seconds,
            "tasks": [t.to_dict() for t in self.tasks],
            "circular_dependencies": self.circular_dependencies,
            "parallelizable_chains": self.parallelizable_chains,
            "critical_path": self.critical_path,
            "execution_order": self.execution_order,
            "success_probability": self.success_probability,
            "optimization_notes": self.optimization_notes,
            "processing_time_ms": self.processing_time_ms,
        }


class ComplexityAnalyzer:
    """Analyze task complexity."""

    def __init__(self):
        self.complexity_weights = {
            "task_count": 0.1,
            "dependency_count": 0.2,
            "parallelization_potential": -0.15,  # negative = reduces complexity
            "conditional_branches": 0.25,
            "error_recovery_needed": 0.15,
            "external_dependencies": 0.15,
            "data_integration": 0.1,
        }

    def analyze(self, tasks: List[DecomposedTask], dependencies: Dict[str, List[str]]) -> float:
        """Calculate overall complexity score (0.0-1.0)."""
        score = 0.0

        # Task count factor
        task_factor = min(1.0, len(tasks) / 10.0)
        score += task_factor * self.complexity_weights["task_count"]

        # Dependency factor
        total_deps = sum(len(deps) for deps in dependencies.values())
        dependency_factor = min(1.0, total_deps / 15.0)
        score += dependency_factor * self.complexity_weights["dependency_count"]

        # Parallelization factor (reduces complexity)
        parallel_groups = self._find_parallel_groups(tasks, dependencies)
        parallelization_reduction = min(0.15, len(parallel_groups) * 0.05)
        score += parallelization_reduction * self.complexity_weights["parallelization_potential"]

        # Conditional branches
        conditional_count = sum(
            1 for task in tasks if "if" in task.description.lower() or "condition" in task.action.lower()
        )
        conditional_factor = min(1.0, conditional_count / 5.0)
        score += conditional_factor * self.complexity_weights["conditional_branches"]

        # Error recovery
        error_recovery_count = sum(1 for task in tasks if task.fallback_actions)
        recovery_factor = min(1.0, error_recovery_count / 5.0)
        score += recovery_factor * self.complexity_weights["error_recovery_needed"]

        # External dependencies
        external_count = sum(1 for task in tasks if "api" in task.action.lower() or "http" in task.action.lower())
        external_factor = min(1.0, external_count / 5.0)
        score += external_factor * self.complexity_weights["external_dependencies"]

        # Data integration
        data_ops = sum(1 for task in tasks if any(
            word in task.action.lower() for word in ["merge", "combine", "aggregate", "transform"]
        ))
        data_factor = min(1.0, data_ops / 5.0)
        score += data_factor * self.complexity_weights["data_integration"]

        return min(1.0, max(0.0, score))

    def _find_parallel_groups(self, tasks: List[DecomposedTask], dependencies: Dict[str, List[str]]) -> List[Set[str]]:
        """Find groups of tasks that can run in parallel."""
        groups = []
        assigned = set()

        for task in tasks:
            if task.task_id in assigned:
                continue

            # Find all tasks with no dependencies in common
            group = {task.task_id}
            assigned.add(task.task_id)

            for other_task in tasks:
                if other_task.task_id not in assigned:
                    if not self._have_conflicting_deps(task, other_task, dependencies):
                        group.add(other_task.task_id)
                        assigned.add(other_task.task_id)

            if len(group) > 1:
                groups.append(group)

        return groups

    def _have_conflicting_deps(self, task1: DecomposedTask, task2: DecomposedTask, dependencies: Dict[str, List[str]]) -> bool:
        """Check if two tasks have conflicting dependencies."""
        deps1 = set(dependencies.get(task1.task_id, []))
        deps2 = set(dependencies.get(task2.task_id, []))
        return bool(deps1 & deps2)


class DependencyOptimizer:
    """Optimize task dependencies and ordering."""

    def __init__(self):
        pass

    def detect_circular_dependencies(self, dependencies: Dict[str, List[str]]) -> List[Tuple[str, str]]:
        """Detect circular dependencies in task graph."""
        cycles = []

        for task, deps in dependencies.items():
            visited = set()
            if self._has_cycle(task, deps, dependencies, visited):
                for dep in deps:
                    if self._has_cycle(dep, dependencies.get(dep, []), dependencies, set()):
                        cycles.append((task, dep))

        return cycles

    def _has_cycle(self, task: str, deps: List[str], all_deps: Dict[str, List[str]], visited: Set[str]) -> bool:
        """Check if task has a cycle."""
        if task in visited:
            return True
        visited.add(task)

        for dep in deps:
            if self._has_cycle(dep, all_deps.get(dep, []), all_deps, visited.copy()):
                return True

        return False

    def minimize_dependencies(self, dependencies: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Remove redundant dependencies (transitive reduction)."""
        optimized = {}

        for task, deps in dependencies.items():
            minimal_deps = set(deps)

            # Remove transitive dependencies
            for dep in deps:
                transitive_deps = set(dependencies.get(dep, []))
                minimal_deps -= transitive_deps

            optimized[task] = list(minimal_deps)

        return optimized

    def find_critical_path(self, tasks: List[DecomposedTask], dependencies: Dict[str, List[str]]) -> List[str]:
        """Find the critical path (longest path through task graph)."""
        # Build completion times
        completion_times = {}

        # Topological sort
        topo_order = self._topological_sort(dependencies)

        for task_id in topo_order:
            task = next((t for t in tasks if t.task_id == task_id), None)
            if not task:
                continue

            deps = dependencies.get(task_id, [])
            if not deps:
                completion_times[task_id] = task.estimated_duration_seconds
            else:
                max_dep_time = max(completion_times.get(dep, 0) for dep in deps)
                completion_times[task_id] = max_dep_time + task.estimated_duration_seconds

        # Find critical path by backtracking from end
        if not completion_times:
            return []

        current = max(completion_times, key=completion_times.get)
        path = [current]

        while True:
            deps = dependencies.get(current, [])
            if not deps:
                break

            # Find the dependency with max completion time
            next_task = max(
                deps,
                key=lambda d: completion_times.get(d, 0),
                default=None
            )

            if next_task is None:
                break

            path.append(next_task)
            current = next_task

        return list(reversed(path))

    def _topological_sort(self, dependencies: Dict[str, List[str]]) -> List[str]:
        """Topological sort of tasks."""
        all_tasks = set(dependencies.keys()) | set(
            dep for deps in dependencies.values() for dep in deps
        )

        in_degree = {task: 0 for task in all_tasks}
        for task, deps in dependencies.items():
            in_degree[task] = len(deps)

        queue = [task for task in all_tasks if in_degree[task] == 0]
        result = []

        while queue:
            current = queue.pop(0)
            result.append(current)

            for task, deps in dependencies.items():
                if current in deps:
                    in_degree[task] -= 1
                    if in_degree[task] == 0:
                        queue.append(task)

        return result

    def suggest_reordering(self, tasks: List[DecomposedTask], dependencies: Dict[str, List[str]]) -> List[str]:
        """Suggest execution order for all tasks."""
        return self._topological_sort(dependencies)


class TaskPatternDetector:
    """Detect task pattern types."""

    def detect(self, tasks: List[DecomposedTask], dependencies: Dict[str, List[str]]) -> TaskPatternType:
        """Detect the overall task pattern."""
        # Count different patterns
        sequential_count = sum(1 for deps in dependencies.values() if len(deps) <= 1)
        parallel_count = sum(1 for deps in dependencies.values() if len(deps) == 0)
        conditional_count = sum(1 for task in tasks if "if" in task.description.lower())

        total = len(tasks)

        # Determine dominant pattern
        if parallel_count >= total * 0.7:
            return TaskPatternType.PARALLEL
        elif sequential_count >= total * 0.7:
            return TaskPatternType.SEQUENTIAL
        elif conditional_count >= total * 0.3:
            return TaskPatternType.CONDITIONAL
        elif any("loop" in task.description.lower() or "repeat" in task.description.lower() for task in tasks):
            return TaskPatternType.LOOP
        else:
            return TaskPatternType.HYBRID


class AdvancedTaskDecomposer:
    """Main task decomposition engine."""

    def __init__(self):
        self.complexity_analyzer = ComplexityAnalyzer()
        self.dependency_optimizer = DependencyOptimizer()
        self.pattern_detector = TaskPatternDetector()

    async def decompose(self, request: str, context: Optional[Dict[str, Any]] = None) -> TaskDecomposition:
        """Decompose a complex request into optimal sub-tasks."""
        start_time = time.time()
        context = context or {}

        logger.info(f"Decomposing request: {request[:100]}...")

        # Extract key information from request
        tasks = self._extract_tasks(request)
        dependencies = self._extract_dependencies(request, tasks)

        # Detect circular dependencies
        circular = self.dependency_optimizer.detect_circular_dependencies(dependencies)
        if circular:
            logger.warning(f"Circular dependencies detected: {circular}")

        # Optimize dependencies
        optimized_deps = self.dependency_optimizer.minimize_dependencies(dependencies)

        # Find critical path
        critical_path = self.dependency_optimizer.find_critical_path(tasks, optimized_deps)

        # Suggest execution order
        execution_order = self.dependency_optimizer.suggest_reordering(tasks, optimized_deps)

        # Detect pattern
        pattern = self.pattern_detector.detect(tasks, optimized_deps)

        # Calculate complexity
        overall_complexity = self.complexity_analyzer.analyze(tasks, optimized_deps)

        # Calculate total duration
        total_duration = sum(t.estimated_duration_seconds for t in tasks)

        # Calculate success probability
        success_prob = 1.0
        for task in tasks:
            success_prob *= task.success_probability

        # Find parallelizable chains
        parallel_chains = self._find_parallelizable_chains(tasks, optimized_deps)

        # Generate optimization notes
        optimization_notes = self._generate_optimization_notes(tasks, optimized_deps, pattern, parallel_chains)

        result = TaskDecomposition(
            original_request=request,
            task_pattern=pattern,
            overall_complexity=overall_complexity,
            estimated_total_duration_seconds=total_duration,
            tasks=tasks,
            circular_dependencies=circular,
            parallelizable_chains=parallel_chains,
            critical_path=critical_path,
            execution_order=execution_order,
            success_probability=success_prob,
            optimization_notes=optimization_notes,
            processing_time_ms=(time.time() - start_time) * 1000,
        )

        logger.info(
            f"Decomposition complete: {len(tasks)} tasks, pattern={pattern.name}, "
            f"complexity={overall_complexity:.2f}, duration={total_duration}s"
        )

        return result

    def _extract_tasks(self, request: str) -> List[DecomposedTask]:
        """Extract individual tasks from request."""
        # Simple pattern-based extraction; would use NLU in production
        tasks = []
        task_id = 0

        # Split by common connectors
        parts = request.split(" then ")
        if len(parts) == 1:
            parts = request.split(" and then ")
        if len(parts) == 1:
            parts = request.split(" also ")
        if len(parts) == 1:
            parts = [request]

        for part in parts:
            part = part.strip()
            if part:
                task = DecomposedTask(
                    task_id=f"task_{task_id}",
                    description=part,
                    action=self._extract_action(part),
                    estimated_duration_seconds=self._estimate_duration(part),
                    estimated_complexity=self._estimate_complexity(part),
                )
                tasks.append(task)
                task_id += 1

        return tasks if tasks else [
            DecomposedTask(
                task_id="task_0",
                description=request,
                action=self._extract_action(request),
            )
        ]

    def _extract_dependencies(self, request: str, tasks: List[DecomposedTask]) -> Dict[str, List[str]]:
        """Extract task dependencies from request."""
        dependencies = {task.task_id: [] for task in tasks}

        # Look for sequential patterns
        import re
        sequential_pattern = re.compile(r"(first|then|after|next|subsequently)")

        for i, task in enumerate(tasks):
            if i > 0:
                # Simple heuristic: tasks mentioned in order have sequential dependency
                if any(keyword in task.description.lower() for keyword in ["after", "then", "next"]):
                    dependencies[task.task_id] = [tasks[i - 1].task_id]

        return dependencies

    def _extract_action(self, text: str) -> str:
        """Extract the main action from text."""
        action_verbs = [
            "create", "read", "update", "delete", "search", "analyze",
            "transform", "merge", "validate", "execute", "download", "upload"
        ]

        text_lower = text.lower()
        for verb in action_verbs:
            if verb in text_lower:
                return verb

        return "execute"

    def _estimate_duration(self, text: str) -> int:
        """Estimate task duration in seconds."""
        # Simple heuristic
        words = len(text.split())
        if words < 5:
            return 10
        elif words < 20:
            return 60
        elif words < 50:
            return 300
        else:
            return 600

    def _estimate_complexity(self, text: str) -> float:
        """Estimate task complexity (0.0-1.0)."""
        complexity_indicators = {
            "api": 0.8,
            "database": 0.7,
            "multiple": 0.6,
            "transform": 0.5,
            "create": 0.4,
            "read": 0.2,
        }

        score = 0.3  # baseline
        text_lower = text.lower()

        for indicator, value in complexity_indicators.items():
            if indicator in text_lower:
                score = max(score, value)

        return min(1.0, score)

    def _find_parallelizable_chains(self, tasks: List[DecomposedTask], dependencies: Dict[str, List[str]]) -> List[List[str]]:
        """Find chains of tasks that can run in parallel."""
        chains = []
        assigned = set()

        for task in tasks:
            if task.task_id in assigned:
                continue

            # Build chain of independent tasks
            chain = [task.task_id]
            assigned.add(task.task_id)

            # Find tasks that can follow (no shared dependencies)
            for other_task in tasks:
                if other_task.task_id not in assigned:
                    if not any(dep in dependencies.get(other_task.task_id, []) for dep in chain):
                        chain.append(other_task.task_id)
                        assigned.add(other_task.task_id)

            if len(chain) > 1:
                chains.append(chain)

        return chains

    def _generate_optimization_notes(
        self,
        tasks: List[DecomposedTask],
        dependencies: Dict[str, List[str]],
        pattern: TaskPatternType,
        parallel_chains: List[List[str]]
    ) -> List[str]:
        """Generate optimization notes."""
        notes = []

        if pattern == TaskPatternType.PARALLEL and len(tasks) > 1:
            notes.append(f"All {len(tasks)} tasks can run in parallel - execution time will be minimized")

        if len(parallel_chains) > 0:
            total_sequential = sum(len(chain) for chain in parallel_chains)
            if total_sequential < len(tasks):
                notes.append(f"Found {len(parallel_chains)} parallelizable chains - consider parallel execution")

        if len(tasks) > 5:
            notes.append("Large number of tasks - consider breaking into sub-projects")

        avg_complexity = sum(t.estimated_complexity for t in tasks) / len(tasks)
        if avg_complexity > 0.7:
            notes.append("High average complexity - consider additional error handling and checkpoints")

        return notes
