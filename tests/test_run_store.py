"""
Test Run Store - persistent run record storage.
Tests: record, retrieve, list, cancel, cleanup.
"""

import pytest
import asyncio
import json
import tempfile
import os
import time
from pathlib import Path
from core.run_store import RunStore, RunRecord


class TestRunRecord:
    """Test RunRecord dataclass."""

    def test_run_record_creation(self):
        """Test creating a RunRecord."""
        record = RunRecord(
            run_id="run_123",
            session_id="sess_456",
            status="completed",
            intent="list files",
            steps=[{"type": "init", "description": "Setup"}],
            tool_calls=[{"tool": "list_files", "status": "success"}]
        )
        assert record.run_id == "run_123"
        assert record.status == "completed"
        assert len(record.steps) == 1
        assert len(record.tool_calls) == 1

    def test_run_record_to_dict(self):
        """Test RunRecord serialization."""
        record = RunRecord(
            run_id="run_124",
            session_id="sess_457",
            status="pending",
            intent="execute script"
        )
        data = record.to_dict()
        assert data["run_id"] == "run_124"
        assert data["intent"] == "execute script"
        assert "started_at" in data
        assert data["completed_at"] is None

    def test_run_record_duration(self):
        """Test duration calculation."""
        import time
        record = RunRecord(
            run_id="run_125",
            session_id="sess_458",
            status="completed",
            intent="test"
        )
        record.completed_at = record.started_at + 10.5
        duration = record.duration_seconds()
        assert duration == 10.5


class TestRunStore:
    """Test RunStore functionality."""

    @pytest.fixture
    def temp_store(self):
        """Create temporary run store."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield RunStore(store_path=tmpdir)

    @pytest.mark.asyncio
    async def test_record_run(self, temp_store):
        """Test recording a run."""
        record = RunRecord(
            run_id="run_001",
            session_id="sess_001",
            status="completed",
            intent="list files"
        )
        await temp_store.record_run(record)

        # Check file was created
        file_path = Path(temp_store.store_path) / "run_001.json"
        assert file_path.exists()

        # Check content
        with open(file_path, "r") as f:
            data = json.load(f)
        assert data["run_id"] == "run_001"
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_run(self, temp_store):
        """Test retrieving a run by ID."""
        record = RunRecord(
            run_id="run_002",
            session_id="sess_002",
            status="completed",
            intent="test"
        )
        await temp_store.record_run(record)
        retrieved = await temp_store.get_run("run_002")

        assert retrieved is not None
        assert retrieved.run_id == "run_002"
        assert retrieved.intent == "test"

    @pytest.mark.asyncio
    async def test_get_nonexistent_run(self, temp_store):
        """Test retrieving non-existent run returns None."""
        retrieved = await temp_store.get_run("run_nonexistent")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_runs(self, temp_store):
        """Test listing runs."""
        # Create multiple runs
        for i in range(5):
            record = RunRecord(
                run_id=f"run_{i:03d}",
                session_id=f"sess_{i}",
                status="completed",
                intent=f"test {i}"
            )
            await temp_store.record_run(record)
            await asyncio.sleep(0.01)  # Small delay for file timestamps

        runs = await temp_store.list_runs(limit=3)
        assert len(runs) <= 3
        assert all(isinstance(r, RunRecord) for r in runs)

    @pytest.mark.asyncio
    async def test_list_runs_with_status_filter(self, temp_store):
        """Test listing runs filtered by status."""
        # Create runs with different statuses
        statuses = ["completed", "completed", "error", "pending"]
        for i, status in enumerate(statuses):
            record = RunRecord(
                run_id=f"run_{status}_{i}",
                session_id="sess_test",
                status=status,
                intent="test"
            )
            await temp_store.record_run(record)

        completed_runs = await temp_store.list_runs(limit=10, status="completed")
        assert all(r.status == "completed" for r in completed_runs)
        assert len(completed_runs) == 2

    @pytest.mark.asyncio
    async def test_cancel_run(self, temp_store):
        """Test canceling a run."""
        record = RunRecord(
            run_id="run_cancel",
            session_id="sess_cancel",
            status="pending",
            intent="test"
        )
        await temp_store.record_run(record)

        # Cancel the run
        success = await temp_store.cancel_run("run_cancel")
        assert success is True

        # Verify status changed
        retrieved = await temp_store.get_run("run_cancel")
        assert retrieved.status == "cancelled"
        assert retrieved.completed_at is not None

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_run(self, temp_store):
        """Test canceling non-existent run fails gracefully."""
        success = await temp_store.cancel_run("run_nonexistent")
        assert success is False

    @pytest.mark.asyncio
    async def test_cleanup_old_runs(self, temp_store):
        """Test cleaning up old runs."""
        import time

        # Create old run with old file timestamp
        old_record = RunRecord(
            run_id="run_old",
            session_id="sess_old",
            status="completed",
            intent="test",
            started_at=time.time() - (10 * 86400)  # 10 days old
        )
        await temp_store.record_run(old_record)

        # Create new run
        new_record = RunRecord(
            run_id="run_new",
            session_id="sess_new",
            status="completed",
            intent="test"
        )
        await temp_store.record_run(new_record)

        # Manually set old file's mtime
        old_file = Path(temp_store.store_path) / "run_old.json"
        if old_file.exists():
            old_mtime = time.time() - (10 * 86400)
            os.utime(old_file, (old_mtime, old_mtime))

        # Cleanup runs older than 7 days
        deleted = await temp_store.cleanup_old_runs(days=7)
        assert deleted >= 1

        # Old run should be gone
        old = await temp_store.get_run("run_old")
        assert old is None

        # New run should still exist
        new = await temp_store.get_run("run_new")
        assert new is not None
