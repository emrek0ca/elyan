"""
Test Run Inspector API endpoints.
Tests: GET/POST run endpoints, run listing, run cancellation.
"""

import pytest
import asyncio
import json
from unittest.mock import patch, AsyncMock, MagicMock
from api.dashboard_api import DashboardAPIv1
from core.run_store import RunRecord


class TestRunInspectorAPI:
    """Test Run Inspector API endpoints."""

    @pytest.mark.asyncio
    async def test_get_run_success(self):
        """Test retrieving run details."""
        api = DashboardAPIv1()

        mock_record = RunRecord(
            run_id="run_123",
            session_id="sess_456",
            status="completed",
            intent="list files",
            steps=[{"type": "init"}],
            tool_calls=[{"tool": "ls", "status": "success"}]
        )

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.get_run = AsyncMock(return_value=mock_record)
            mock_store.return_value = mock_store_instance

            result = await api.get_run("run_123")
            assert result["success"] is True
            assert result["run"]["run_id"] == "run_123"
            assert result["run"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_run_not_found(self):
        """Test retrieving non-existent run."""
        api = DashboardAPIv1()

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.get_run = AsyncMock(return_value=None)
            mock_store.return_value = mock_store_instance

            result = await api.get_run("run_nonexistent")
            assert result["success"] is False
            assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_list_runs(self):
        """Test listing runs."""
        api = DashboardAPIv1()

        mock_records = [
            RunRecord(
                run_id=f"run_{i:03d}",
                session_id=f"sess_{i}",
                status="completed",
                intent=f"test {i}"
            )
            for i in range(3)
        ]

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.list_runs = AsyncMock(return_value=mock_records)
            mock_store.return_value = mock_store_instance

            result = await api.list_runs(limit=20, status=None)
            assert result["success"] is True
            assert result["count"] == 3
            assert len(result["runs"]) == 3

    @pytest.mark.asyncio
    async def test_list_runs_with_status_filter(self):
        """Test listing runs with status filter."""
        api = DashboardAPIv1()

        mock_records = [
            RunRecord(
                run_id="run_001",
                session_id="sess_001",
                status="completed",
                intent="test"
            ),
            RunRecord(
                run_id="run_002",
                session_id="sess_002",
                status="completed",
                intent="test"
            )
        ]

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.list_runs = AsyncMock(return_value=mock_records)
            mock_store.return_value = mock_store_instance

            result = await api.list_runs(limit=20, status="completed")
            assert result["success"] is True
            assert result["count"] == 2
            # Verify list_runs was called with correct filter
            mock_store_instance.list_runs.assert_called_once_with(20, "completed")

    @pytest.mark.asyncio
    async def test_cancel_run_success(self):
        """Test canceling a run."""
        api = DashboardAPIv1()

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.cancel_run = AsyncMock(return_value=True)
            mock_store.return_value = mock_store_instance

            result = await api.cancel_run("run_123")
            assert result["success"] is True
            assert "cancelled" in result["message"].lower()
            mock_store_instance.cancel_run.assert_called_once_with("run_123")

    @pytest.mark.asyncio
    async def test_cancel_run_not_found(self):
        """Test canceling non-existent run."""
        api = DashboardAPIv1()

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.cancel_run = AsyncMock(return_value=False)
            mock_store.return_value = mock_store_instance

            result = await api.cancel_run("run_nonexistent")
            assert result["success"] is False
            assert "not found" in result["error"].lower()


class TestMemoryTimelineAPI:
    """Test Memory Timeline API endpoint."""

    @pytest.mark.asyncio
    async def test_get_memory_timeline(self):
        """Test retrieving memory timeline."""
        api = DashboardAPIv1()

        mock_records = [
            RunRecord(
                run_id="run_001",
                session_id="sess_001",
                status="completed",
                intent="test"
            ),
            RunRecord(
                run_id="run_002",
                session_id="sess_002",
                status="completed",
                intent="test"
            )
        ]

        with patch("core.run_store.get_run_store") as mock_store:
            mock_store_instance = AsyncMock()
            mock_store_instance.list_runs = AsyncMock(return_value=mock_records)
            mock_store.return_value = mock_store_instance

            with patch("pathlib.Path") as mock_path:
                mock_memory_path = MagicMock()
                mock_memory_path.exists.return_value = False
                mock_path.return_value = mock_memory_path

                result = await api.get_memory_timeline(limit=20)
                assert result["success"] is True
                assert result["count"] >= 0
                assert isinstance(result["events"], list)
