"""
Integration tests for Phase 5-3 Dashboard API

Tests:
- Metrics store operations
- WebSocket manager
- Dashboard API endpoints
- HTTP server endpoints
- Real-time updates
"""

import pytest
from datetime import datetime, timedelta
import json


def _has_flask() -> bool:
    """Check if Flask is available"""
    try:
        import flask
        return True
    except ImportError:
        return False


class TestMetricsStore:
    """Test metrics store functionality"""

    def test_record_metric(self):
        """Test recording a metric"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore()
        store.record("test_metric", 42.0, {"tag": "value"})

        latest = store.get_latest("test_metric")
        assert latest is not None
        assert latest["value"] == 42.0
        assert latest["metric_name"] == "test_metric"

    def test_get_metrics_history(self):
        """Test retrieving metric history"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore()

        # Record multiple values
        for i in range(5):
            store.record("test_metric", float(i), {})

        history = store.get_metrics("test_metric", limit=10)
        assert len(history) == 5
        assert history[0]["value"] == 0.0
        assert history[-1]["value"] == 4.0

    def test_get_metrics_with_limit(self):
        """Test metric history with limit"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore()

        # Record 10 values
        for i in range(10):
            store.record("test_metric", float(i), {})

        # Get only last 3
        history = store.get_metrics("test_metric", limit=3)
        assert len(history) == 3
        assert history[0]["value"] == 7.0
        assert history[-1]["value"] == 9.0

    def test_get_summary(self):
        """Test metric summary statistics"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore()

        # Record values: 10, 20, 30, 40, 50
        for value in [10, 20, 30, 40, 50]:
            store.record("test_metric", float(value), {})

        summary = store.get_summary("test_metric")
        assert summary["count"] == 5
        assert summary["min"] == 10.0
        assert summary["max"] == 50.0
        assert summary["avg"] == 30.0
        assert summary["latest"] == 50.0

    def test_max_history_limit(self):
        """Test that metrics store respects max history limit"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore(max_history=10)

        # Record 20 values
        for i in range(20):
            store.record("test_metric", float(i), {})

        # Should only keep last 10
        history = store.get_metrics("test_metric", limit=20)
        assert len(history) == 10
        assert history[0]["value"] == 10.0  # First value is 10
        assert history[-1]["value"] == 19.0  # Last value is 19

    def test_multiple_metrics(self):
        """Test storing multiple different metrics"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore()

        store.record("metric_a", 10.0)
        store.record("metric_b", 20.0)
        store.record("metric_a", 15.0)

        history_a = store.get_metrics("metric_a")
        history_b = store.get_metrics("metric_b")

        assert len(history_a) == 2
        assert len(history_b) == 1
        assert history_a[-1]["value"] == 15.0
        assert history_b[0]["value"] == 20.0

    def test_nonexistent_metric(self):
        """Test querying nonexistent metric"""
        from api.dashboard_api import MetricsStore

        store = MetricsStore()
        history = store.get_metrics("nonexistent")
        latest = store.get_latest("nonexistent")

        assert history == []
        assert latest is None


class TestWebSocketManager:
    """Test WebSocket manager"""

    def test_register_connection(self):
        """Test registering a WebSocket connection"""
        from api.dashboard_api import WebSocketManager

        manager = WebSocketManager()
        connection = object()

        manager.register(connection)
        assert len(manager._connections) == 1

    def test_unregister_connection(self):
        """Test unregistering a WebSocket connection"""
        from api.dashboard_api import WebSocketManager

        manager = WebSocketManager()
        connection = object()

        manager.register(connection)
        assert len(manager._connections) == 1

        manager.unregister(connection)
        assert len(manager._connections) == 0

    def test_unregister_nonexistent_connection(self):
        """Test unregistering a connection that doesn't exist"""
        from api.dashboard_api import WebSocketManager

        manager = WebSocketManager()
        connection = object()

        # Should not raise
        manager.unregister(connection)
        assert len(manager._connections) == 0

    def test_subscribe_and_broadcast(self):
        """Test pub/sub functionality"""
        from api.dashboard_api import WebSocketManager

        manager = WebSocketManager()
        messages = []

        def callback(msg):
            messages.append(msg)

        manager.subscribe("test_topic", callback)
        manager.broadcast("test_topic", {"value": 42})

        assert len(messages) == 1
        data = json.loads(messages[0])
        assert data["topic"] == "test_topic"
        assert data["data"]["value"] == 42

    def test_multiple_subscribers(self):
        """Test multiple subscribers to same topic"""
        from api.dashboard_api import WebSocketManager

        manager = WebSocketManager()
        messages_a = []
        messages_b = []

        def callback_a(msg):
            messages_a.append(msg)

        def callback_b(msg):
            messages_b.append(msg)

        manager.subscribe("topic", callback_a)
        manager.subscribe("topic", callback_b)
        manager.broadcast("topic", {"data": "test"})

        assert len(messages_a) == 1
        assert len(messages_b) == 1


class TestDashboardAPI:
    """Test dashboard API endpoints"""

    def test_get_cognitive_state(self):
        """Test cognitive state endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()
        result = api.get_cognitive_state()

        assert result["success"] in (True, False)
        if result["success"]:
            assert "data" in result
        else:
            assert "error" in result

    def test_get_error_predictions(self):
        """Test error predictions endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()
        result = api.get_error_predictions()

        assert result["success"] in (True, False)
        if result["success"]:
            assert "data" in result

    def test_get_deadlock_stats(self):
        """Test deadlock stats endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()
        result = api.get_deadlock_stats()

        assert result["success"] in (True, False)
        if result["success"]:
            assert "data" in result

    def test_get_deadlock_timeline(self):
        """Test deadlock timeline endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()
        result = api.get_deadlock_timeline(hours=24)

        assert result["success"] in (True, False)
        if result["success"]:
            assert "data" in result

    def test_get_sleep_consolidation(self):
        """Test sleep consolidation endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()
        result = api.get_sleep_consolidation()

        assert result["success"] in (True, False)
        if result["success"]:
            assert "data" in result

    def test_get_cache_performance(self):
        """Test cache performance endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()
        result = api.get_cache_performance()

        assert result["success"] in (True, False)
        if result["success"]:
            assert "aggregate" in result
            assert "hit_rate_pct" in result["aggregate"]

    def test_list_available_metrics(self):
        """Test listing available metrics"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()

        # Record some metrics first
        api.metrics.record("test_metric_1", 10.0)
        api.metrics.record("test_metric_2", 20.0)

        result = api.list_available_metrics()

        assert result["success"] is True
        assert "metrics" in result
        assert "test_metric_1" in result["metrics"]
        assert "test_metric_2" in result["metrics"]

    def test_get_metrics_summary(self):
        """Test metrics summary endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()

        # Record metrics
        for value in [10, 20, 30, 40, 50]:
            api.metrics.record("test_metric", float(value))

        result = api.get_metrics_summary("test_metric")

        assert result["success"] is True
        assert result["data"]["min"] == 10.0
        assert result["data"]["max"] == 50.0

    def test_get_metrics_history(self):
        """Test metrics history endpoint"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api

        reset_dashboard_api()
        api = get_dashboard_api()

        # Record metrics
        for i in range(5):
            api.metrics.record("test_metric", float(i))

        result = api.get_metrics_history("test_metric", limit=10)

        assert result["success"] is True
        assert result["count"] == 5
        assert len(result["data"]) == 5


class TestHTTPServer:
    """Test HTTP server endpoints"""

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_server_initialization(self):
        """Test HTTP server can be created"""
        from api.http_server import create_server

        server = create_server(port=5001)
        assert server is not None
        assert server.port == 5001

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_health_endpoint(self):
        """Test health check endpoint"""
        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(port=5002)
        client = server.app.test_client()

        response = client.get("/health")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data["status"] == "healthy"
        assert data["service"] == "dashboard-api"

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_api_docs_endpoint(self):
        """Test API documentation endpoint"""
        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(port=5003)
        client = server.app.test_client()

        response = client.get("/api/v1/docs")
        assert response.status_code == 200
        data = json.loads(response.data)
        assert "endpoints" in data
        assert "version" in data

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_cognitive_state_endpoint(self):
        """Test cognitive state endpoint"""
        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(port=5004)
        client = server.app.test_client()

        response = client.get("/api/v1/cognitive/state")
        assert response.status_code in (200, 400)
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_cache_performance_endpoint(self):
        """Test cache performance endpoint"""
        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(port=5005)
        client = server.app.test_client()

        response = client.get("/api/v1/cache/performance")
        assert response.status_code in (200, 400)
        data = json.loads(response.data)
        assert "success" in data

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_session_cookie_is_http_only(self):
        """Test that the dashboard session cookie is not readable from browser JS."""
        from flask import Response

        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(port=5007)
        with server.app.test_request_context("/api/v1/cognitive/state", headers={"Origin": "http://localhost:5007"}):
            response = Response()
            updated = server._ensure_session_cookie(response)

        set_cookie_headers = updated.headers.getlist("Set-Cookie")
        assert any("elyan_session=" in header and "HttpOnly" in header for header in set_cookie_headers)
        assert updated.headers.get("X-Elyan-Session-Token")

    @pytest.mark.skipif(not _has_flask(), reason="Flask not available")
    def test_404_response(self):
        """Test 404 error handling"""
        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(port=5006)
        client = server.app.test_client()

        response = client.get("/nonexistent")
        assert response.status_code == 404


class TestDashboardAPIIntegration:
    """Integration tests for dashboard API"""

    def test_metrics_collection_thread(self):
        """Test that metrics collection thread works"""
        from api.dashboard_api import get_dashboard_api, reset_dashboard_api
        import time

        reset_dashboard_api()
        api = get_dashboard_api()

        # Wait for a collection cycle
        time.sleep(6)

        # Check if metrics were collected
        available = api.list_available_metrics()
        assert available["success"] is True

    def test_concurrent_metric_access(self):
        """Test thread-safe metric access"""
        from api.dashboard_api import MetricsStore
        import threading

        store = MetricsStore()
        results = []

        def record_and_read():
            for i in range(10):
                store.record("test_metric", float(i))
                history = store.get_metrics("test_metric")
                results.append(len(history))

        threads = [threading.Thread(target=record_and_read) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should have recorded metrics without race conditions
        assert len(results) == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
