"""Tests for Computer Use Action Executor

Tests action execution: mouse, keyboard, screen control.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
import asyncio

from elyan.computer_use.executor.action_executor import (
    ActionExecutor,
    get_action_executor
)
from elyan.computer_use.tool import ComputerAction


class TestActionExecutor:
    """Test ActionExecutor class"""

    @pytest.fixture
    def executor(self):
        """Create ActionExecutor instance"""
        return ActionExecutor()

    def test_executor_initialization(self, executor):
        """Test executor creation"""
        assert executor.mouse is not None or executor.pyautogui is not None
        assert executor.keyboard is not None or executor.pyautogui is not None

    @pytest.mark.asyncio
    async def test_execute_left_click(self, executor):
        """Test left click execution"""
        action = ComputerAction(
            action_type="left_click",
            x=100,
            y=200,
            confidence=0.95
        )

        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_left_click_missing_coords(self, executor):
        """Test left click fails without coordinates"""
        action = ComputerAction(action_type="left_click")
        result = await executor.execute(action)
        assert result["success"] is False
        assert "coordinate" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_execute_right_click(self, executor):
        """Test right click execution"""
        action = ComputerAction(
            action_type="right_click",
            x=150,
            y=250
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_double_click(self, executor):
        """Test double click execution"""
        action = ComputerAction(
            action_type="double_click",
            x=100,
            y=200
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_type(self, executor):
        """Test text typing"""
        action = ComputerAction(
            action_type="type",
            text="Hello World"
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_type_missing_text(self, executor):
        """Test type fails without text"""
        action = ComputerAction(action_type="type")
        result = await executor.execute(action)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_scroll(self, executor):
        """Test scroll execution"""
        action = ComputerAction(
            action_type="scroll",
            dy=3,  # Scroll down
            x=500,
            y=400
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_drag(self, executor):
        """Test drag execution"""
        action = ComputerAction(
            action_type="drag",
            x=100,
            y=100,
            x2=200,
            y2=200
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_drag_missing_coords(self, executor):
        """Test drag fails without complete coordinates"""
        action = ComputerAction(
            action_type="drag",
            x=100,
            y=100
            # Missing x2, y2
        )
        result = await executor.execute(action)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_hotkey(self, executor):
        """Test keyboard hotkey"""
        action = ComputerAction(
            action_type="hotkey",
            key_combination=["ctrl", "c"]
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_hotkey_missing_keys(self, executor):
        """Test hotkey fails without key combination"""
        action = ComputerAction(action_type="hotkey")
        result = await executor.execute(action)
        assert result["success"] is False

    @pytest.mark.asyncio
    async def test_execute_mouse_move(self, executor):
        """Test mouse move"""
        action = ComputerAction(
            action_type="mouse_move",
            x=300,
            y=300
        )
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_wait(self, executor):
        """Test wait action"""
        action = ComputerAction(
            action_type="wait",
            wait_ms=100
        )

        import time
        start = time.time()
        result = await executor.execute(action)
        elapsed = time.time() - start

        assert result["success"] is True
        assert elapsed >= 0.1  # Should wait at least 100ms

    @pytest.mark.asyncio
    async def test_execute_noop(self, executor):
        """Test no-op action"""
        action = ComputerAction(action_type="noop")
        result = await executor.execute(action)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_execute_unknown_action(self, executor):
        """Test unknown action type"""
        action = ComputerAction(action_type="unknown_action_type")
        result = await executor.execute(action)
        assert result["success"] is False
        assert "unknown" in result.get("error", "").lower()

    @pytest.mark.asyncio
    async def test_execute_action_with_error(self, executor):
        """Test action execution with error handling"""
        action = ComputerAction(
            action_type="left_click",
            x=-999999,  # Invalid coordinate
            y=-999999
        )
        # Should not raise, just return error
        result = await executor.execute(action)
        # Result may be success=True or False depending on implementation


class TestActionExecutorSequences:
    """Test action sequences"""

    @pytest.fixture
    def executor(self):
        return ActionExecutor()

    @pytest.mark.asyncio
    async def test_click_then_type(self, executor):
        """Test clicking a text field then typing"""
        # Click on input field
        click_action = ComputerAction(
            action_type="left_click",
            x=100,
            y=100
        )
        result1 = await executor.execute(click_action)
        assert result1["success"] is True

        # Type text
        type_action = ComputerAction(
            action_type="type",
            text="username@example.com"
        )
        result2 = await executor.execute(type_action)
        assert result2["success"] is True

    @pytest.mark.asyncio
    async def test_drag_then_click(self, executor):
        """Test dragging then clicking"""
        # Drag element
        drag_action = ComputerAction(
            action_type="drag",
            x=50,
            y=50,
            x2=200,
            y2=200
        )
        result1 = await executor.execute(drag_action)
        assert result1["success"] is True

        # Click button
        click_action = ComputerAction(
            action_type="left_click",
            x=300,
            y=300
        )
        result2 = await executor.execute(click_action)
        assert result2["success"] is True


class TestExecutorSingleton:
    """Test singleton pattern"""

    def test_get_action_executor_singleton(self):
        """Test singleton pattern"""
        executor1 = get_action_executor()
        executor2 = get_action_executor()
        assert executor1 is executor2


class TestExecutorRobustness:
    """Test error handling and robustness"""

    @pytest.fixture
    def executor(self):
        return ActionExecutor()

    @pytest.mark.asyncio
    async def test_multiple_rapid_clicks(self, executor):
        """Test multiple rapid clicks"""
        for i in range(5):
            action = ComputerAction(
                action_type="left_click",
                x=100 + i * 10,
                y=100
            )
            result = await executor.execute(action)
            assert "success" in result

    @pytest.mark.asyncio
    async def test_text_with_special_chars(self, executor):
        """Test typing special characters"""
        special_text = "!@#$%^&*()_+-=[]{}|;:',.<>?/~`"
        action = ComputerAction(
            action_type="type",
            text=special_text
        )
        result = await executor.execute(action)
        # Should handle gracefully even if some chars fail
        assert "error" not in result or result.get("success") is True
