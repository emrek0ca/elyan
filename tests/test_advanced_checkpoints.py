"""
Tests for Advanced Checkpoint & Recovery System
================================================
"""

import pytest
import tempfile
import time
import json
from pathlib import Path

from core.advanced_checkpoints import (
    CheckpointStore,
    CheckpointMetadata,
    ExecutionRecovery,
    CheckpointManager,
    CheckpointType
)


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test_checkpoints.db")
        yield db_path


class TestCheckpointMetadata:
    """Tests for CheckpointMetadata."""

    def test_metadata_creation(self):
        """Test creating checkpoint metadata."""
        metadata = CheckpointMetadata(
            checkpoint_id="cp1",
            execution_id="exec1",
            timestamp=time.time(),
            checkpoint_type="task_complete",
            step_number=1,
            task_id="task1",
            group_id="group1",
            progress_percentage=50.0,
            estimated_time_remaining=30.0
        )

        assert metadata.checkpoint_id == "cp1"
        assert metadata.task_id == "task1"
        assert metadata.progress_percentage == 50.0

    def test_metadata_to_dict(self):
        """Test converting metadata to dict."""
        metadata = CheckpointMetadata(
            checkpoint_id="cp1",
            execution_id="exec1",
            timestamp=time.time(),
            checkpoint_type="task_complete",
            step_number=1,
            task_id="task1",
            group_id="group1",
            progress_percentage=50.0,
            estimated_time_remaining=30.0
        )

        data = metadata.to_dict()
        assert isinstance(data, dict)
        assert data["checkpoint_id"] == "cp1"
        assert data["progress_percentage"] == 50.0


class TestCheckpointStore:
    """Tests for CheckpointStore."""

    def test_store_initialization(self, temp_db):
        """Test store initialization."""
        store = CheckpointStore(temp_db)
        assert Path(temp_db).exists()

    def test_create_execution(self, temp_db):
        """Test creating execution record."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 10)

        stats = store.get_execution_stats("exec1")
        assert stats["total_steps"] == 10
        assert stats["status"] == "active"

    def test_save_and_load_checkpoint(self, temp_db):
        """Test saving and loading checkpoint."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 5)

        metadata = CheckpointMetadata(
            checkpoint_id="cp1",
            execution_id="exec1",
            timestamp=time.time(),
            checkpoint_type="task_complete",
            step_number=1,
            task_id="task1",
            group_id=None,
            progress_percentage=20.0,
            estimated_time_remaining=40.0
        )

        state = {"data": "test_data", "values": [1, 2, 3]}

        checkpoint_id = store.save_checkpoint(metadata, state, compress=True)
        assert checkpoint_id == "cp1"

        # Load it back
        loaded_metadata, loaded_state = store.load_checkpoint("cp1")

        assert loaded_metadata.checkpoint_id == "cp1"
        assert loaded_state["data"] == "test_data"
        assert loaded_state["values"] == [1, 2, 3]

    def test_checkpoint_compression(self, temp_db):
        """Test checkpoint compression."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 5)

        metadata = CheckpointMetadata(
            checkpoint_id="cp_compressed",
            execution_id="exec1",
            timestamp=time.time(),
            checkpoint_type="task_complete",
            step_number=1,
            task_id="task1",
            group_id=None,
            progress_percentage=20.0,
            estimated_time_remaining=40.0
        )

        # Large state
        state = {f"key_{i}": f"value_{i}" * 100 for i in range(100)}

        checkpoint_id = store.save_checkpoint(metadata, state, compress=True)

        loaded_metadata, loaded_state = store.load_checkpoint(checkpoint_id)
        assert len(loaded_state) == 100
        assert loaded_state["key_0"].startswith("value_0")

    def test_get_latest_checkpoint(self, temp_db):
        """Test getting latest checkpoint."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 5)

        # Save multiple checkpoints
        for i in range(3):
            metadata = CheckpointMetadata(
                checkpoint_id=f"cp{i}",
                execution_id="exec1",
                timestamp=time.time() + i,
                checkpoint_type="task_complete",
                step_number=i,
                task_id=f"task{i}",
                group_id=None,
                progress_percentage=float(i * 20),
                estimated_time_remaining=0.0
            )
            store.save_checkpoint(metadata, {"step": i}, compress=True)

        latest = store.get_latest_checkpoint("exec1")
        assert latest == "cp2"

    def test_get_latest_checkpoint_by_type(self, temp_db):
        """Test getting latest checkpoint by type."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 5)

        # Save different checkpoint types
        for ctype, i in [("task_complete", 0), ("group_complete", 1), ("task_complete", 2)]:
            metadata = CheckpointMetadata(
                checkpoint_id=f"cp{i}",
                execution_id="exec1",
                timestamp=time.time() + i,
                checkpoint_type=ctype,
                step_number=i,
                task_id=f"task{i}",
                group_id=None,
                progress_percentage=0.0,
                estimated_time_remaining=0.0
            )
            store.save_checkpoint(metadata, {"step": i}, compress=True)

        latest_task = store.get_latest_checkpoint("exec1", "task_complete")
        assert latest_task == "cp2"

    def test_list_checkpoints(self, temp_db):
        """Test listing checkpoints."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 5)

        # Save multiple checkpoints
        for i in range(5):
            metadata = CheckpointMetadata(
                checkpoint_id=f"cp{i}",
                execution_id="exec1",
                timestamp=time.time() + i,
                checkpoint_type="task_complete",
                step_number=i,
                task_id=f"task{i}",
                group_id=None,
                progress_percentage=float(i * 20),
                estimated_time_remaining=0.0
            )
            store.save_checkpoint(metadata, {"step": i}, compress=True)

        checkpoints = store.list_checkpoints("exec1", limit=3)
        assert len(checkpoints) == 3
        assert checkpoints[0]["checkpoint_id"] == "cp4"  # Latest first

    def test_delete_old_checkpoints(self, temp_db):
        """Test deleting old checkpoints."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 10)

        # Save 10 checkpoints
        for i in range(10):
            metadata = CheckpointMetadata(
                checkpoint_id=f"cp{i}",
                execution_id="exec1",
                timestamp=time.time() + i,
                checkpoint_type="task_complete",
                step_number=i,
                task_id=f"task{i}",
                group_id=None,
                progress_percentage=float(i * 10),
                estimated_time_remaining=0.0
            )
            store.save_checkpoint(metadata, {"step": i}, compress=True)

        # Keep only latest 3
        deleted = store.delete_old_checkpoints("exec1", keep_latest=3)
        assert deleted == 7

        remaining = store.list_checkpoints("exec1", limit=100)
        assert len(remaining) == 3

    def test_cleanup_execution(self, temp_db):
        """Test cleaning up execution."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 5)

        for i in range(3):
            metadata = CheckpointMetadata(
                checkpoint_id=f"cp{i}",
                execution_id="exec1",
                timestamp=time.time() + i,
                checkpoint_type="task_complete",
                step_number=i,
                task_id=f"task{i}",
                group_id=None,
                progress_percentage=0.0,
                estimated_time_remaining=0.0
            )
            store.save_checkpoint(metadata, {"step": i}, compress=True)

        store.cleanup_execution("exec1")

        # Should have no checkpoints
        latest = store.get_latest_checkpoint("exec1")
        assert latest is None

    def test_get_execution_stats(self, temp_db):
        """Test getting execution stats."""
        store = CheckpointStore(temp_db)
        store.create_execution("exec1", 10)

        stats = store.get_execution_stats("exec1")
        assert stats["total_steps"] == 10
        assert stats["execution_id"] == "exec1"


class TestExecutionRecovery:
    """Tests for ExecutionRecovery."""

    def test_get_recovery_point(self, temp_db):
        """Test getting recovery point."""
        store = CheckpointStore(temp_db)
        recovery = ExecutionRecovery(store)

        store.create_execution("exec1", 5)

        metadata = CheckpointMetadata(
            checkpoint_id="cp1",
            execution_id="exec1",
            timestamp=time.time(),
            checkpoint_type="task_complete",
            step_number=1,
            task_id="task1",
            group_id=None,
            progress_percentage=20.0,
            estimated_time_remaining=40.0
        )

        state = {"data": "test"}
        store.save_checkpoint(metadata, state, compress=True)

        recovery_point = recovery.get_recovery_point("exec1")
        assert recovery_point is not None
        assert recovery_point[1]["data"] == "test"

    def test_rollback_to_checkpoint(self, temp_db):
        """Test rollback to checkpoint."""
        store = CheckpointStore(temp_db)
        recovery = ExecutionRecovery(store)

        store.create_execution("exec1", 10)

        # Save multiple checkpoints
        for i in range(5):
            metadata = CheckpointMetadata(
                checkpoint_id=f"cp{i}",
                execution_id="exec1",
                timestamp=time.time() + i * 0.1,
                checkpoint_type="task_complete",
                step_number=i,
                task_id=f"task{i}",
                group_id=None,
                progress_percentage=float(i * 20),
                estimated_time_remaining=0.0
            )
            store.save_checkpoint(metadata, {"step": i}, compress=True)

        # Rollback to checkpoint 2
        recovery.rollback_to_checkpoint("exec1", "cp2")

        # Check that only checkpoints 0-2 remain
        checkpoints = store.list_checkpoints("exec1", limit=100)
        assert len(checkpoints) == 3
        assert all(cp["checkpoint_id"] in ["cp0", "cp1", "cp2"] for cp in checkpoints)

    def test_validate_recovery(self, temp_db):
        """Test recovery validation."""
        store = CheckpointStore(temp_db)
        recovery = ExecutionRecovery(store)

        store.create_execution("exec1", 5)

        metadata = CheckpointMetadata(
            checkpoint_id="cp1",
            execution_id="exec1",
            timestamp=time.time(),
            checkpoint_type="task_complete",
            step_number=1,
            task_id="task1",
            group_id=None,
            progress_percentage=20.0,
            estimated_time_remaining=40.0
        )

        state = {"data": "test", "values": [1, 2, 3]}
        store.save_checkpoint(metadata, state, compress=True)

        # Validate valid recovery
        valid, message = recovery.validate_recovery("cp1", state)
        assert valid

        # Validate with different data
        bad_state = {"data": "different"}
        valid, message = recovery.validate_recovery("cp1", bad_state)
        assert not valid


class TestCheckpointManager:
    """Tests for CheckpointManager."""

    def test_manager_initialization(self, temp_db):
        """Test manager initialization."""
        manager = CheckpointManager(temp_db)
        assert manager.store is not None
        assert manager.recovery is not None

    def test_should_checkpoint(self, temp_db):
        """Test checkpoint timing."""
        manager = CheckpointManager(temp_db)
        manager.auto_checkpoint_interval = 0.1

        assert manager.should_checkpoint()

        manager.last_checkpoint_time = time.time()
        assert not manager.should_checkpoint()

        time.sleep(0.15)
        assert manager.should_checkpoint()

    def test_create_checkpoint(self, temp_db):
        """Test creating checkpoint."""
        manager = CheckpointManager(temp_db)

        checkpoint_id = manager.create_checkpoint(
            execution_id="exec1",
            state={"data": "test"},
            step_number=1,
            checkpoint_type="task_complete",
            task_id="task1",
            progress_percentage=50.0,
            estimated_time_remaining=30.0
        )

        assert checkpoint_id is not None
        assert "exec1" in checkpoint_id

    def test_get_recovery_state(self, temp_db):
        """Test getting recovery state."""
        manager = CheckpointManager(temp_db)

        state = {"data": "test", "value": 42}
        manager.create_checkpoint(
            execution_id="exec1",
            state=state,
            step_number=1,
            task_id="task1"
        )

        recovered_state = manager.get_recovery_state("exec1")
        assert recovered_state is not None
        assert recovered_state["data"] == "test"
        assert recovered_state["value"] == 42

    def test_list_checkpoints_for_execution(self, temp_db):
        """Test listing checkpoints."""
        manager = CheckpointManager(temp_db)

        for i in range(3):
            manager.create_checkpoint(
                execution_id="exec1",
                state={"step": i},
                step_number=i,
                task_id=f"task{i}"
            )

        checkpoints = manager.list_checkpoints_for_execution("exec1")
        assert len(checkpoints) == 3

    def test_cleanup(self, temp_db):
        """Test cleanup."""
        manager = CheckpointManager(temp_db)

        for i in range(3):
            manager.create_checkpoint(
                execution_id="exec1",
                state={"step": i},
                step_number=i,
                task_id=f"task{i}"
            )

        manager.cleanup("exec1")

        recovered = manager.get_recovery_state("exec1")
        assert recovered is None


class TestCheckpointIntegration:
    """Integration tests for checkpoint system."""

    def test_long_running_task_recovery(self, temp_db):
        """Test recovery of long-running task execution."""
        manager = CheckpointManager(temp_db)

        # Simulate task execution with checkpoints
        execution_id = "long_exec_1"
        total_steps = 10

        for step in range(5):  # First 5 steps complete
            state = {
                "step": step,
                "data": f"step_{step}_data",
                "results": list(range(step + 1))
            }
            manager.create_checkpoint(
                execution_id=execution_id,
                state=state,
                step_number=step,
                checkpoint_type="task_complete",
                task_id=f"task_{step}",
                progress_percentage=float((step + 1) * 100 / total_steps),
                estimated_time_remaining=float((total_steps - step - 1) * 2)
            )

        # Get recovery point
        recovered_state = manager.get_recovery_state(execution_id)
        assert recovered_state is not None
        assert recovered_state["step"] == 4
        assert len(recovered_state["results"]) == 5

    def test_parallel_execution_with_checkpoints(self, temp_db):
        """Test checkpointing during parallel task groups."""
        manager = CheckpointManager(temp_db)

        execution_id = "parallel_exec_1"

        # Group 1: Independent tasks
        for i in range(3):
            state = {"group": 1, "task": i, "results": [i] * (i + 1)}
            manager.create_checkpoint(
                execution_id=execution_id,
                state=state,
                step_number=i,
                checkpoint_type="group_complete",
                group_id="group_1",
                progress_percentage=25.0
            )

        # Group 2: Dependent on Group 1
        state = {"group": 2, "aggregated": "results"}
        checkpoint_id = manager.create_checkpoint(
            execution_id=execution_id,
            state=state,
            step_number=3,
            checkpoint_type="group_complete",
            group_id="group_2",
            progress_percentage=75.0
        )

        # Verify recovery
        recovered = manager.get_recovery_state(execution_id)
        assert recovered["group"] == 2
        assert recovered["aggregated"] == "results"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
