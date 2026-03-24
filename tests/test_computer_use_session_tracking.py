"""Tests for Computer Use session tracking"""

import pytest
import asyncio
from core.session_manager import SessionManager


class TestComputerUseSessionTracking:
    """Test Computer Use task tracking in SessionManager"""

    @pytest.fixture
    def manager(self):
        """Create a session manager instance"""
        return SessionManager()

    @pytest.mark.asyncio
    async def test_start_computer_use_task(self, manager):
        """Test starting a Computer Use task"""
        session = await manager.create_session(user_id=1)

        ok = await manager.start_computer_use_task(
            session.session_id,
            "cu_001",
            "CONFIRM",
            "/tmp/evidence"
        )

        assert ok is True
        assert session.computer_use_active is True
        assert session.computer_use_task_id == "cu_001"
        assert session.computer_use_approval_level == "CONFIRM"

    @pytest.mark.asyncio
    async def test_update_computer_use_progress(self, manager):
        """Test updating Computer Use progress"""
        session = await manager.create_session(user_id=2)
        await manager.start_computer_use_task(session.session_id, "cu_002")

        ok = await manager.update_computer_use_progress(session.session_id, 10)

        assert ok is True
        assert session.computer_use_actions_executed == 10

    @pytest.mark.asyncio
    async def test_get_computer_use_status(self, manager):
        """Test retrieving Computer Use status"""
        session = await manager.create_session(user_id=3)
        await manager.start_computer_use_task(
            session.session_id,
            "cu_003",
            "SCREEN",
            "/tmp/evidence"
        )
        await manager.update_computer_use_progress(session.session_id, 5)

        status = manager.get_computer_use_status(session.session_id)

        assert status is not None
        assert status["task_id"] == "cu_003"
        assert status["active"] is True
        assert status["approval_level"] == "SCREEN"
        assert status["actions_executed"] == 5

    @pytest.mark.asyncio
    async def test_complete_computer_use_task(self, manager):
        """Test completing a Computer Use task"""
        session = await manager.create_session(user_id=4)
        await manager.start_computer_use_task(session.session_id, "cu_004")

        ok = await manager.complete_computer_use_task(session.session_id)

        assert ok is True
        assert session.computer_use_active is False
        assert session.computer_use_task_id is None

    @pytest.mark.asyncio
    async def test_get_status_after_completion(self, manager):
        """Test that status returns None after completion"""
        session = await manager.create_session(user_id=5)
        await manager.start_computer_use_task(session.session_id, "cu_005")
        await manager.complete_computer_use_task(session.session_id)

        status = manager.get_computer_use_status(session.session_id)

        assert status is None

    @pytest.mark.asyncio
    async def test_approval_level_persistence(self, manager):
        """Test that approval level is properly persisted"""
        session = await manager.create_session(user_id=6)

        for level in ["AUTO", "CONFIRM", "SCREEN", "TWO_FA"]:
            await manager.start_computer_use_task(
                session.session_id,
                f"cu_{level}",
                level
            )
            status = manager.get_computer_use_status(session.session_id)
            assert status["approval_level"] == level
            await manager.complete_computer_use_task(session.session_id)

    @pytest.mark.asyncio
    async def test_nonexistent_session(self, manager):
        """Test error handling for non-existent session"""
        ok = await manager.start_computer_use_task("fake_session", "cu_task")
        assert ok is False

    @pytest.mark.asyncio
    async def test_duration_calculation(self, manager):
        """Test that duration is calculated correctly"""
        import time
        session = await manager.create_session(user_id=7)
        await manager.start_computer_use_task(session.session_id, "cu_007")

        time.sleep(0.1)  # Wait 100ms

        status = manager.get_computer_use_status(session.session_id)
        assert status["duration_seconds"] >= 0.1
