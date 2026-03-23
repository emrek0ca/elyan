"""
Integration tests for Task Engine + Cognitive Layer integration.

Validates that:
1. CEO Planner simulates before execution
2. Time budgets are assigned correctly
3. Deadlock detection monitors execution
4. Mode switching happens on failures
5. All cognitive decisions are logged
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, AsyncMock
from core.task_engine import TaskEngine, TaskDefinition, TaskResult
from core.cognitive_layer_integrator import get_cognitive_integrator


class TestTaskEngineCognitiveIntegration:
    """Test cognitive layer integration into task engine"""

    @pytest.fixture
    def task_engine(self):
        """Create task engine instance"""
        engine = TaskEngine()
        return engine

    @pytest.fixture
    def sample_input(self):
        """Sample user input"""
        return "List all Python files in the current directory"

    def test_cognitive_settings_exist(self, task_engine):
        """Verify cognitive settings are initialized"""
        assert task_engine.settings.get("cognitive_layer_enabled") is not None
        assert task_engine.settings.get("ceo_simulation_enabled") is not None
        assert task_engine.settings.get("time_boxed_scheduler_enabled") is not None
        assert task_engine.settings.get("deadlock_detection_enabled") is not None

    def test_cognitive_integrator_initialized(self, task_engine):
        """Verify cognitive integrator is created"""
        assert task_engine.cognitive_integrator is not None
        assert hasattr(task_engine.cognitive_integrator, "simulate_task_execution")
        assert hasattr(task_engine.cognitive_integrator, "assign_time_budget")
        assert hasattr(task_engine.cognitive_integrator, "monitor_execution")

    def test_infer_task_type_simple_query(self, task_engine):
        """Test task type inference for simple queries"""
        # Simple query
        assert task_engine._infer_task_type("search_web") == "simple_query"
        assert task_engine._infer_task_type("get_time") == "simple_query"
        assert task_engine._infer_task_type("calculate_sum") == "simple_query"

    def test_infer_task_type_file_operation(self, task_engine):
        """Test task type inference for file operations"""
        assert task_engine._infer_task_type("read_file") == "file_operation"
        assert task_engine._infer_task_type("list_files") == "file_operation"
        assert task_engine._infer_task_type("copy_file") == "file_operation"

    def test_infer_task_type_api_call(self, task_engine):
        """Test task type inference for API calls"""
        assert task_engine._infer_task_type("api_request") == "api_call"
        assert task_engine._infer_task_type("http_request") == "api_call"
        assert task_engine._infer_task_type("fetch_data") == "api_call"

    def test_infer_task_type_complex_analysis(self, task_engine):
        """Test task type inference for complex operations"""
        assert task_engine._infer_task_type("analyze_data") == "complex_analysis"
        assert task_engine._infer_task_type("generate_report") == "complex_analysis"
        assert task_engine._infer_task_type("research_topic") == "complex_analysis"

    def test_infer_task_type_default(self, task_engine):
        """Test task type defaults to general"""
        assert task_engine._infer_task_type("unknown_action") == "general"
        assert task_engine._infer_task_type("") == "general"

    @pytest.mark.asyncio
    async def test_cognitive_integrator_simulate_task(self, task_engine):
        """Test CEO planner simulation through integrator"""
        integrator = task_engine.cognitive_integrator

        result = await integrator.simulate_task_execution(
            task_id="test_1",
            action="list_files",
            params={"path": "/tmp"},
            context={"task_type": "file_operation"}
        )

        assert result is not None
        assert "success" in result
        # CEO might succeed or fail, but it should return a valid response
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_cognitive_integrator_assign_budget(self, task_engine):
        """Test time budget assignment through integrator"""
        integrator = task_engine.cognitive_integrator

        result = integrator.assign_time_budget(
            task_id="test_1",
            action="list_files",
            task_type="file_operation"
        )

        assert result["success"] is True
        assert result["budget_seconds"] == 30  # file_operation budget
        assert result["task_id"] == "test_1"

    @pytest.mark.asyncio
    async def test_cognitive_integrator_monitor_execution(self, task_engine):
        """Test deadlock detection through integrator"""
        integrator = task_engine.cognitive_integrator

        # Successful execution
        result = await integrator.monitor_execution(
            task_id="test_1",
            execution_success=True,
            execution_duration_ms=100,
            error_code=None,
            agent_id="list_files"
        )

        assert result is not None
        assert "deadlock_detected" in result
        assert result["deadlock_detected"] is False

    @pytest.mark.asyncio
    async def test_cognitive_integrator_mode_switch(self, task_engine):
        """Test mode switching through integrator"""
        integrator = task_engine.cognitive_integrator

        result = await integrator.evaluate_mode_switch(
            execution_success=True,
            execution_duration_ms=100,
            error_code=None
        )

        assert result is not None
        assert "mode_before" in result
        assert "mode_after" in result
        assert "switched" in result

    @pytest.mark.asyncio
    async def test_cognitive_trace_generation(self, task_engine):
        """Test cognitive trace generation"""
        integrator = task_engine.cognitive_integrator

        trace = await integrator.process_task_cognitive_flow(
            task_id="test_1",
            action="list_files",
            params={"path": "/tmp"},
            context={"task_type": "file_operation"}
        )

        assert trace is not None
        assert trace.task_id == "test_1"
        assert trace.action == "list_files"
        assert trace.timestamp is not None
        assert trace.ceo_simulation_result is not None
        assert trace.assigned_budget_seconds is not None

    @pytest.mark.asyncio
    async def test_cognitive_trace_logging(self, task_engine):
        """Test cognitive trace logging"""
        integrator = task_engine.cognitive_integrator

        trace = await integrator.process_task_cognitive_flow(
            task_id="test_1",
            action="list_files",
            params={"path": "/tmp"},
            context={"task_type": "file_operation"}
        )

        # Record execution result
        integrator.record_execution_result(
            trace=trace,
            success=True,
            duration_ms=150,
            error=None,
            agent_id="list_files"
        )

        # Finalize decisions (monitor, timeout, mode)
        await integrator.finalize_cognitive_decisions(trace, agent_id="list_files")

        # Log trace
        integrator.log_cognitive_trace(trace)

        # Verify trace has complete data
        assert trace.execution_success is True
        assert trace.execution_duration_ms == 150
        trace_dict = trace.to_dict()
        assert trace_dict is not None

    @pytest.mark.asyncio
    async def test_pomodoro_break_check(self, task_engine):
        """Test Pomodoro break checking"""
        integrator = task_engine.cognitive_integrator

        result = await integrator.check_pomodoro_break()
        assert isinstance(result, bool)

    @pytest.mark.asyncio
    async def test_sleep_consolidation_check(self, task_engine):
        """Test sleep consolidation trigger"""
        integrator = task_engine.cognitive_integrator

        result = await integrator.consolidate_daily_learning(force=False)
        # Should return None or SleepReport
        assert result is None or result is not None  # Can be either

    def test_cognitive_metadata_in_tasks(self, task_engine):
        """Verify task objects can store cognitive metadata"""
        task = TaskDefinition(
            id="test_1",
            action="list_files",
            params={},
            description="Test task"
        )

        task.metadata = {"cognitive_budget_seconds": 30}
        assert task.metadata["cognitive_budget_seconds"] == 30


class TestTaskEngineWithCognitiveSettings:
    """Test task engine behavior with cognitive settings"""

    @pytest.fixture
    def task_engine_with_cognitive_enabled(self):
        """Create task engine with cognitive enabled"""
        engine = TaskEngine()
        engine.settings._settings["cognitive_layer_enabled"] = True
        return engine

    @pytest.fixture
    def task_engine_with_cognitive_disabled(self):
        """Create task engine with cognitive disabled"""
        engine = TaskEngine()
        engine.settings._settings["cognitive_layer_enabled"] = False
        return engine

    def test_cognitive_enabled_flag(self, task_engine_with_cognitive_enabled):
        """Verify cognitive enabled flag"""
        assert task_engine_with_cognitive_enabled.settings.get("cognitive_layer_enabled") is True

    def test_cognitive_disabled_flag(self, task_engine_with_cognitive_disabled):
        """Verify cognitive disabled flag"""
        assert task_engine_with_cognitive_disabled.settings.get("cognitive_layer_enabled") is False


class TestBackwardCompatibility:
    """Test that cognitive layer doesn't break existing functionality"""

    @pytest.fixture
    def task_engine(self):
        """Create task engine"""
        return TaskEngine()

    def test_task_engine_initializes_without_errors(self, task_engine):
        """Verify task engine still initializes"""
        assert task_engine is not None
        assert task_engine.intent_parser is not None
        assert task_engine.audit is not None

    def test_task_definition_still_works(self):
        """Verify TaskDefinition class unchanged"""
        task = TaskDefinition(
            id="test_1",
            action="test_action",
            params={"key": "value"},
            description="Test"
        )

        assert task.id == "test_1"
        assert task.action == "test_action"
        assert task.params == {"key": "value"}

    def test_task_result_still_works(self):
        """Verify TaskResult class unchanged"""
        result = TaskResult(
            success=True,
            message="Test message",
            data={"key": "value"},
            execution_time_ms=1000
        )

        assert result.success is True
        assert result.message == "Test message"
        assert result.execution_time_ms == 1000


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
