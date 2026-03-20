"""
Task Optimizer for elyan Bot
============================
Analyzes task graphs and suggests optimizations for efficient execution.

Features:
- Task graph analysis
- Optimization opportunity identification
- Task reordering for efficiency
- Execution time prediction
- Parallelization suggestions
- Resource utilization analysis
"""

import logging
from typing import Dict, List, Set, Tuple, Any, Optional
from dataclasses import dataclass
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class TaskInfo:
    """Information about a task for optimization."""
    task_id: str
    estimated_duration: float = 1.0
    estimated_memory: float = 0.0
    dependencies: List[str] = None
    priority: int = 0
    is_io_bound: bool = False
    can_parallelize: bool = True

    def __post_init__(self):
        if self.dependencies is None:
            self.dependencies = []


@dataclass
class OptimizationSuggestion:
    """Suggestion for optimization."""
    suggestion_type: str  # "reorder", "parallelize", "batch", "cache"
    task_ids: List[str]
    expected_speedup: float
    reasoning: str
    priority: int = 0


class TaskGraph:
    """Represents a task execution graph."""

    def __init__(self):
        self.tasks: Dict[str, TaskInfo] = {}
        self.adjacency: Dict[str, Set[str]] = defaultdict(set)
        self.reverse_adjacency: Dict[str, Set[str]] = defaultdict(set)

    def add_task(self, task_info: TaskInfo) -> None:
        """Add a task to the graph."""
        self.tasks[task_info.task_id] = task_info

        for dep in task_info.dependencies:
            self.adjacency[dep].add(task_info.task_id)
            self.reverse_adjacency[task_info.task_id].add(dep)

    def get_critical_path_length(self) -> float:
        """Calculate critical path length (longest dependency chain)."""
        memoized = {}

        def calculate_path_length(task_id: str) -> float:
            if task_id in memoized:
                return memoized[task_id]

            task = self.tasks.get(task_id)
            if not task:
                return 0.0

            if not task.dependencies:
                length = task.estimated_duration
            else:
                max_dep_length = max(
                    calculate_path_length(dep) for dep in task.dependencies
                )
                length = max_dep_length + task.estimated_duration

            memoized[task_id] = length
            return length

        return max((calculate_path_length(task_id) for task_id in self.tasks), default=0.0)

    def get_parallelizable_chains(self) -> List[List[str]]:
        """Identify chains of tasks that can be parallelized."""
        # Find independent task groups at each level
        visited: Set[str] = set()
        chains: List[List[str]] = []

        # Topological sort to find parallelizable chains
        in_degree = {
            task_id: len(self.tasks[task_id].dependencies)
            for task_id in self.tasks
        }

        while visited != set(self.tasks.keys()):
            # Get all tasks with no unvisited dependencies
            available = [
                task_id for task_id in self.tasks
                if task_id not in visited
                and all(dep in visited for dep in self.tasks[task_id].dependencies)
            ]

            if not available:
                # Circular dependency or invalid graph
                break

            # Sort by priority for execution order within this level
            available_sorted = sorted(
                available,
                key=lambda t: (-self.tasks[t].priority, self.tasks[t].estimated_duration),
                reverse=True
            )

            chains.append(available_sorted)
            visited.update(available_sorted)

        return chains

    def get_bottleneck_tasks(self, threshold_percentage: float = 20.0) -> List[str]:
        """
        Identify tasks that are bottlenecks (on critical path and significant duration).
        """
        critical_length = self.get_critical_path_length()
        threshold = critical_length * (threshold_percentage / 100.0)

        # Tasks on critical path
        critical_tasks = []
        for task_id in self.tasks:
            path_length = self._get_path_length_to_end(task_id)
            if path_length >= threshold:
                critical_tasks.append(task_id)

        return critical_tasks

    def _get_path_length_to_end(self, task_id: str) -> float:
        """Calculate path length from task to any end node."""
        memoized = {}

        def calculate(task_id: str) -> float:
            if task_id in memoized:
                return memoized[task_id]

            task = self.tasks.get(task_id)
            if not task:
                return 0.0

            dependents = self.adjacency.get(task_id, set())
            if not dependents:
                length = task.estimated_duration
            else:
                max_dep_length = max(
                    calculate(dep) for dep in dependents
                )
                length = task.estimated_duration + max_dep_length

            memoized[task_id] = length
            return length

        return calculate(task_id)

    def get_memory_hotspots(self) -> List[Tuple[str, float]]:
        """Identify tasks with high memory usage."""
        hotspots = [
            (task_id, task.estimated_memory)
            for task_id, task in self.tasks.items()
            if task.estimated_memory > 0
        ]
        return sorted(hotspots, key=lambda x: x[1], reverse=True)

    def get_io_bound_tasks(self) -> List[str]:
        """Identify IO-bound tasks (good candidates for parallelization)."""
        return [
            task_id for task_id, task in self.tasks.items()
            if task.is_io_bound
        ]


class TaskOptimizer:
    """Analyzes task graphs and suggests optimizations."""

    def __init__(self):
        self.graph: Optional[TaskGraph] = None
        self.suggestions: List[OptimizationSuggestion] = []

    def analyze_graph(self, graph: TaskGraph) -> Dict[str, Any]:
        """Analyze a task graph and return analysis."""
        self.graph = graph
        self.suggestions = []

        analysis = {
            "critical_path_length": graph.get_critical_path_length(),
            "parallelizable_chains": graph.get_parallelizable_chains(),
            "bottleneck_tasks": graph.get_bottleneck_tasks(),
            "io_bound_tasks": graph.get_io_bound_tasks(),
            "memory_hotspots": graph.get_memory_hotspots(),
            "total_tasks": len(graph.tasks),
            "total_sequential_duration": sum(
                task.estimated_duration for task in graph.tasks.values()
            )
        }

        # Generate suggestions
        self._suggest_reordering()
        self._suggest_parallelization()
        self._suggest_batching()

        analysis["suggestions"] = [
            {
                "type": s.suggestion_type,
                "task_ids": s.task_ids,
                "expected_speedup": s.expected_speedup,
                "reasoning": s.reasoning,
                "priority": s.priority
            }
            for s in sorted(self.suggestions, key=lambda s: s.priority, reverse=True)
        ]

        return analysis

    def _suggest_reordering(self) -> None:
        """Suggest task reordering for efficiency."""
        if not self.graph:
            return

        # Find tasks that could be reordered to reduce critical path
        critical_path_length = self.graph.get_critical_path_length()
        bottlenecks = self.graph.get_bottleneck_tasks(10.0)

        if bottlenecks:
            self.suggestions.append(OptimizationSuggestion(
                suggestion_type="reorder",
                task_ids=bottlenecks,
                expected_speedup=1.1,  # 10% speedup estimate
                reasoning=f"Reorder {len(bottlenecks)} bottleneck tasks to reduce critical path",
                priority=8
            ))

    def _suggest_parallelization(self) -> None:
        """Suggest tasks that could be parallelized."""
        if not self.graph:
            return

        io_bound = self.graph.get_io_bound_tasks()
        if io_bound and len(io_bound) > 1:
            speedup = min(len(io_bound), 4)  # Max 4x from IO parallelization
            self.suggestions.append(OptimizationSuggestion(
                suggestion_type="parallelize",
                task_ids=io_bound,
                expected_speedup=float(speedup),
                reasoning=f"Parallelize {len(io_bound)} IO-bound tasks",
                priority=9
            ))

        # Check for independent task chains
        chains = self.graph.get_parallelizable_chains()
        if len(chains) > 1:
            chain_sizes = [len(chain) for chain in chains]
            max_chain_size = max(chain_sizes)

            if max_chain_size > 1:
                speedup = len(chains) / max(1, max_chain_size)
                parallel_tasks = [t for chain in chains for t in chain]

                if len(parallel_tasks) > 2:
                    self.suggestions.append(OptimizationSuggestion(
                        suggestion_type="parallelize",
                        task_ids=parallel_tasks[:min(10, len(parallel_tasks))],
                        expected_speedup=speedup,
                        reasoning=f"Execute {len(chains)} independent chains in parallel",
                        priority=10
                    ))

    def _suggest_batching(self) -> None:
        """Suggest task batching opportunities."""
        if not self.graph:
            return

        # Find consecutive similar tasks that could be batched
        # (This is a simplified heuristic)
        tasks_by_type = defaultdict(list)

        for task_id, task in self.graph.tasks.items():
            # Simple heuristic: short duration tasks are good candidates
            if task.estimated_duration < 1.0:
                task_type = "short_task"
                tasks_by_type[task_type].append(task_id)

        for task_type, task_ids in tasks_by_type.items():
            if len(task_ids) > 2:
                speedup = 1.0 + (len(task_ids) * 0.05)  # 5% per batched task

                self.suggestions.append(OptimizationSuggestion(
                    suggestion_type="batch",
                    task_ids=task_ids[:min(5, len(task_ids))],
                    expected_speedup=speedup,
                    reasoning=f"Batch {len(task_ids)} short-duration tasks to reduce overhead",
                    priority=6
                ))

    def get_optimized_execution_plan(self) -> List[List[str]]:
        """Get an optimized execution plan (task groups to execute in parallel)."""
        if not self.graph:
            return []

        return self.graph.get_parallelizable_chains()

    def estimate_execution_time(self, max_concurrent: int = 4) -> float:
        """Estimate execution time with parallelization."""
        if not self.graph:
            return 0.0

        chains = self.graph.get_parallelizable_chains()
        worker_count = max(1, int(max_concurrent or 1))
        total_time = 0.0
        for chain in chains:
            durations = sorted(
                [
                    float(self.graph.tasks[task_id].estimated_duration)
                    for task_id in chain
                    if task_id in self.graph.tasks
                ],
                reverse=True,
            )
            if not durations:
                continue
            if worker_count == 1:
                total_time += sum(durations)
                continue
            worker_loads = [0.0 for _ in range(min(worker_count, len(durations)))]
            for duration in durations:
                lightest_index = min(range(len(worker_loads)), key=lambda idx: worker_loads[idx])
                worker_loads[lightest_index] += duration
            total_time += max(worker_loads)
        return total_time

    def compare_serial_vs_parallel(self) -> Dict[str, Any]:
        """Compare serial vs parallel execution."""
        if not self.graph:
            return {}

        serial_time = sum(
            task.estimated_duration for task in self.graph.tasks.values()
        )

        parallel_time_2x = self.estimate_execution_time(max_concurrent=2)
        parallel_time_4x = self.estimate_execution_time(max_concurrent=4)
        parallel_time_8x = self.estimate_execution_time(max_concurrent=8)

        return {
            "serial_time": serial_time,
            "parallel_2x": parallel_time_2x,
            "parallel_4x": parallel_time_4x,
            "parallel_8x": parallel_time_8x,
            "speedup_2x": serial_time / max(0.1, parallel_time_2x),
            "speedup_4x": serial_time / max(0.1, parallel_time_4x),
            "speedup_8x": serial_time / max(0.1, parallel_time_8x),
            "critical_path_length": self.graph.get_critical_path_length()
        }


def optimize_task_execution(
    tasks: Dict[str, TaskInfo],
    max_concurrent: int = 4
) -> Dict[str, Any]:
    """
    High-level function to optimize task execution.
    """
    # Build graph
    graph = TaskGraph()
    for task_info in tasks.values():
        graph.add_task(task_info)

    # Analyze and optimize
    optimizer = TaskOptimizer()
    analysis = optimizer.analyze_graph(graph)

    # Get comparison
    comparison = optimizer.compare_serial_vs_parallel()

    return {
        "analysis": analysis,
        "optimized_plan": optimizer.get_optimized_execution_plan(),
        "performance_comparison": comparison,
        "recommendations": analysis["suggestions"][:3]  # Top 3 recommendations
    }
