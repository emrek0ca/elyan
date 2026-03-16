"""
tests/test_phase4_integration.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4 Integration Tests
Full end-to-end testing of NLU, decomposition, and coordination.
─────────────────────────────────────────────────────────────────────────────
"""

import pytest
import asyncio
from core.advanced_nlu import AdvancedNLU
from core.advanced_task_decomposer import AdvancedTaskDecomposer
from core.main_agent_coordinator import MainAgentCoordinator, get_main_agent_coordinator
from core.task_state_machine import TaskStateMachine, TaskState
from core.error_recovery_engine import ErrorRecoveryEngine, ErrorCategory
from core.result_aggregator import ResultAggregator, AggregationMode
from core.execution_quality_scorer import ExecutionQualityScorer, ExecutionMetrics


class TestPhase4NLUDecomposition:
    """Test NLU and task decomposition integration."""

    @pytest.mark.asyncio
    async def test_nlu_decomposition_pipeline(self):
        """Test NLU -> Decomposition pipeline."""
        nlu = AdvancedNLU()
        decomposer = AdvancedTaskDecomposer()

        # NLU analysis
        nlu_result = await nlu.analyze("create a file and read its content")
        assert nlu_result.confidence > 0.5

        # Task decomposition
        decomposition = await decomposer.decompose("create a file and read its content")
        assert len(decomposition.tasks) >= 1
        assert decomposition.overall_complexity >= 0.0

    @pytest.mark.asyncio
    async def test_complex_task_decomposition(self):
        """Test decomposition of complex tasks."""
        decomposer = AdvancedTaskDecomposer()

        decomposition = await decomposer.decompose(
            "create a database, insert 100 records, analyze the data, "
            "then generate a report and send it by email"
        )

        assert len(decomposition.tasks) > 3
        assert len(decomposition.execution_order) > 0
        assert decomposition.task_pattern is not None

    @pytest.mark.asyncio
    async def test_dependency_detection(self):
        """Test task dependency detection."""
        decomposer = AdvancedTaskDecomposer()

        decomposition = await decomposer.decompose(
            "first create the file, then write to it, finally read from it"
        )

        # Check that tasks have proper dependencies
        assert decomposition.critical_path is not None
        assert len(decomposition.critical_path) > 0


class TestPhase4MainAgentCoordinator:
    """Test main agent coordinator."""

    @pytest.mark.asyncio
    async def test_coordinator_initialization(self):
        """Test coordinator initialization."""
        coordinator = await get_main_agent_coordinator()
        assert coordinator is not None
        assert coordinator.pool_manager is not None

    @pytest.mark.asyncio
    async def test_simple_task_processing(self):
        """Test processing simple task."""
        coordinator = await get_main_agent_coordinator()

        result = await coordinator.process("list all files")
        assert result.status is not None
        assert result.session_id is not None
        assert result.execution_time_ms >= 0

    @pytest.mark.asyncio
    async def test_complex_task_processing(self):
        """Test processing complex task."""
        coordinator = await get_main_agent_coordinator()

        result = await coordinator.process(
            "create a CSV file with test data and verify it exists"
        )

        assert result.status in ("success", "partial_success", "failed")
        assert len(result.notes) > 0

    @pytest.mark.asyncio
    async def test_error_handling_in_coordination(self):
        """Test error handling during coordination."""
        coordinator = await get_main_agent_coordinator()

        # This should handle gracefully
        result = await coordinator.process("do something impossible")
        assert result is not None


class TestTaskStateMachine:
    """Test task state machine."""

    def test_state_transitions(self):
        """Test valid state transitions."""
        sm = TaskStateMachine("session_1")
        sm.register_task("task_1")

        # Valid transition
        assert sm.transition("task_1", TaskState.RUNNING)
        assert sm.task_states["task_1"] == TaskState.RUNNING

        # Another valid transition
        assert sm.transition("task_1", TaskState.SUCCESS)
        assert sm.task_states["task_1"] == TaskState.SUCCESS

    def test_invalid_transitions(self):
        """Test invalid state transitions."""
        sm = TaskStateMachine("session_1")
        sm.register_task("task_1")

        sm.transition("task_1", TaskState.RUNNING)
        # Invalid: RUNNING -> PENDING
        assert not sm.transition("task_1", TaskState.PENDING)

    def test_retry_handling(self):
        """Test retry logic."""
        sm = TaskStateMachine("session_1", max_retries=3)
        sm.register_task("task_1")

        sm.transition("task_1", TaskState.RUNNING)
        success = sm.mark_failure("task_1")

        assert success
        assert sm.task_states["task_1"] == TaskState.RETRY
        assert sm.retry_counts["task_1"] == 1

    def test_checkpoint_creation(self):
        """Test checkpoint creation and retrieval."""
        sm = TaskStateMachine("session_1")
        sm.register_task("task_1")

        data = {"step": 1, "progress": 0.5}
        sm.checkpoint("task_1", data)

        checkpoint = sm.get_checkpoint("task_1")
        assert checkpoint is not None
        assert checkpoint.data == data

    def test_resource_tracking(self):
        """Test resource registration and cleanup."""
        sm = TaskStateMachine("session_1")

        sm.register_resource("file_1", {"name": "test.txt"})
        sm.register_resource("connection_1", {"type": "database"})

        assert len(sm.resources) == 2

    def test_status_reporting(self):
        """Test status reporting."""
        sm = TaskStateMachine("session_1")
        sm.register_task("task_1")
        sm.register_task("task_2")

        sm.transition("task_1", TaskState.RUNNING)
        sm.transition("task_2", TaskState.RUNNING)

        status = sm.get_status()
        assert status["total_tasks"] == 2
        assert status["completed_tasks"] == 0


class TestErrorRecoveryEngine:
    """Test error recovery."""

    def test_error_categorization(self):
        """Test error categorization."""
        engine = ErrorRecoveryEngine()

        # Test timeout
        timeout_error = TimeoutError("Request timed out")
        category = engine.categorizer.categorize(timeout_error)
        assert category == ErrorCategory.TIMEOUT

        # Test network error
        network_error = ConnectionError("Network unavailable")
        category = engine.categorizer.categorize(network_error)
        assert category == ErrorCategory.NETWORK

    def test_recovery_planning(self):
        """Test recovery plan generation."""
        engine = ErrorRecoveryEngine()

        from core.error_recovery_engine import ErrorAnalysis
        analysis = ErrorAnalysis(
            error_message="Timeout",
            error_type="TimeoutError",
            category=ErrorCategory.TIMEOUT,
            severity=0.6,
            stack_trace="",
            context={},
            suggested_recovery=None,
        )

        plan = engine.planner.plan_recovery(analysis)
        assert plan is not None
        assert len(plan.steps) > 0

    @pytest.mark.asyncio
    async def test_recovery_execution(self):
        """Test recovery execution."""
        engine = ErrorRecoveryEngine()

        async def failing_task(**kwargs):
            raise ValueError("Task failed")

        # This should handle gracefully
        result = await engine.handle_error(
            ValueError("Test error"),
            task_fn=failing_task,
            context={}
        )
        # Result may be None due to failure, but shouldn't raise


class TestResultAggregator:
    """Test result aggregation."""

    def test_sequential_aggregation(self):
        """Test sequential result aggregation."""
        aggregator = ResultAggregator()

        results = {
            "task_1": {"step": 1},
            "task_2": {"step": 2},
            "task_3": {"step": 3},
        }

        aggregated = aggregator.aggregate(results, AggregationMode.SEQUENTIAL)
        assert aggregated is not None

    def test_parallel_aggregation(self):
        """Test parallel result aggregation."""
        aggregator = ResultAggregator()

        results = {
            "task_1": [1, 2, 3],
            "task_2": [4, 5, 6],
        }

        aggregated = aggregator.aggregate(results, AggregationMode.PARALLEL)
        assert isinstance(aggregated, list)
        assert len(aggregated) == 6

    def test_conditional_aggregation(self):
        """Test conditional aggregation."""
        aggregator = ResultAggregator()

        results = {
            "task_1": {"success": True, "data": "A"},
            "task_2": {"success": False, "data": "B"},
        }

        aggregated = aggregator.aggregate(results, AggregationMode.CONDITIONAL)
        assert aggregated["success"] is True

    def test_result_validation(self):
        """Test result validation."""
        aggregator = ResultAggregator()

        valid_result = {"name": "test", "value": 42}
        schema = {"name": str, "value": int}

        validation = aggregator.validator.validate(valid_result, schema)
        assert validation.is_valid
        assert validation.completeness > 0

    def test_result_transformation(self):
        """Test result format transformation."""
        aggregator = ResultAggregator()

        data = {"key": "value", "number": 42}

        json_str = aggregator.transformer.transform(data, "json")
        assert '"key"' in json_str

        csv_str = aggregator.transformer.transform([data], "csv")
        assert "key" in csv_str


class TestExecutionQualityScorer:
    """Test execution quality scoring."""

    def test_performance_scoring(self):
        """Test performance score calculation."""
        scorer = ExecutionQualityScorer()

        score = scorer.performance_analyzer.score_performance(500)  # 500ms
        assert 0.0 <= score <= 1.0

    def test_reliability_scoring(self):
        """Test reliability score calculation."""
        scorer = ExecutionQualityScorer()

        metrics = ExecutionMetrics(
            task_id="task_1",
            success=True,
            duration_ms=1000,
            error_count=0,
            retries=0,
        )

        score = scorer.reliability_analyzer.score_reliability(metrics)
        assert score > 0.5

    def test_resource_scoring(self):
        """Test resource usage scoring."""
        scorer = ExecutionQualityScorer()

        metrics = ExecutionMetrics(
            task_id="task_1",
            success=True,
            duration_ms=1000,
            resource_usage_mb=100,
        )

        score = scorer.resource_analyzer.score_resource_usage(metrics)
        assert 0.0 <= score <= 1.0

    def test_overall_quality_score(self):
        """Test overall quality scoring."""
        scorer = ExecutionQualityScorer()

        metrics = ExecutionMetrics(
            task_id="task_1",
            success=True,
            duration_ms=1000,
            error_count=0,
            warning_count=0,
            retries=0,
        )

        score = scorer.score_execution(
            metrics,
            result={"success": True, "data": "test"},
            expected_fields=["success", "data"]
        )

        assert score.overall_score > 0.5
        assert score.confidence > 0.5
        assert score.task_id == "task_1"

    def test_anomaly_detection(self):
        """Test anomaly detection."""
        scorer = ExecutionQualityScorer()

        metrics = ExecutionMetrics(
            task_id="task_1",
            success=False,
            duration_ms=5000,
            error_count=5,
            retries=3,
            resource_usage_mb=1000,
        )

        score = scorer.score_execution(metrics)
        assert len(score.anomalies) > 0
        assert len(score.suggestions) > 0


class TestPhase4PerformanceRequirements:
    """Test performance requirements."""

    @pytest.mark.asyncio
    async def test_nlu_performance(self):
        """Test NLU < 500ms requirement."""
        nlu = AdvancedNLU()

        result = await nlu.analyze("create a test file")
        assert result.processing_time_ms < 500

    @pytest.mark.asyncio
    async def test_decomposition_performance(self):
        """Test decomposition < 200ms requirement."""
        decomposer = AdvancedTaskDecomposer()

        decomposition = await decomposer.decompose("create files")
        assert decomposition.processing_time_ms < 200


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
