"""Tests for Computer Use HTTP Routes"""

import pytest
from unittest.mock import patch, AsyncMock
import json


@pytest.fixture
def app():
    """Create test Flask app"""
    try:
        from api.http_server import DashboardHTTPServer
        server = DashboardHTTPServer(debug=True)
        return server.app.test_client()
    except ImportError:
        pytest.skip("Flask not available")


class TestComputerUseControlPlaneRoutes:
    """Tests for Computer Use ControlPlane HTTP routes"""

    def test_start_task_route(self, app):
        """Test POST /api/v1/computer_use/controlplane/tasks"""
        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.start_task.return_value = {
                "task_id": "task_123",
                "status": "pending",
                "user_intent": "Test task"
            }
            mock_get.return_value = mock_api

            response = app.post(
                '/api/v1/computer_use/controlplane/tasks',
                data=json.dumps({
                    "user_intent": "Test task",
                    "approval_level": "CONFIRM"
                }),
                content_type='application/json'
            )

            assert response.status_code == 200
            data = response.get_json()
            assert data["status"] == "pending"
            assert data["task_id"] == "task_123"

    def test_list_tasks_route(self, app):
        """Test GET /api/v1/computer_use/controlplane/tasks"""
        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.list_tasks.return_value = {
                "success": True,
                "tasks": [
                    {"task_id": "task_1", "status": "completed"},
                    {"task_id": "task_2", "status": "running"}
                ],
                "total": 2
            }
            mock_get.return_value = mock_api

            response = app.get('/api/v1/computer_use/controlplane/tasks?limit=20')

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert len(data["tasks"]) == 2

    def test_get_task_status_route(self, app):
        """Test GET /api/v1/computer_use/controlplane/tasks/<task_id>"""
        task_id = "task_123"

        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.get_task_status.return_value = {
                "task_id": task_id,
                "status": "running",
                "session_id": "sess_1"
            }
            mock_get.return_value = mock_api

            response = app.get(f'/api/v1/computer_use/controlplane/tasks/{task_id}')

            assert response.status_code == 200
            data = response.get_json()
            assert data["task_id"] == task_id
            assert data["status"] == "running"

    def test_cancel_task_route(self, app):
        """Test POST /api/v1/computer_use/controlplane/tasks/<task_id>/cancel"""
        task_id = "task_123"

        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.cancel_task.return_value = {
                "success": True,
                "task_id": task_id,
                "status": "cancelled"
            }
            mock_get.return_value = mock_api

            response = app.post(f'/api/v1/computer_use/controlplane/tasks/{task_id}/cancel')

            assert response.status_code == 200
            data = response.get_json()
            assert data["success"] is True
            assert data["status"] == "cancelled"

    def test_api_docs_includes_controlplane(self, app):
        """Test /api/v1/docs includes ControlPlane endpoints"""
        response = app.get('/api/v1/docs')

        assert response.status_code == 200
        data = response.get_json()
        endpoints = data.get("endpoints", {})

        # Check that ControlPlane endpoints are documented
        assert "controlplane_start_task" in endpoints
        assert "controlplane_list_tasks" in endpoints
        assert "controlplane_get_status" in endpoints
        assert "controlplane_cancel_task" in endpoints


class TestComputerUseRouteErrors:
    """Test error handling in routes"""

    def test_start_task_missing_intent(self, app):
        """Test start_task with missing user_intent"""
        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.start_task.return_value = {
                "status": "pending"
            }
            mock_get.return_value = mock_api

            response = app.post(
                '/api/v1/computer_use/controlplane/tasks',
                data=json.dumps({}),
                content_type='application/json'
            )

            # Should still return 200 (empty intent is allowed)
            assert response.status_code == 200

    def test_get_task_not_found(self, app):
        """Test get_task_status with non-existent task"""
        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.get_task_status.return_value = {
                "error": "Task not found"
            }
            mock_get.return_value = mock_api

            response = app.get('/api/v1/computer_use/controlplane/tasks/nonexistent')

            assert response.status_code == 404

    def test_cancel_task_not_found(self, app):
        """Test cancel_task with non-existent task"""
        with patch('api.computer_use_controlplane.get_computer_use_controlplane_api') as mock_get:
            mock_api = AsyncMock()
            mock_api.cancel_task.return_value = {
                "success": False,
                "error": "Task not found"
            }
            mock_get.return_value = mock_api

            response = app.post('/api/v1/computer_use/controlplane/tasks/nonexistent/cancel')

            assert response.status_code == 404
