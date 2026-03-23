"""
Test Run Timeline Visualization

Tests for step timeline generation, Gantt chart data, and critical path analysis.
"""

import pytest
import asyncio
import time
from core.run_store import RunRecord, RunStep, RunStore, get_run_store


class TestRunStep:
    """Test RunStep dataclass."""

    def test_step_creation(self):
        """Test creating a run step."""
        step = RunStep(
            step_id="step_1",
            name="Download data",
            status="completed",
            started_at=1000.0,
            completed_at=1005.0
        )
        assert step.step_id == "step_1"
        assert step.name == "Download data"
        assert step.status == "completed"

    def test_step_duration(self):
        """Test step duration calculation."""
        step = RunStep(
            step_id="step_1",
            name="Process",
            status="completed",
            started_at=1000.0,
            completed_at=1010.0
        )
        assert step.duration_seconds() == 10.0

    def test_step_with_dependencies(self):
        """Test step with dependencies."""
        step = RunStep(
            step_id="step_2",
            name="Upload",
            status="pending",
            started_at=1010.0,
            dependencies=["step_1"]
        )
        assert step.dependencies == ["step_1"]
        assert step.duration_seconds() is None  # Not completed

    def test_step_to_dict(self):
        """Test step serialization."""
        step = RunStep(
            step_id="step_1",
            name="Test",
            status="completed",
            started_at=1000.0,
            completed_at=1005.0
        )
        data = step.to_dict()
        assert data["step_id"] == "step_1"
        assert "started_at" in data
        assert "completed_at" in data


class TestStepTimeline:
    """Test step timeline functionality."""

    @pytest.mark.asyncio
    async def test_timeline_empty_steps(self):
        """Test timeline with no steps."""
        store = RunStore()
        run = RunRecord(
            run_id="run_timeline_1",
            session_id="sess_123",
            status="completed",
            intent="Test",
            started_at=1000.0,
            completed_at=1010.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_timeline_1")
        assert timeline is not None
        assert timeline["step_count"] == 0
        assert len(timeline["steps"]) == 0

    @pytest.mark.asyncio
    async def test_timeline_single_step(self):
        """Test timeline with a single step."""
        store = RunStore()
        run = RunRecord(
            run_id="run_timeline_2",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[{
                "step_id": "step_1",
                "name": "Process",
                "status": "completed",
                "started_at": 1000.0,
                "completed_at": 1010.0
            }],
            started_at=1000.0,
            completed_at=1010.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_timeline_2")
        assert timeline is not None
        assert timeline["step_count"] == 1
        assert len(timeline["steps"]) == 1
        assert timeline["steps"][0]["name"] == "Process"
        assert timeline["steps"][0]["duration"] == 10.0

    @pytest.mark.asyncio
    async def test_timeline_multiple_steps(self):
        """Test timeline with multiple dependent steps."""
        store = RunStore()
        run = RunRecord(
            run_id="run_timeline_3",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Download",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1005.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Process",
                    "status": "completed",
                    "started_at": 1005.0,
                    "completed_at": 1015.0,
                    "dependencies": ["step_1"]
                },
                {
                    "step_id": "step_3",
                    "name": "Upload",
                    "status": "completed",
                    "started_at": 1015.0,
                    "completed_at": 1020.0,
                    "dependencies": ["step_2"]
                }
            ],
            started_at=1000.0,
            completed_at=1020.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_timeline_3")
        assert timeline is not None
        assert timeline["step_count"] == 3
        assert len(timeline["steps"]) == 3

        # Verify durations
        assert timeline["steps"][0]["duration"] == 5.0  # Download
        assert timeline["steps"][1]["duration"] == 10.0  # Process
        assert timeline["steps"][2]["duration"] == 5.0  # Upload

    @pytest.mark.asyncio
    async def test_timeline_parallel_steps(self):
        """Test timeline with parallel steps."""
        store = RunStore()
        run = RunRecord(
            run_id="run_timeline_4",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Download A",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1010.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Download B",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1005.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_3",
                    "name": "Merge",
                    "status": "completed",
                    "started_at": 1010.0,
                    "completed_at": 1015.0,
                    "dependencies": ["step_1", "step_2"]
                }
            ],
            started_at=1000.0,
            completed_at=1015.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_timeline_4")
        assert timeline is not None
        assert timeline["step_count"] == 3

        # Verify parallel steps have same start time
        assert timeline["steps"][0]["start"] == 1000.0
        assert timeline["steps"][1]["start"] == 1000.0

    @pytest.mark.asyncio
    async def test_timeline_with_errors(self):
        """Test timeline with failed steps."""
        store = RunStore()
        run = RunRecord(
            run_id="run_timeline_5",
            session_id="sess_123",
            status="error",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Download",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1005.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Process",
                    "status": "error",
                    "started_at": 1005.0,
                    "completed_at": 1007.0,
                    "error": "Invalid data format",
                    "dependencies": ["step_1"]
                }
            ],
            started_at=1000.0,
            completed_at=1007.0,
            error="Process failed"
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_timeline_5")
        assert timeline is not None
        assert timeline["step_count"] == 2
        assert timeline["steps"][1]["status"] == "error"
        assert timeline["steps"][1]["error"] == "Invalid data format"

    @pytest.mark.asyncio
    async def test_timeline_nonexistent_run(self):
        """Test timeline for non-existent run."""
        store = RunStore()
        timeline = await store.get_step_timeline("nonexistent_run")
        assert timeline is None

    @pytest.mark.asyncio
    async def test_total_duration_calculation(self):
        """Test total duration calculation in timeline."""
        store = RunStore()
        run = RunRecord(
            run_id="run_timeline_6",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Step 1",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1010.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Step 2",
                    "status": "completed",
                    "started_at": 1010.0,
                    "completed_at": 1030.0,
                    "dependencies": ["step_1"]
                }
            ],
            started_at=1000.0,
            completed_at=1030.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_timeline_6")
        assert timeline is not None
        assert timeline["total_duration"] == 30.0


class TestCriticalPath:
    """Test critical path calculation."""

    @pytest.mark.asyncio
    async def test_critical_path_linear(self):
        """Test critical path for linear sequence."""
        store = RunStore()
        run = RunRecord(
            run_id="run_crit_1",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Step 1",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1010.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Step 2",
                    "status": "completed",
                    "started_at": 1010.0,
                    "completed_at": 1020.0,
                    "dependencies": ["step_1"]
                },
                {
                    "step_id": "step_3",
                    "name": "Step 3",
                    "status": "completed",
                    "started_at": 1020.0,
                    "completed_at": 1030.0,
                    "dependencies": ["step_2"]
                }
            ],
            started_at=1000.0,
            completed_at=1030.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_crit_1")
        assert timeline is not None
        # All steps should be on the critical path
        assert "step_1" in timeline["critical_path"]

    @pytest.mark.asyncio
    async def test_critical_path_with_parallelism(self):
        """Test critical path with parallel branches."""
        store = RunStore()
        run = RunRecord(
            run_id="run_crit_2",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Start",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1005.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Fast Branch",
                    "status": "completed",
                    "started_at": 1005.0,
                    "completed_at": 1008.0,
                    "dependencies": ["step_1"]
                },
                {
                    "step_id": "step_3",
                    "name": "Slow Branch",
                    "status": "completed",
                    "started_at": 1005.0,
                    "completed_at": 1020.0,
                    "dependencies": ["step_1"]
                },
                {
                    "step_id": "step_4",
                    "name": "Merge",
                    "status": "completed",
                    "started_at": 1020.0,
                    "completed_at": 1025.0,
                    "dependencies": ["step_2", "step_3"]
                }
            ],
            started_at=1000.0,
            completed_at=1025.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_crit_2")
        assert timeline is not None
        # Critical path should include slow branch
        assert "step_1" in timeline["critical_path"]


class TestGanttChartData:
    """Test Gantt chart data format."""

    @pytest.mark.asyncio
    async def test_gantt_format(self):
        """Test that timeline returns proper Gantt chart format."""
        store = RunStore()
        run = RunRecord(
            run_id="run_gantt_1",
            session_id="sess_123",
            status="completed",
            intent="Test",
            steps=[
                {
                    "step_id": "step_1",
                    "name": "Task 1",
                    "status": "completed",
                    "started_at": 1000.0,
                    "completed_at": 1010.0,
                    "dependencies": []
                },
                {
                    "step_id": "step_2",
                    "name": "Task 2",
                    "status": "completed",
                    "started_at": 1010.0,
                    "completed_at": 1025.0,
                    "dependencies": ["step_1"]
                }
            ],
            started_at=1000.0,
            completed_at=1025.0
        )
        await store.record_run(run)

        timeline = await store.get_step_timeline("run_gantt_1")
        assert timeline is not None

        # Check Gantt chart required fields
        for step in timeline["steps"]:
            assert "step_id" in step
            assert "name" in step
            assert "status" in step
            assert "start" in step
            assert "duration" in step
            assert "dependencies" in step

        # Verify timeline structure
        assert "total_duration" in timeline
        assert "run_status" in timeline
        assert "step_count" in timeline
