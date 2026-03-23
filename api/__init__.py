"""
Dashboard API Package - Phase 5 Extended Monitoring

Real-time API for dashboard widgets with WebSocket and HTTP support.
"""

from api.dashboard_api import (
    DashboardAPIv1,
    MetricsStore,
    WebSocketManager,
    get_dashboard_api,
    reset_dashboard_api,
)

from api.http_server import (
    DashboardHTTPServer,
    create_server,
)

__all__ = [
    "DashboardAPIv1",
    "MetricsStore",
    "WebSocketManager",
    "get_dashboard_api",
    "reset_dashboard_api",
    "DashboardHTTPServer",
    "create_server",
]
