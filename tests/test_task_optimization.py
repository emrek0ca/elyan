"""
Tests for Task Optimization System
===================================
"""

import pytest
from core.task_optimizer import (
    TaskInfo,
    TaskGraph,
    TaskOptimizer,
    OptimizationSuggestion,
    optimize_task_execution
)


class TestTaskInfo:
    """Tests for TaskInfo."""

    def test_task_info_creation(self):
        """Test creating task info."""
        task = TaskInfo(
            task_id="task1",
            estimated_duration=2.5,
            estimated_memory=100.0,
            dependencies=["task0"],
            priority=1,
            is_io_bound=True
        )

        assert task.task_id == "task1"
        assert task.estimated_duration == 2.5
        assert task.is_io_bound

    def test_task_info_defaults(self):
        """Test task info defaults."""
        task = TaskInfo(task_id="task1")

        assert task.estimated_duration == 1.0
        assert task.estimated_memory == 0.0
        assert task.dependencies == []
        assert not task.is_io_bound


class TestTaskGraph:
    """Tests for TaskGraph."""

    def test_add_task(self):
        """Test adding tasks to graph."""
        graph = TaskGraph()

        task1 = TaskInfo(task_id="t1")
        graph.add_task(task1)

        assert "t1" in graph.tasks

    def test_dependency_tracking(self):
        """Test dependency tracking."""
        graph = TaskGraph()

        task1 = TaskInfo(task_id="t1", estimated_duration=1.0)
        task2 = TaskInfo(task_id="t2", estimated_duration=2.0, dependencies=["t1"])

        graph.add_task(task1)
        graph.add_task(task2)

        assert "t2" in graph.adjacency["t1"]
        assert "t1" in graph.reverse_adjacency["t2"]

    def test_critical_path_no_dependencies(self):
        """Test critical path calculation with no dependencies."""
        graph = TaskGraph()

        for i in range(3):
            task = TaskInfo(task_id=f"t{i}", estimated_duration=1.0)
            graph.add_task(task)

        # All independent, so critical path is just one task duration
        critical = graph.get_critical_path_length()
        assert critical == 1.0

    def test_critical_path_linear(self):
        """Test critical path with linear dependencies."""
        graph = TaskGraph()

        # t1 -> t2 -> t3 (durations: 1, 2, 3)
        graph.add_task(TaskInfo(task_id="t1", estimated_duration=1.0))
        graph.add_task(TaskInfo(task_id="t2", estimated_duration=2.0, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t3", estimated_duration=3.0, dependencies=["t2"]))

        critical = graph.get_critical_path_length()
        assert critical == 6.0  # 1 + 2 + 3

    def test_critical_path_branching(self):
        """Test critical path with branching."""
        graph = TaskGraph()

        # t1 -> t2, t3
        # t2, t3 -> t4
        graph.add_task(TaskInfo(task_id="t1", estimated_duration=1.0))
        graph.add_task(TaskInfo(task_id="t2", estimated_duration=5.0, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t3", estimated_duration=2.0, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t4", estimated_duration=1.0, dependencies=["t2", "t3"]))

        critical = graph.get_critical_path_length()
        # Path: t1 (1) -> t2 (5) -> t4 (1) = 7
        assert critical == 7.0

    def test_get_parallelizable_chains(self):
        """Test identifying parallelizable chains."""
        graph = TaskGraph()

        # t1 -> t2, t3, t4 (all independent at same level)
        graph.add_task(TaskInfo(task_id="t1", estimated_duration=1.0))
        graph.add_task(TaskInfo(task_id="t2", estimated_duration=1.0, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t3", estimated_duration=1.0, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t4", estimated_duration=1.0, dependencies=["t1"]))

        chains = graph.get_parallelizable_chains()

        # Should have 2 chains: [t1] and [t2, t3, t4]
        assert len(chains) >= 2
        assert len(chains[0]) == 1  # t1 first
        assert set(chains[1]) == {"t2", "t3", "t4"}

    def test_get_bottleneck_tasks(self):
        """Test identifying bottleneck tasks."""
        graph = TaskGraph()

        # t1 (10s) -> t2 (0.5s) -> t3 (10s)
        graph.add_task(TaskInfo(task_id="t1", estimated_duration=10.0))
        graph.add_task(TaskInfo(task_id="t2", estimated_duration=0.5, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t3", estimated_duration=10.0, dependencies=["t2"]))

        bottlenecks = graph.get_bottleneck_tasks(threshold_percentage=20.0)

        # t3 should be a bottleneck (on critical path, duration 10)
        assert len(bottlenecks) > 0

    def test_get_memory_hotspots(self):
        """Test identifying memory hotspots."""
        graph = TaskGraph()

        graph.add_task(TaskInfo(task_id="t1", estimated_duration=1.0, estimated_memory=100.0))
        graph.add_task(TaskInfo(task_id="t2", estimated_duration=1.0, estimated_memory=500.0))
        graph.add_task(TaskInfo(task_id="t3", estimated_duration=1.0, estimated_memory=200.0))

        hotspots = graph.get_memory_hotspots()

        # Should be sorted by memory descending
        assert len(hotspots) == 3
        assert hotspots[0][0] == "t2"  # 500.0 highest
        assert hotspots[1][0] == "t3"  # 200.0 middle
        assert hotspots[2][0] == "t1"  # 100.0 lowest

    def test_get_io_bound_tasks(self):
        """Test identifying IO-bound tasks."""
        graph = TaskGraph()

        graph.add_task(TaskInfo(task_id="t1", is_io_bound=True))
        graph.add_task(TaskInfo(task_id="t2", is_io_bound=False))
        graph.add_task(TaskInfo(task_id="t3", is_io_bound=True))

        io_tasks = graph.get_io_bound_tasks()

        assert len(io_tasks) == 2
        assert "t1" in io_tasks
        assert "t3" in io_tasks
        assert "t2" not in io_tasks


class TestTaskOptimizer:
    """Tests for TaskOptimizer."""

    def test_optimizer_initialization(self):
        """Test optimizer initialization."""
        optimizer = TaskOptimizer()

        assert optimizer.graph is None
        assert len(optimizer.suggestions) == 0

    def test_analyze_simple_graph(self):
        """Test analyzing a simple graph."""
        graph = TaskGraph()

        for i in range(3):
            graph.add_task(TaskInfo(task_id=f"t{i}", estimated_duration=1.0))

        optimizer = TaskOptimizer()
        analysis = optimizer.analyze_graph(graph)

        assert "critical_path_length" in analysis
        assert "parallelizable_chains" in analysis
        assert "bottleneck_tasks" in analysis
        assert "total_tasks" in analysis
        assert analysis["total_tasks"] == 3

    def test_analyze_with_suggestions(self):
        """Test that analysis includes suggestions."""
        graph = TaskGraph()

        # Create IO-bound tasks that could be parallelized
        for i in range(3):
            graph.add_task(TaskInfo(
                task_id=f"t{i}",
                estimated_duration=1.0,
                is_io_bound=True
            ))

        optimizer = TaskOptimizer()
        analysis = optimizer.analyze_graph(graph)

        # Should have suggestions
        assert "suggestions" in analysis
        assert len(analysis["suggestions"]) > 0

    def test_optimized_execution_plan(self):
        """Test getting optimized execution plan."""
        graph = TaskGraph()

        # t1 -> t2, t3
        graph.add_task(TaskInfo(task_id="t1", estimated_duration=1.0))
        graph.add_task(TaskInfo(task_id="t2", estimated_duration=1.0, dependencies=["t1"]))
        graph.add_task(TaskInfo(task_id="t3", estimated_duration=1.0, dependencies=["t1"]))

        optimizer = TaskOptimizer()
        optimizer.analyze_graph(graph)
        plan = optimizer.get_optimized_execution_plan()

        # Should have execution plan
        assert len(plan) > 0
        # First group should have t1
        assert "t1" in plan[0]

    def test_estimate_execution_time_serial(self):
        """Test execution time estimation for serial case."""
        graph = TaskGraph()

        # 3 tasks, 1s each
        for i in range(3):
            graph.add_task(TaskInfo(task_id=f"t{i}", estimated_duration=1.0))

        optimizer = TaskOptimizer()
        optimizer.analyze_graph(graph)

        # With 1 concurrent, should be ~3s
        time_1x = optimizer.estimate_execution_time(max_concurrent=1)
        assert time_1x >= 3.0

    def test_estimate_execution_time_parallel(self):
        """Test execution time estimation for parallel case."""
        graph = TaskGraph()

        # 3 independent tasks, 1s each
        for i in range(3):
            graph.add_task(TaskInfo(task_id=f"t{i}", estimated_duration=1.0))

        optimizer = TaskOptimizer()
        optimizer.analyze_graph(graph)

        # With 3 concurrent, should be ~1s
        time_3x = optimizer.estimate_execution_time(max_concurrent=3)
        assert time_3x <= 1.5

    def test_compare_serial_vs_parallel(self):
        """Test serial vs parallel comparison."""
        graph = TaskGraph()

        # 4 independent IO-bound tasks
        for i in range(4):
            graph.add_task(TaskInfo(
                task_id=f"t{i}",
                estimated_duration=1.0,
                is_io_bound=True
            ))

        optimizer = TaskOptimizer()
        optimizer.analyze_graph(graph)
        comparison = optimizer.compare_serial_vs_parallel()

        assert "serial_time" in comparison
        assert "parallel_2x" in comparison
        assert "parallel_4x" in comparison
        assert "speedup_2x" in comparison
        assert "speedup_4x" in comparison

        # Parallel should be faster than serial
        assert comparison["parallel_4x"] < comparison["serial_time"]
        # Speedup should be > 1
        assert comparison["speedup_4x"] > 1.0

    def test_suggestions_ordering_by_priority(self):
        """Test that suggestions are ordered by priority."""
        graph = TaskGraph()

        # Many tasks to trigger multiple suggestions
        for i in range(10):
            graph.add_task(TaskInfo(
                task_id=f"t{i}",
                estimated_duration=0.5,
                is_io_bound=True
            ))

        optimizer = TaskOptimizer()
        analysis = optimizer.analyze_graph(graph)

        suggestions = analysis["suggestions"]
        if len(suggestions) > 1:
            # Check that they're sorted by priority (descending)
            priorities = [s["priority"] for s in suggestions]
            assert priorities == sorted(priorities, reverse=True)


class TestOptimizationSuggestion:
    """Tests for OptimizationSuggestion."""

    def test_suggestion_creation(self):
        """Test creating optimization suggestion."""
        suggestion = OptimizationSuggestion(
            suggestion_type="parallelize",
            task_ids=["t1", "t2", "t3"],
            expected_speedup=3.0,
            reasoning="These tasks are IO-bound and independent",
            priority=9
        )

        assert suggestion.suggestion_type == "parallelize"
        assert len(suggestion.task_ids) == 3
        assert suggestion.expected_speedup == 3.0
        assert suggestion.priority == 9


class TestOptimizationFunction:
    """Tests for high-level optimization function."""

    def test_optimize_task_execution(self):
        """Test high-level optimization function."""
        tasks = {
            "t1": TaskInfo(task_id="t1", estimated_duration=1.0),
            "t2": TaskInfo(task_id="t2", estimated_duration=1.0, dependencies=["t1"]),
            "t3": TaskInfo(task_id="t3", estimated_duration=1.0, dependencies=["t1"]),
        }

        result = optimize_task_execution(tasks, max_concurrent=2)

        assert "analysis" in result
        assert "optimized_plan" in result
        assert "performance_comparison" in result
        assert "recommendations" in result

    def test_optimize_complex_graph(self):
        """Test optimization of complex graph."""
        tasks = {
            "download": TaskInfo(task_id="download", estimated_duration=5.0, is_io_bound=True),
            "process1": TaskInfo(task_id="process1", estimated_duration=2.0, dependencies=["download"]),
            "process2": TaskInfo(task_id="process2", estimated_duration=2.0, dependencies=["download"]),
            "process3": TaskInfo(task_id="process3", estimated_duration=2.0, dependencies=["download"]),
            "merge": TaskInfo(task_id="merge", estimated_duration=1.0,
                            dependencies=["process1", "process2", "process3"]),
        }

        result = optimize_task_execution(tasks, max_concurrent=4)

        comparison = result["performance_comparison"]
        # 4x parallel should be significantly faster than serial
        assert comparison["speedup_4x"] > 1.0

        # Critical path should be identified
        assert comparison["critical_path_length"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
