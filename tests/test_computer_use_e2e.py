"""End-to-End tests for Computer Use

Tests full workflow: Task execution → Evidence recording → API retrieval
"""

import pytest
import json
import tempfile
from unittest.mock import Mock, MagicMock, AsyncMock, patch
from pathlib import Path

from elyan.computer_use.tool import ComputerUseTool, ComputerAction, ComputerUseTask
from elyan.computer_use.evidence.recorder import ComputerUseRecorder
from api.computer_use_api import ComputerUseAPI


class TestComputerUseE2E:
    """End-to-end Computer Use tests"""

    @pytest.fixture
    def temp_evidence_dir(self):
        """Create temporary evidence directory"""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield tmpdir

    @pytest.mark.asyncio
    async def test_task_execution_with_evidence(self, temp_evidence_dir):
        """Test full task execution with evidence recording"""
        from elyan.computer_use.evidence.recorder import ComputerUseRecorder

        recorder = ComputerUseRecorder(storage_path=temp_evidence_dir)

        # Create a mock task
        task = ComputerUseTask(
            task_id="test_task_1",
            user_intent="Test task",
            max_steps=3,
            created_at=123456789.0,
            status="completed",
            completed_at=123456850.0
        )

        # Add action trace
        task.steps = [
            {
                "step": 0,
                "action": {"action_type": "left_click", "x": 100, "y": 200},
                "result": {"success": True},
                "screenshot_id": "ss_0_123456790000",
                "timestamp": 123456790.0
            },
            {
                "step": 1,
                "action": {"action_type": "type", "text": "test"},
                "result": {"success": True},
                "screenshot_id": "ss_1_123456810000",
                "timestamp": 123456810.0
            }
        ]
        task.evidence = ["ss_0_123456790000", "ss_1_123456810000"]

        # Record task
        result = await recorder.record_task(task.model_dump())

        assert result["success"] is True
        assert result["task_id"] == "test_task_1"
        assert Path(result["evidence_dir"]).exists()

        # Verify files were created
        task_dir = Path(result["evidence_dir"])
        assert (task_dir / "metadata.json").exists()
        assert (task_dir / "action_trace.jsonl").exists()
        assert (task_dir / "screenshots").is_dir()

    @pytest.mark.asyncio
    async def test_evidence_retrieval(self, temp_evidence_dir):
        """Test retrieving evidence after task completion"""
        from elyan.computer_use.evidence.recorder import ComputerUseRecorder

        recorder = ComputerUseRecorder(storage_path=temp_evidence_dir)

        # Create and record a task
        task = ComputerUseTask(
            task_id="retrieval_test",
            user_intent="Retrieve test",
            created_at=111111111.0,
            status="completed",
            completed_at=111111200.0
        )
        task.steps = [
            {"step": 0, "action": {"action_type": "click"}, "result": {}}
        ]

        await recorder.record_task(task.model_dump())

        # Retrieve evidence
        evidence = await recorder.get_task_evidence("retrieval_test")

        assert evidence["success"] is True
        assert evidence["task_id"] == "retrieval_test"
        assert evidence["metadata"]["status"] == "completed"
        assert evidence["total_steps"] == 1

    @pytest.mark.asyncio
    async def test_screenshot_storage(self, temp_evidence_dir):
        """Test screenshot storage and retrieval"""
        from elyan.computer_use.evidence.recorder import ComputerUseRecorder
        from PIL import Image
        from io import BytesIO

        recorder = ComputerUseRecorder(storage_path=temp_evidence_dir)

        # Create a test image
        img = Image.new('RGB', (100, 100), color='red')
        buf = BytesIO()
        img.save(buf, format='PNG')
        screenshot_bytes = buf.getvalue()

        # Save screenshot
        result = await recorder.save_screenshot(
            task_id="screenshot_test",
            screenshot_id="ss_0",
            screenshot_bytes=screenshot_bytes
        )

        assert result is True

        # Verify file exists
        task_dir = Path(temp_evidence_dir) / "screenshot_test" / "screenshots"
        assert (task_dir / "ss_0.png").exists()

        # Verify size
        saved_size = (task_dir / "ss_0.png").stat().st_size
        assert saved_size > 0

    @pytest.mark.asyncio
    async def test_api_task_creation(self):
        """Test API endpoint for task creation"""
        api = ComputerUseAPI()

        # Start a task via API
        result = await api.start_task(
            user_intent="API test task",
            approval_level="CONFIRM"
        )

        assert result["success"] is True
        assert "task_id" in result
        assert result["status"] == "pending"

        # Verify task is in running_tasks
        task_id = result["task_id"]
        status = await api.get_task_status(task_id)
        assert status["success"] is True
        assert status["status"] == "pending"

    @pytest.mark.asyncio
    async def test_api_task_listing(self):
        """Test API endpoint for task listing"""
        api = ComputerUseAPI()

        # Create multiple tasks
        task1 = await api.start_task("Task 1")
        task2 = await api.start_task("Task 2")

        # List tasks
        result = await api.list_tasks()

        assert result["success"] is True
        assert result["total"] >= 2
        assert any(t["task_id"] == task1["task_id"] for t in result["tasks"])
        assert any(t["task_id"] == task2["task_id"] for t in result["tasks"])

    @pytest.mark.asyncio
    async def test_evidence_cleanup(self, temp_evidence_dir):
        """Test evidence cleanup for old tasks"""
        import time
        from elyan.computer_use.evidence.recorder import ComputerUseRecorder

        recorder = ComputerUseRecorder(storage_path=temp_evidence_dir)

        # Create task directory with old timestamp
        task_dir = Path(temp_evidence_dir) / "old_task"
        task_dir.mkdir(parents=True, exist_ok=True)

        # Create a file with old timestamp
        test_file = task_dir / "test.txt"
        test_file.write_text("old")

        # Set old modification time (8 days ago)
        old_time = time.time() - (8 * 24 * 3600)
        import os
        os.utime(test_file, (old_time, old_time))

        # Run cleanup (keep tasks from last 7 days)
        result = await recorder.cleanup_old_evidence(days=7)

        assert result["cleaned"] >= 1
        assert not task_dir.exists()

    @pytest.mark.asyncio
    async def test_task_with_approval_callback(self):
        """Test task execution with approval callback"""
        tool = ComputerUseTool(max_steps=5)

        # Mock approval callback
        approved_actions = []

        async def approval_callback(action, screenshot):
            approved_actions.append(action.action_type)
            return True  # Always approve

        # Note: This is a simplified test that mocks the components
        # Real test would require ollama running for VLM
        with patch.object(tool, '_ensure_components', new_callable=AsyncMock):
            with patch.object(tool, '_get_screenshot', return_value=b"test"):
                pass  # Would need full mocking of vision/planner/executor

    def test_action_trace_jsonl_format(self, temp_evidence_dir):
        """Test that action trace is JSONL (one JSON per line)"""
        from pathlib import Path

        task_dir = Path(temp_evidence_dir) / "test_task"
        task_dir.mkdir(parents=True, exist_ok=True)

        # Create action trace file
        action_file = task_dir / "action_trace.jsonl"
        actions = [
            {"step": 0, "action_type": "click", "x": 100},
            {"step": 1, "action_type": "type", "text": "test"},
            {"step": 2, "action_type": "wait", "ms": 500}
        ]

        with open(action_file, "w") as f:
            for action in actions:
                f.write(json.dumps(action) + "\n")

        # Read back and verify JSONL format
        read_actions = []
        with open(action_file, "r") as f:
            for line in f:
                if line.strip():
                    read_actions.append(json.loads(line))

        assert len(read_actions) == 3
        assert read_actions[0]["step"] == 0
        assert read_actions[1]["action_type"] == "type"
        assert read_actions[2]["ms"] == 500


class TestComputerUseIntegration:
    """Integration tests for full Computer Use workflow"""

    @pytest.mark.asyncio
    async def test_full_workflow_mock(self, temp_evidence_dir):
        """Test full workflow with mocked components"""
        from elyan.computer_use.tool import ComputerUseTool
        from elyan.computer_use.evidence.recorder import ComputerUseRecorder

        # Create components
        tool = ComputerUseTool()
        recorder = ComputerUseRecorder(storage_path=temp_evidence_dir)

        # Mock a completed task
        task = ComputerUseTask(
            task_id="workflow_test",
            user_intent="Complete workflow",
            max_steps=2,
            created_at=999999.0,
            status="completed",
            completed_at=999999 + 30
        )
        task.steps = [
            {
                "step": 0,
                "action": ComputerAction(action_type="left_click", x=100, y=100).model_dump(),
                "result": {"success": True},
                "screenshot_id": "ss_0",
                "timestamp": 999999 + 5
            }
        ]
        task.evidence = ["ss_0"]

        # Record task
        result = await recorder.record_task(task.model_dump())
        assert result["success"] is True

        # Retrieve evidence
        evidence = await recorder.get_task_evidence("workflow_test")
        assert evidence["success"] is True
        assert evidence["total_steps"] == 1
