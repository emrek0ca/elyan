"""Tests for Computer Use ControlPlane API"""

import pytest
from unittest.mock import AsyncMock, patch

from api.computer_use_controlplane import (
    ComputerUseControlPlaneAPI,
    get_computer_use_controlplane_api
)


class TestComputerUseControlPlaneAPI:
    """Tests for ComputerUseControlPlaneAPI"""

    @pytest.fixture
    def api(self):
        """Create API instance"""
        return ComputerUseControlPlaneAPI()

    def test_init(self, api):
        """Test API initializes correctly"""
        assert api.integration is not None

    @pytest.mark.asyncio
    async def test_start_task(self, api):
        """Test starting a task"""
        result = await api.start_task(
            user_intent="Open Chrome",
            approval_level="CONFIRM",
            session_id="sess_123"
        )

        assert result["status"] == "pending"
        assert result["user_intent"] == "Open Chrome"
        assert result["approval_level"] == "CONFIRM"
        assert "task_id" in result
        assert "created_at" in result

    @pytest.mark.asyncio
    async def test_start_task_defaults(self, api):
        """Test starting task with defaults"""
        result = await api.start_task(user_intent="Task")

        assert result["approval_level"] == "CONFIRM"
        assert "session_id" in result
        assert result["session_id"] == "unknown"

    @pytest.mark.asyncio
    async def test_get_task_status(self, api):
        """Test getting task status"""
        task_id = "test_task_1"

        # Mock integration
        with patch.object(api.integration, 'get_task_status', new_callable=AsyncMock) as mock_status:
            mock_status.return_value = {
                "task_id": task_id,
                "status": "completed",
                "session_id": "sess_123"
            }

            result = await api.get_task_status(task_id)

            assert result["task_id"] == task_id
            assert result["status"] == "completed"
            mock_status.assert_called_once_with(task_id)

    @pytest.mark.asyncio
    async def test_list_tasks(self, api):
        """Test listing tasks"""
        with patch.object(api.integration, 'list_active_tasks', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {
                "tasks": [
                    {"task_id": "task_1", "status": "completed"},
                    {"task_id": "task_2", "status": "running"}
                ],
                "total": 2
            }

            result = await api.list_tasks(limit=20)

            assert result["success"] is True
            assert result["total"] == 2
            assert len(result["tasks"]) == 2
            mock_list.assert_called_once_with(limit=20)

    @pytest.mark.asyncio
    async def test_list_tasks_with_custom_limit(self, api):
        """Test list with custom limit"""
        with patch.object(api.integration, 'list_active_tasks', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {"tasks": [], "total": 0}

            await api.list_tasks(limit=50)

            mock_list.assert_called_once_with(limit=50)

    @pytest.mark.asyncio
    async def test_cancel_task_success(self, api):
        """Test cancelling a task"""
        task_id = "task_to_cancel"

        with patch.object(api.integration, 'cancel_task', new_callable=AsyncMock) as mock_cancel:
            mock_cancel.return_value = True

            result = await api.cancel_task(task_id)

            assert result["success"] is True
            assert result["status"] == "cancelled"
            assert result["task_id"] == task_id

    @pytest.mark.asyncio
    async def test_cancel_task_not_found(self, api):
        """Test cancelling non-existent task"""
        task_id = "nonexistent"

        with patch.object(api.integration, 'cancel_task', new_callable=AsyncMock) as mock_cancel:
            mock_cancel.return_value = False

            result = await api.cancel_task(task_id)

            assert result["success"] is False
            assert "not found" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_cancel_task_error(self, api):
        """Test error during cancel"""
        task_id = "task_id"

        with patch.object(api.integration, 'cancel_task', new_callable=AsyncMock) as mock_cancel:
            mock_cancel.side_effect = Exception("Integration error")

            result = await api.cancel_task(task_id)

            assert result["success"] is False
            assert "Integration error" in result["error"]

    def test_should_route_computer_use(self, api):
        """Test routing detection"""
        with patch.object(api.integration, 'should_route_to_computer_use') as mock_route:
            mock_route.return_value = True

            result = api.should_route("computer_use")

            assert result is True
            mock_route.assert_called_once_with("computer_use")

    def test_should_not_route_other_actions(self, api):
        """Test non-computer_use actions"""
        with patch.object(api.integration, 'should_route_to_computer_use') as mock_route:
            mock_route.return_value = False

            result = api.should_route("web_search")

            assert result is False

    def test_singleton_pattern(self):
        """Test singleton returns same instance"""
        api1 = get_computer_use_controlplane_api()
        api2 = get_computer_use_controlplane_api()

        assert api1 is api2


class TestAPIIntegrationWithHTTP:
    """Tests for HTTP endpoint integration"""

    @pytest.fixture
    def api(self):
        """Create API instance"""
        return ComputerUseControlPlaneAPI()

    @pytest.mark.asyncio
    async def test_http_start_task_payload(self, api):
        """Test HTTP payload for start_task"""
        payload = {
            "user_intent": "Open website and read content",
            "approval_level": "SCREEN",
            "session_id": "http_sess_1"
        }

        result = await api.start_task(**payload)

        # Should match HTTP response format
        assert "task_id" in result
        assert "status" in result
        assert result["user_intent"] == payload["user_intent"]

    @pytest.mark.asyncio
    async def test_http_list_tasks_response_format(self, api):
        """Test HTTP response format for list"""
        with patch.object(api.integration, 'list_active_tasks', new_callable=AsyncMock) as mock_list:
            mock_list.return_value = {
                "tasks": [{"task_id": "t1", "status": "completed"}],
                "total": 1
            }

            result = await api.list_tasks()

            # Should have HTTP success field
            assert "success" in result
            assert result["success"] is True
