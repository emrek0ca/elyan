"""
Phase 5-3: Dashboard HTTP Server

Flask-based HTTP server for Dashboard API with:
- REST endpoints for widget data
- CORS support
- JSON responses
- Error handling
- Health checks
"""

import logging
import json
from typing import Dict, Any, Tuple, Optional
from functools import wraps
from datetime import datetime

logger = logging.getLogger(__name__)

# Try to import Flask, gracefully degrade if not available
try:
    from flask import Flask, jsonify, request, Response
    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False
    logger.warning("Flask not available - HTTP server requires: pip install flask flask-cors")

# Try to import Socket.IO for WebSocket support
try:
    from socketio import AsyncServer, WSGIApp
    SOCKETIO_AVAILABLE = True
except ImportError:
    SOCKETIO_AVAILABLE = False
    logger.warning("Socket.IO not available - WebSocket requires: pip install python-socketio python-engineio")


def require_flask(func):
    """Decorator to check Flask availability"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        if not FLASK_AVAILABLE:
            raise RuntimeError("Flask is required for HTTP server. Install with: pip install flask flask-cors")
        return func(*args, **kwargs)
    return wrapper


class DashboardHTTPServer:
    """HTTP server for Dashboard API"""

    def __init__(self, host: str = "127.0.0.1", port: int = 5000, debug: bool = False):
        """Initialize HTTP server"""
        if not FLASK_AVAILABLE:
            raise RuntimeError("Flask required")

        self.host = host
        self.port = port
        self.debug = debug
        self.app = Flask(__name__)
        self.sio = None
        self.wsgi_app = None

        # Enable CORS
        try:
            from flask_cors import CORS
            CORS(self.app)
        except ImportError:
            logger.warning("CORS not available - install flask-cors for cross-origin requests")

        # Setup WebSocket if available
        if SOCKETIO_AVAILABLE:
            self._setup_websocket()

        self._setup_routes()

    def _setup_websocket(self) -> None:
        """Setup WebSocket support with Socket.IO"""
        self.sio = AsyncServer(
            async_mode='threading',
            cors_allowed_origins='*',
            logger=False,
            engineio_logger=False
        )
        self.wsgi_app = WSGIApp(self.sio, self.app)

        @self.sio.event
        async def connect(sid, environ):
            """Handle WebSocket connection."""
            logger.info(f"WebSocket client connected: {sid}")
            from core.event_broadcaster import get_event_broadcaster
            broadcaster = get_event_broadcaster()
            await broadcaster.register_websocket(self.sio.emit)

        @self.sio.event
        async def disconnect(sid):
            """Handle WebSocket disconnection."""
            logger.info(f"WebSocket client disconnected: {sid}")

        @self.sio.event
        async def subscribe(sid, data):
            """Subscribe to specific event types."""
            event_type = data.get("event_type", "all")
            logger.debug(f"Client {sid} subscribed to {event_type}")
            await self.sio.emit('subscription_confirmed', {
                'event_type': event_type
            }, to=sid)

        @self.sio.event
        async def get_history(sid, data):
            """Get event history."""
            event_type = data.get("event_type")
            limit = data.get("limit", 20)
            from core.event_broadcaster import get_event_broadcaster
            broadcaster = get_event_broadcaster()
            history = await broadcaster.get_event_history(event_type, limit)
            await self.sio.emit('history', {
                'events': history
            }, to=sid)

    def _setup_routes(self) -> None:
        """Setup all API routes"""
        # Health check
        @self.app.route("/health", methods=["GET"])
        def health_check() -> Tuple[Dict[str, Any], int]:
            return {
                "status": "healthy",
                "timestamp": datetime.now().isoformat(),
                "service": "dashboard-api"
            }, 200

        # Cognitive state
        @self.app.route("/api/v1/cognitive/state", methods=["GET"])
        def cognitive_state() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_cognitive_state()
            status = 200 if result.get("success") else 400
            return result, status

        # Error predictions
        @self.app.route("/api/v1/predictions/errors", methods=["GET"])
        def error_predictions() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_error_predictions()
            status = 200 if result.get("success") else 400
            return result, status

        # Deadlock stats
        @self.app.route("/api/v1/deadlock/stats", methods=["GET"])
        def deadlock_stats() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_deadlock_stats()
            status = 200 if result.get("success") else 400
            return result, status

        # Deadlock timeline
        @self.app.route("/api/v1/deadlock/timeline", methods=["GET"])
        def deadlock_timeline() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            hours = request.args.get("hours", 24, type=int)
            api = get_dashboard_api()
            result = api.get_deadlock_timeline(hours)
            status = 200 if result.get("success") else 400
            return result, status

        # Sleep consolidation
        @self.app.route("/api/v1/sleep/consolidation", methods=["GET"])
        def sleep_consolidation() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_sleep_consolidation()
            status = 200 if result.get("success") else 400
            return result, status

        # Cache performance
        @self.app.route("/api/v1/cache/performance", methods=["GET"])
        def cache_performance() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_cache_performance()
            status = 200 if result.get("success") else 400
            return result, status

        # Metrics history
        @self.app.route("/api/v1/metrics/history", methods=["GET"])
        def metrics_history() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            metric_name = request.args.get("name")
            limit = request.args.get("limit", 100, type=int)

            if not metric_name:
                return {"error": "Missing 'name' parameter"}, 400

            api = get_dashboard_api()
            result = api.get_metrics_history(metric_name, limit)
            status = 200 if result.get("success") else 400
            return result, status

        # Metrics summary
        @self.app.route("/api/v1/metrics/summary", methods=["GET"])
        def metrics_summary() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            metric_name = request.args.get("name")

            if not metric_name:
                return {"error": "Missing 'name' parameter"}, 400

            api = get_dashboard_api()
            result = api.get_metrics_summary(metric_name)
            status = 200 if result.get("success") else 400
            return result, status

        # List available metrics
        @self.app.route("/api/v1/metrics/available", methods=["GET"])
        def available_metrics() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.list_available_metrics()
            status = 200 if result.get("success") else 400
            return result, status

        # ===== Approval System Routes =====

        # Get pending approvals
        @self.app.route("/api/v1/approvals/pending", methods=["GET"])
        def get_pending_approvals() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_pending_approvals()
            status = 200 if result.get("success") else 400
            return result, status

        # Resolve approval
        @self.app.route("/api/v1/approvals/resolve", methods=["POST"])
        def resolve_approval_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            data = request.get_json() or {}
            request_id = data.get("request_id")
            approved = data.get("approved", False)
            resolver_id = data.get("resolver_id", "web_ui")

            if not request_id:
                return {"error": "Missing request_id"}, 400

            api = get_dashboard_api()
            result = api.resolve_approval(request_id, approved, resolver_id)
            status = 200 if result.get("success") else 400
            return result, status

        # Bulk resolve approvals
        @self.app.route("/api/v1/approvals/bulk-resolve", methods=["POST"])
        def bulk_resolve_approvals_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            data = request.get_json() or {}
            request_ids = data.get("request_ids", [])
            approved = data.get("approved", False)
            resolver_id = data.get("resolver_id", "web_ui")

            if not request_ids or not isinstance(request_ids, list):
                return {"error": "Missing or invalid request_ids list"}, 400

            api = get_dashboard_api()
            result = api.bulk_resolve_approvals(request_ids, approved, resolver_id)
            status = 200 if result.get("success") else 400
            return result, status

        # Approval workflow metrics
        @self.app.route("/api/v1/approvals/workflow-metrics", methods=["GET"])
        def approval_workflow_metrics_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = api.get_approval_workflow_metrics()
            status = 200 if result.get("success") else 400
            return result, status

        # ===== Run Inspector Routes =====

        # Get run details
        @self.app.route("/api/v1/runs/<run_id>", methods=["GET"])
        def get_run_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            api = get_dashboard_api()
            result = asyncio.run(api.get_run(run_id))
            status = 200 if result.get("success") else 400
            return result, status

        # List runs
        @self.app.route("/api/v1/runs", methods=["GET"])
        def list_runs_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            limit = request.args.get("limit", 20, type=int)
            status_filter = request.args.get("status", None)

            api = get_dashboard_api()
            result = asyncio.run(api.list_runs(limit, status_filter))
            status_code = 200 if result.get("success") else 400
            return result, status_code

        # Cancel run
        @self.app.route("/api/v1/runs/<run_id>/cancel", methods=["POST"])
        def cancel_run_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            api = get_dashboard_api()
            result = asyncio.run(api.cancel_run(run_id))
            status = 200 if result.get("success") else 400
            return result, status

        # Get step timeline (Gantt chart data)
        @self.app.route("/api/v1/runs/<run_id>/timeline", methods=["GET"])
        def step_timeline_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            api = get_dashboard_api()
            result = asyncio.run(api.get_step_timeline(run_id))
            status = 200 if result.get("success") else 400
            return result, status

        # ===== Memory Timeline Route =====

        # ===== Analytics Routes =====

        # Approval metrics
        @self.app.route("/api/v1/analytics/approvals", methods=["GET"])
        def approval_metrics_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            days = request.args.get("days", 7, type=int)

            api = get_dashboard_api()
            result = asyncio.run(api.get_approval_metrics(days))
            status = 200 if result.get("success") else 400
            return result, status

        # Approval trends
        @self.app.route("/api/v1/analytics/approval-trends", methods=["GET"])
        def approval_trends_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            days = request.args.get("days", 7, type=int)

            api = get_dashboard_api()
            result = asyncio.run(api.get_approval_trends(days))
            status = 200 if result.get("success") else 400
            return result, status

        # Memory timeline
        @self.app.route("/api/v1/memory/timeline", methods=["GET"])
        def memory_timeline_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import asyncio
            limit = request.args.get("limit", 20, type=int)

            api = get_dashboard_api()
            result = asyncio.run(api.get_memory_timeline(limit))
            status = 200 if result.get("success") else 400
            return result, status

        # Smart suggestions endpoint
        @self.app.route("/api/v1/suggestions/smart", methods=["GET"])
        def smart_suggestions_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            import json
            context_str = request.args.get("context", "{}")
            try:
                context = json.loads(context_str) if context_str else {}
            except json.JSONDecodeError:
                context = {}

            api = get_dashboard_api()
            result = api.get_smart_suggestions(context)
            status = 200 if result.get("success") else 400
            return result, status

        # Adaptive response endpoint
        @self.app.route("/api/v1/suggestions/adaptive", methods=["POST"])
        def adaptive_response_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            data = request.get_json() or {}

            intent = data.get("intent", "")
            actions = data.get("available_actions", [])
            context = data.get("context", {})

            if not intent or not actions:
                return {"success": False, "error": "Missing intent or available_actions"}, 400

            api = get_dashboard_api()
            result = api.get_adaptive_response(intent, actions, context)
            status = 200 if result.get("success") else 400
            return result, status

        # Learning record endpoint
        @self.app.route("/api/v1/learning/record", methods=["POST"])
        def learning_record_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            data = request.get_json() or {}

            intent = data.get("intent", "")
            action = data.get("action", "")
            success = data.get("success", False)
            context = data.get("context", {})
            duration = data.get("duration", 0.0)

            if not intent or not action:
                return {"success": False, "error": "Missing intent or action"}, 400

            api = get_dashboard_api()
            result = api.learn_interaction(intent, action, success, context, duration)
            status = 200 if result.get("success") else 400
            return result, status

        # Computer Use endpoints
        @self.app.route("/api/v1/computer_use/tasks", methods=["POST"])
        def start_computer_use_task() -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api
            import asyncio

            data = request.get_json() or {}
            user_intent = data.get("user_intent", "")
            approval_level = data.get("approval_level", "CONFIRM")

            if not user_intent:
                return {"success": False, "error": "Missing user_intent"}, 400

            api = get_computer_use_api()
            result = asyncio.run(api.start_task(user_intent, approval_level))
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/computer_use/tasks/<task_id>", methods=["GET"])
        def get_computer_use_task_status(task_id: str) -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api
            import asyncio

            api = get_computer_use_api()
            result = asyncio.run(api.get_task_status(task_id))
            status = 200 if result.get("success") else 404
            return result, status

        @self.app.route("/api/v1/computer_use/tasks/<task_id>/evidence", methods=["GET"])
        def get_computer_use_task_evidence(task_id: str) -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api
            import asyncio

            api = get_computer_use_api()
            result = asyncio.run(api.get_task_evidence(task_id))
            status = 200 if result.get("success") else 404
            return result, status

        @self.app.route("/api/v1/computer_use/tasks", methods=["GET"])
        def list_computer_use_tasks() -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api
            import asyncio

            status_filter = request.args.get("status")
            limit = request.args.get("limit", 20, type=int)

            api = get_computer_use_api()
            result = asyncio.run(api.list_tasks(status=status_filter, limit=limit))
            status = 200 if result.get("success") else 400
            return result, status

        # API documentation
        @self.app.route("/api/v1/docs", methods=["GET"])
        def api_docs() -> Dict[str, Any]:
            return {
                "version": "1.0",
                "endpoints": {
                    "health": "GET /health",
                    "cognitive_state": "GET /api/v1/cognitive/state",
                    "error_predictions": "GET /api/v1/predictions/errors",
                    "deadlock_stats": "GET /api/v1/deadlock/stats",
                    "deadlock_timeline": "GET /api/v1/deadlock/timeline?hours=24",
                    "sleep_consolidation": "GET /api/v1/sleep/consolidation",
                    "cache_performance": "GET /api/v1/cache/performance",
                    "metrics_history": "GET /api/v1/metrics/history?name=<metric>&limit=100",
                    "metrics_summary": "GET /api/v1/metrics/summary?name=<metric>",
                    "available_metrics": "GET /api/v1/metrics/available",
                    "pending_approvals": "GET /api/v1/approvals/pending",
                    "resolve_approval": "POST /api/v1/approvals/resolve",
                    "bulk_resolve_approvals": "POST /api/v1/approvals/bulk-resolve",
                    "approval_workflow_metrics": "GET /api/v1/approvals/workflow-metrics",
                    "get_run": "GET /api/v1/runs/<run_id>",
                    "list_runs": "GET /api/v1/runs?limit=20&status=*",
                    "cancel_run": "POST /api/v1/runs/<run_id>/cancel",
                    "step_timeline": "GET /api/v1/runs/<run_id>/timeline",
                    "memory_timeline": "GET /api/v1/memory/timeline?limit=20",
                    "smart_suggestions": "GET /api/v1/suggestions/smart?context={json}",
                    "adaptive_response": "POST /api/v1/suggestions/adaptive",
                    "learning_record": "POST /api/v1/learning/record",
                    "start_computer_use_task": "POST /api/v1/computer_use/tasks",
                    "get_task_status": "GET /api/v1/computer_use/tasks/<task_id>",
                    "get_task_evidence": "GET /api/v1/computer_use/tasks/<task_id>/evidence",
                    "list_tasks": "GET /api/v1/computer_use/tasks?status=*&limit=20"
                }
            }

        # 404 handler
        @self.app.errorhandler(404)
        def not_found(error) -> Tuple[Dict[str, str], int]:
            return {"error": "Endpoint not found"}, 404

        # 500 handler
        @self.app.errorhandler(500)
        def server_error(error) -> Tuple[Dict[str, str], int]:
            logger.error(f"Server error: {error}")
            return {"error": "Internal server error"}, 500

    @require_flask
    def run(self, debug: Optional[bool] = None) -> None:
        """Start the HTTP server"""
        debug = debug if debug is not None else self.debug
        logger.info(f"Starting Dashboard HTTP Server on {self.host}:{self.port}")

        if SOCKETIO_AVAILABLE and self.sio:
            # Use Socket.IO server with WebSocket support
            import logging as logging_module
            logging_module.getLogger('engineio').setLevel(logging_module.WARNING)
            logging_module.getLogger('socketio').setLevel(logging_module.WARNING)

            self.sio.run(self.app, host=self.host, port=self.port, debug=debug, use_reloader=False)
        else:
            # Fallback to plain Flask
            self.app.run(host=self.host, port=self.port, debug=debug, use_reloader=False)

    @require_flask
    def start_background(self) -> None:
        """Start server in background thread"""
        import threading

        def run_server():
            self.run(debug=False)

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        msg = f"Dashboard HTTP Server started in background on {self.host}:{self.port}"
        if SOCKETIO_AVAILABLE:
            msg += " (with WebSocket support)"
        logger.info(msg)


def create_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> Optional[DashboardHTTPServer]:
    """Create and return a dashboard HTTP server"""
    try:
        return DashboardHTTPServer(host=host, port=port, debug=debug)
    except RuntimeError as e:
        logger.error(f"Cannot create HTTP server: {e}")
        return None
