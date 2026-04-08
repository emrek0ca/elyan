from __future__ import annotations

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
import asyncio
import threading
import secrets
from typing import Dict, Any, Tuple, Optional
from functools import wraps
from datetime import datetime

from config.elyan_config import elyan_config

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
        self._async_bridge_timeout = 60.0
        self._async_loop = asyncio.new_event_loop()
        self._async_thread = threading.Thread(
            target=self._run_async_loop,
            name="dashboard-http-async-bridge",
            daemon=True,
        )
        self._async_thread.start()
        self._allowed_origins = list(
            elyan_config.get("security.http.allowedOrigins", elyan_config.get("gateway.corsOrigins", [])) or []
        )
        self._csrf_enabled = bool(elyan_config.get("security.http.csrf.enabled", True))
        self._csrf_cookie_name = str(elyan_config.get("security.http.csrf.cookie_name", "elyan_csrf") or "elyan_csrf")
        self._csrf_header_name = str(elyan_config.get("security.http.csrf.header_name", "X-Elyan-CSRF") or "X-Elyan-CSRF")
        self._session_cookie_name = str(elyan_config.get("security.http.session.cookie_name", "elyan_session") or "elyan_session")
        self._session_header_name = str(elyan_config.get("security.http.session.header_name", "X-Elyan-Session-Token") or "X-Elyan-Session-Token")
        self._trusted_local_origins = {
            f"http://{self.host}:{self.port}",
            f"https://{self.host}:{self.port}",
            f"http://127.0.0.1:{self.port}",
            f"https://127.0.0.1:{self.port}",
            f"http://localhost:{self.port}",
            f"https://localhost:{self.port}",
            "tauri://localhost",
            "http://tauri.localhost",
            "https://tauri.localhost",
        }

        # Enable CORS
        try:
            from flask_cors import CORS
            CORS(self.app, origins=self._allowed_origins, supports_credentials=True)
        except ImportError:
            logger.warning("CORS not available - install flask-cors for cross-origin requests")

        # Setup WebSocket if available
        if SOCKETIO_AVAILABLE:
            self._setup_websocket()

        self._setup_security_hooks()
        self._setup_routes()

    def _run_async_loop(self) -> None:
        """Run dedicated event loop for async API calls from Flask threads."""
        asyncio.set_event_loop(self._async_loop)
        self._async_loop.run_forever()

    def _run_async(self, coro):
        """Execute coroutine on dedicated loop and wait for result."""
        future = asyncio.run_coroutine_threadsafe(coro, self._async_loop)
        return future.result(timeout=self._async_bridge_timeout)

    def _shutdown_async_bridge(self) -> None:
        """Stop dedicated async loop."""
        if self._async_loop.is_running():
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)

    def _setup_websocket(self) -> None:
        """Setup WebSocket support with Socket.IO"""
        try:
            self.sio = AsyncServer(
                async_mode='threading',
                cors_allowed_origins=self._allowed_origins,
                logger=False,
                engineio_logger=False
            )
        except Exception as exc:
            logger.warning(f"Socket.IO disabled (invalid async mode/runtime): {exc}")
            self.sio = None
            self.wsgi_app = None
            return
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

    def _is_browser_mutation(self) -> bool:
        return request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"} and bool(request.headers.get("Origin"))

    def _is_allowed_origin(self, origin: str) -> bool:
        token = str(origin or "").strip()
        return bool(token) and token in set(self._allowed_origins + list(self._trusted_local_origins))

    def _ensure_csrf_cookie(self, response: Response) -> Response:
        if not self._csrf_enabled:
            return response
        current = request.cookies.get(self._csrf_cookie_name)
        if current:
            response.set_cookie(self._csrf_cookie_name, current, httponly=False, samesite="Lax", secure=False)
            return response
        token = secrets.token_urlsafe(24)
        response.set_cookie(self._csrf_cookie_name, token, httponly=False, samesite="Lax", secure=False)
        return response

    def _session_manager(self):
        from core.security.session_security import get_session_manager

        return get_session_manager()

    def _get_session_token(self) -> str:
        return str(
            request.headers.get(self._session_header_name, "")
            or request.cookies.get(self._session_cookie_name, "")
            or ""
        ).strip()

    def _issue_session_token(self) -> str:
        manager = self._session_manager()
        token = manager.issue_token(
            "dashboard_local",
            {
                "scope": "dashboard_http",
                "origin": str(request.headers.get("Origin") or ""),
                "user_agent": str(request.headers.get("User-Agent") or "")[:200],
            },
            metadata={
                "scope": "dashboard_http",
                "origin": str(request.headers.get("Origin") or ""),
            },
        )
        return token

    def _ensure_session_cookie(self, response: Response) -> Response:
        if not request.path.startswith("/api/"):
            return response
        origin = str(request.headers.get("Origin") or "").strip()
        if origin and not self._is_allowed_origin(origin):
            return response
        token = self._get_session_token()
        if token and self._session_manager().validate_token(token):
            response.set_cookie(self._session_cookie_name, token, httponly=False, samesite="Lax", secure=False)
            response.headers[self._session_header_name] = token
            return response
        token = self._issue_session_token()
        response.set_cookie(self._session_cookie_name, token, httponly=False, samesite="Lax", secure=False)
        response.headers[self._session_header_name] = token
        return response

    def _setup_security_hooks(self) -> None:
        @self.app.before_request
        def _browser_mutation_guard():
            origin = str(request.headers.get("Origin") or "").strip()
            if not self._is_browser_mutation():
                if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
                    token = self._get_session_token()
                    if not token or not self._session_manager().validate_token(token):
                        return {"success": False, "error": "Auth required"}, 403
                return None
            if not self._is_allowed_origin(origin):
                return {"success": False, "error": "Origin not allowed"}, 403
            token = self._get_session_token()
            if not token or not self._session_manager().validate_token(token):
                return {"success": False, "error": "Auth required"}, 403
            if self._csrf_enabled and origin not in self._trusted_local_origins:
                header_token = str(request.headers.get(self._csrf_header_name) or "").strip()
                cookie_token = str(request.cookies.get(self._csrf_cookie_name) or "").strip()
                if not header_token or not cookie_token or header_token != cookie_token:
                    return {"success": False, "error": "CSRF validation failed"}, 403
            return None

        @self.app.after_request
        def _security_headers(response: Response):
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
            response.headers["Content-Security-Policy"] = "default-src 'self'; connect-src 'self' http: https: ws: wss: tauri:; img-src 'self' data: blob:; media-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'"
            response.headers["Access-Control-Expose-Headers"] = self._session_header_name
            if request.path.startswith("/api/"):
                response.headers["Cache-Control"] = "no-store"
            if request.headers.get("Origin"):
                response.headers["Vary"] = "Origin"
            response = self._ensure_csrf_cookie(response)
            return self._ensure_session_cookie(response)

    def _setup_routes(self) -> None:
        """Setup all API routes"""
        try:
            from api.privacy_api import create_privacy_blueprint
            self.app.register_blueprint(create_privacy_blueprint())
        except Exception as exc:
            logger.warning(f"Privacy blueprint registration failed: {exc}")

        try:
            from api.elyan_api import create_elyan_blueprint
            self.app.register_blueprint(create_elyan_blueprint())
        except Exception as exc:
            logger.warning(f"Elyan blueprint registration failed: {exc}")

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

        @self.app.route("/api/v1/metrics/multi-agent", methods=["GET"])
        def multi_agent_metrics() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_multi_agent_metrics())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/security/summary", methods=["GET"])
        def security_summary() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_security_summary())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/security/events", methods=["GET"])
        def security_events() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api

            limit = request.args.get("limit", 40, type=int)
            api = get_dashboard_api()
            result = self._run_async(api.get_security_events(limit))
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
            resolver_id = str(data.get("resolver_id") or request.headers.get("X-Elyan-Resolver") or "web_ui").strip()[:64]

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
            resolver_id = str(data.get("resolver_id") or request.headers.get("X-Elyan-Resolver") or "web_ui").strip()[:64]

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

        # Metrics endpoints
        @self.app.route("/api/v1/metrics/dora", methods=["GET"])
        def metrics_dora_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            period = request.args.get("period", 24, type=int)
            api = get_dashboard_api()
            result = self._run_async(api.get_dora_metrics(period))
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/metrics/tools", methods=["GET"])
        def metrics_tools_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_tool_metrics())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/metrics/health", methods=["GET"])
        def metrics_health_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_health_metrics())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/metrics/learning", methods=["GET"])
        def metrics_learning_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_learning_metrics())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/metrics/toil", methods=["GET"])
        def metrics_toil_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_toil_metrics())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/system/backends", methods=["GET"])
        def runtime_backends_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api

            api = get_dashboard_api()
            result = self._run_async(api.get_runtime_backends())
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/feedback/<run_id>", methods=["POST"])
        def feedback_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            data = request.get_json() or {}
            satisfaction = float(data.get("satisfaction", 0.5))
            api = get_dashboard_api()
            result = self._run_async(api.submit_feedback(run_id, satisfaction))
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/htn/add-method", methods=["POST"])
        def htn_add_method_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            data = request.get_json() or {}
            task_name = str(data.get("task_name") or "").strip()
            subtasks = data.get("subtasks") or []
            if not task_name:
                return {"success": False, "error": "Missing task_name"}, 400
            api = get_dashboard_api()
            result = self._run_async(api.add_htn_method(task_name, subtasks))
            status = 200 if result.get("success") else 400
            return result, status

        # ===== Run Inspector Routes =====

        # Get run details
        @self.app.route("/api/v1/runs/<run_id>", methods=["GET"])
        def get_run_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_run(run_id))
            status = 200 if result.get("success") else 400
            return result, status

        # List runs
        @self.app.route("/api/v1/runs", methods=["GET"])
        def list_runs_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            limit = request.args.get("limit", 20, type=int)
            status_filter = request.args.get("status", None)

            api = get_dashboard_api()
            result = self._run_async(api.list_runs(limit, status_filter))
            status_code = 200 if result.get("success") else 400
            return result, status_code

        # Cancel run
        @self.app.route("/api/v1/runs/<run_id>/cancel", methods=["POST"])
        def cancel_run_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.cancel_run(run_id))
            status = 200 if result.get("success") else 400
            return result, status

        # Get step timeline (Gantt chart data)
        @self.app.route("/api/v1/runs/<run_id>/timeline", methods=["GET"])
        def step_timeline_endpoint(run_id: str) -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            api = get_dashboard_api()
            result = self._run_async(api.get_step_timeline(run_id))
            status = 200 if result.get("success") else 400
            return result, status

        # ===== Memory Timeline Route =====

        # ===== Analytics Routes =====

        # Approval metrics
        @self.app.route("/api/v1/analytics/approvals", methods=["GET"])
        def approval_metrics_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            days = request.args.get("days", 7, type=int)

            api = get_dashboard_api()
            result = self._run_async(api.get_approval_metrics(days))
            status = 200 if result.get("success") else 400
            return result, status

        # Approval trends
        @self.app.route("/api/v1/analytics/approval-trends", methods=["GET"])
        def approval_trends_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            days = request.args.get("days", 7, type=int)

            api = get_dashboard_api()
            result = self._run_async(api.get_approval_trends(days))
            status = 200 if result.get("success") else 400
            return result, status

        # Memory timeline
        @self.app.route("/api/v1/memory/timeline", methods=["GET"])
        def memory_timeline_endpoint() -> Tuple[Dict[str, Any], int]:
            from api.dashboard_api import get_dashboard_api
            limit = request.args.get("limit", 20, type=int)

            api = get_dashboard_api()
            result = self._run_async(api.get_memory_timeline(limit))
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

        @self.app.route("/api/v1/learning/policy", methods=["POST"])
        def learning_policy_endpoint() -> Tuple[Dict[str, Any], int]:
            from core.learning_control import get_learning_control_plane

            data = request.get_json() or {}
            user_id = str(data.get("user_id") or "local")
            plane = get_learning_control_plane()

            updates: Dict[str, Any] = {}
            if "learning_mode" in data or "retention_policy" in data:
                updates["preferences"] = plane.set_learning_preferences(
                    user_id=user_id,
                    learning_mode=data.get("learning_mode"),
                    retention_policy=data.get("retention_policy"),
                )
            if "paused" in data:
                updates["paused"] = plane.set_learning_paused(bool(data.get("paused")), user_id=user_id)
            if "opt_out" in data:
                updates["opt_out"] = plane.set_learning_opt_out(user_id, bool(data.get("opt_out")))

            if not updates:
                return {"success": False, "error": "No policy fields provided"}, 400
            return {"success": True, "user_id": user_id, "updates": updates}, 200

        @self.app.route("/api/v1/learning/opt-out", methods=["POST"])
        def learning_opt_out_endpoint() -> Tuple[Dict[str, Any], int]:
            from core.learning_control import get_learning_control_plane

            data = request.get_json() or {}
            user_id = str(data.get("user_id") or "local")
            opt_out = bool(data.get("opt_out", True))
            result = get_learning_control_plane().set_learning_opt_out(user_id, opt_out)
            return {"success": True, "user_id": user_id, "opt_out": opt_out, "policy": result}, 200

        @self.app.route("/api/v1/learning/user-data/delete", methods=["POST"])
        def learning_delete_user_data_endpoint() -> Tuple[Dict[str, Any], int]:
            from core.learning_control import get_learning_control_plane

            data = request.get_json() or {}
            user_id = str(data.get("user_id") or "local")
            result = get_learning_control_plane().delete_user_data(user_id)
            return {"success": True, "user_id": user_id, "result": result}, 200

        # Computer Use endpoints
        @self.app.route("/api/v1/computer_use/tasks", methods=["POST"])
        def start_computer_use_task() -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api

            data = request.get_json() or {}
            user_intent = data.get("user_intent", "")
            approval_level = data.get("approval_level", "CONFIRM")

            if not user_intent:
                return {"success": False, "error": "Missing user_intent"}, 400

            api = get_computer_use_api()
            result = self._run_async(api.start_task(user_intent, approval_level))
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/computer_use/tasks/<task_id>", methods=["GET"])
        def get_computer_use_task_status(task_id: str) -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api

            api = get_computer_use_api()
            result = self._run_async(api.get_task_status(task_id))
            status = 200 if result.get("success") else 404
            return result, status

        @self.app.route("/api/v1/computer_use/tasks/<task_id>/evidence", methods=["GET"])
        def get_computer_use_task_evidence(task_id: str) -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api

            api = get_computer_use_api()
            result = self._run_async(api.get_task_evidence(task_id))
            status = 200 if result.get("success") else 404
            return result, status

        @self.app.route("/api/v1/computer_use/tasks", methods=["GET"])
        def list_computer_use_tasks() -> Tuple[Dict[str, Any], int]:
            from api.computer_use_api import get_computer_use_api

            status_filter = request.args.get("status")
            limit = request.args.get("limit", 20, type=int)

            api = get_computer_use_api()
            result = self._run_async(api.list_tasks(status=status_filter, limit=limit))
            status = 200 if result.get("success") else 400
            return result, status

        # ControlPlane Integration Routes
        @self.app.route("/api/v1/computer_use/controlplane/tasks", methods=["POST"])
        def controlplane_start_task() -> Tuple[Dict[str, Any], int]:
            from api.computer_use_controlplane import get_computer_use_controlplane_api

            data = request.get_json() or {}
            user_intent = data.get("user_intent", "")
            approval_level = data.get("approval_level", "CONFIRM")
            session_id = data.get("session_id")

            api = get_computer_use_controlplane_api()
            result = self._run_async(api.start_task(
                user_intent=user_intent,
                approval_level=approval_level,
                session_id=session_id
            ))
            status = 200 if result.get("status") else 400
            return result, status

        @self.app.route("/api/v1/computer_use/controlplane/tasks", methods=["GET"])
        def controlplane_list_tasks() -> Tuple[Dict[str, Any], int]:
            from api.computer_use_controlplane import get_computer_use_controlplane_api

            limit = request.args.get("limit", 20, type=int)

            api = get_computer_use_controlplane_api()
            result = self._run_async(api.list_tasks(limit=limit))
            status = 200 if result.get("success") else 400
            return result, status

        @self.app.route("/api/v1/computer_use/controlplane/tasks/<task_id>", methods=["GET"])
        def controlplane_get_task_status(task_id: str) -> Tuple[Dict[str, Any], int]:
            from api.computer_use_controlplane import get_computer_use_controlplane_api

            api = get_computer_use_controlplane_api()
            result = self._run_async(api.get_task_status(task_id))
            status = 200 if "error" not in result else 404
            return result, status

        @self.app.route("/api/v1/computer_use/controlplane/tasks/<task_id>/cancel", methods=["POST"])
        def controlplane_cancel_task(task_id: str) -> Tuple[Dict[str, Any], int]:
            from api.computer_use_controlplane import get_computer_use_controlplane_api

            api = get_computer_use_controlplane_api()
            result = self._run_async(api.cancel_task(task_id))
            status = 200 if result.get("success") else 404
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
                    "learning_policy": "POST /api/v1/learning/policy",
                    "learning_opt_out": "POST /api/v1/learning/opt-out",
                    "learning_delete_user_data": "POST /api/v1/learning/user-data/delete",
                    "start_computer_use_task": "POST /api/v1/computer_use/tasks",
                    "get_task_status": "GET /api/v1/computer_use/tasks/<task_id>",
                    "get_task_evidence": "GET /api/v1/computer_use/tasks/<task_id>/evidence",
                    "list_tasks": "GET /api/v1/computer_use/tasks?status=*&limit=20",
                    "controlplane_start_task": "POST /api/v1/computer_use/controlplane/tasks",
                    "controlplane_list_tasks": "GET /api/v1/computer_use/controlplane/tasks?limit=20",
                    "controlplane_get_status": "GET /api/v1/computer_use/controlplane/tasks/<task_id>",
                    "controlplane_cancel_task": "POST /api/v1/computer_use/controlplane/tasks/<task_id>/cancel"
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
        try:
            if SOCKETIO_AVAILABLE and self.sio:
                # Use Socket.IO server with WebSocket support
                import logging as logging_module
                logging_module.getLogger('engineio').setLevel(logging_module.WARNING)
                logging_module.getLogger('socketio').setLevel(logging_module.WARNING)

                self.sio.run(self.app, host=self.host, port=self.port, debug=debug, use_reloader=False)
            else:
                # Fallback to plain Flask
                self.app.run(host=self.host, port=self.port, debug=debug, use_reloader=False)
        finally:
            self._shutdown_async_bridge()

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
