"""Tests for Computer Use Integration with ControlPlane"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from core.computer_use_integration import (
    ComputerUseIntegration,
    ComputerUseRequest,
    ComputerUseResult,
    get_computer_use_integration
)


class TestComputerUseIntegration:
    """Tests for ComputerUseIntegration class"""

    @pytest.fixture
    def integration(self):
        """Create integration instance"""
        return ComputerUseIntegration()

    def test_init(self, integration):
        """Test integration initializes correctly"""
        assert integration.tool is not None
        assert integration._active_tasks == {}

    def test_should_route_to_computer_use(self, integration):
        """Test action routing detection"""
        assert integration.should_route_to_computer_use("computer_use")
        assert integration.should_route_to_computer_use("screen_control")
        assert integration.should_route_to_computer_use("ui_automation")
        assert not integration.should_route_to_computer_use("web_search")
        assert not integration.should_route_to_computer_use("file_operation")

    def test_should_route_case_insensitive(self, integration):
        """Test routing is case-insensitive"""
        assert integration.should_route_to_computer_use("COMPUTER_USE")
        assert integration.should_route_to_computer_use("Computer_Use")

    @pytest.mark.asyncio
    async def test_execute_task_success(self, integration):
        """Test successful task execution"""
        request = ComputerUseRequest(
            user_intent="Click button",
            approval_level="CONFIRM",
            session_id="test_session"
        )

        # Mock tool execution
        with patch.object(integration.tool, 'execute_task', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {
                "status": "completed",
                "steps": [{"action": "left_click"}],
                "result": "Button clicked"
            }

            result = await integration.execute_task(request)

            assert result.success is True
            assert result.status == "completed"
            assert result.steps_executed == 1
            assert "Button clicked" in str(result.result)

    @pytest.mark.asyncio
    async def test_execute_task_with_screenshot(self, integration):
        """Test task execution with initial screenshot"""
        request = ComputerUseRequest(
            user_intent="Type text",
            approval_level="SCREEN"
        )

        with patch.object(integration.tool, 'execute_task', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {
                "status": "completed",
                "steps": []
            }

            screenshot = b"fake_screenshot_data"
            result = await integration.execute_task(request, initial_screenshot=screenshot)

            # Verify tool was called with screenshot
            mock_execute.assert_called_once()
            call_kwargs = mock_execute.call_args[1]
            assert call_kwargs.get("initial_screenshot") == screenshot

    @pytest.mark.asyncio
    async def test_execute_task_cancelled(self, integration):
        """Test cancelled task"""
        request = ComputerUseRequest(user_intent="Task")

        with patch.object(integration.tool, 'execute_task', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {
                "status": "cancelled",
                "error": "User denied action"
            }

            result = await integration.execute_task(request)

            assert result.success is False
            assert result.status == "cancelled"

    @pytest.mark.asyncio
    async def test_execute_task_error(self, integration):
        """Test error handling"""
        request = ComputerUseRequest(user_intent="Task")

        with patch.object(integration.tool, 'execute_task', new_callable=AsyncMock) as mock_execute:
            mock_execute.side_effect = Exception("Tool error")

            result = await integration.execute_task(request)

            assert result.success is False
            assert result.status == "failed"
            assert "Tool error" in result.error

    @pytest.mark.asyncio
    async def test_get_task_status(self, integration):
        """Test getting task status"""
        # Create a task
        request = ComputerUseRequest(
            user_intent="Test task",
            approval_level="AUTO",
            session_id="session_123"
        )

        with patch.object(integration.tool, 'execute_task', new_callable=AsyncMock) as mock_execute:
            mock_execute.return_value = {
                "status": "completed",
                "steps": []
            }

            result = await integration.execute_task(request)
            task_id = result.task_id

            # Get status
            status = await integration.get_task_status(task_id)

            assert status["task_id"] == task_id
            assert status["status"] == "completed"
            assert status["intent"] == "Test task"
            assert status["session_id"] == "session_123"

    @pytest.mark.asyncio
    async def test_get_task_status_not_found(self, integration):
        """Test getting status of non-existent task"""
        status = await integration.get_task_status("nonexistent_task")

        assert "error" in status
        assert "not found" in status["error"].lower()

    @pytest.mark.asyncio
    async def test_list_active_tasks(self, integration):
        """Test listing active tasks"""
        # Create multiple tasks
        for i in range(3):
            integration._active_tasks[f"task_{i}"] = {
                "status": "pending",
                "intent": f"Task {i}",
                "created_at": __import__('time').time()
            }

        result = await integration.list_active_tasks()

        assert result["total"] == 3
        assert len(result["tasks"]) == 3

    @pytest.mark.asyncio
    async def test_list_active_tasks_with_limit(self, integration):
        """Test list with limit"""
        for i in range(5):
            integration._active_tasks[f"task_{i}"] = {
                "status": "pending",
                "intent": f"Task {i}",
                "created_at": __import__('time').time()
            }

        result = await integration.list_active_tasks(limit=2)

        assert result["total"] == 5
        assert len(result["tasks"]) == 2

    @pytest.mark.asyncio
    async def test_cancel_task(self, integration):
        """Test cancelling a task"""
        task_id = "task_to_cancel"
        integration._active_tasks[task_id] = {
            "status": "running",
            "intent": "Test"
        }

        success = await integration.cancel_task(task_id)

        assert success is True
        assert integration._active_tasks[task_id]["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_cancel_nonexistent_task(self, integration):
        """Test cancelling non-existent task"""
        success = await integration.cancel_task("nonexistent")

        assert success is False

    def test_singleton_pattern(self):
        """Test get_computer_use_integration returns singleton"""
        int1 = get_computer_use_integration()
        int2 = get_computer_use_integration()

        assert int1 is int2


class TestComputerUseRequest:
    """Tests for ComputerUseRequest"""

    def test_request_defaults(self):
        """Test request default values"""
        request = ComputerUseRequest(user_intent="Test")

        assert request.user_intent == "Test"
        assert request.approval_level == "CONFIRM"
        assert request.session_id is None
        assert request.timeout_seconds == 300

    def test_request_custom_values(self):
        """Test request with custom values"""
        request = ComputerUseRequest(
            user_intent="Test",
            approval_level="TWO_FA",
            session_id="sess_123",
            task_id="task_456",
            timeout_seconds=600
        )

        assert request.approval_level == "TWO_FA"
        assert request.session_id == "sess_123"
        assert request.task_id == "task_456"
        assert request.timeout_seconds == 600


class TestComputerUseResult:
    """Tests for ComputerUseResult"""

    def test_successful_result(self):
        """Test successful result"""
        result = ComputerUseResult(
            success=True,
            task_id="task_1",
            status="completed",
            steps_executed=5,
            evidence_dir="/path/to/evidence",
            result="Task completed"
        )

        assert result.success is True
        assert result.status == "completed"
        assert result.steps_executed == 5

    def test_failed_result(self):
        """Test failed result"""
        result = ComputerUseResult(
            success=False,
            task_id="task_2",
            status="failed",
            steps_executed=2,
            error="Something went wrong"
        )

        assert result.success is False
        assert result.status == "failed"
        assert result.error == "Something went wrong"
