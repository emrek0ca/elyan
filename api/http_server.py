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

        # Enable CORS
        try:
            from flask_cors import CORS
            CORS(self.app)
        except ImportError:
            logger.warning("CORS not available - install flask-cors for cross-origin requests")

        self._setup_routes()

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
                    "available_metrics": "GET /api/v1/metrics/available"
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
        self.app.run(host=self.host, port=self.port, debug=debug, use_reloader=False)

    @require_flask
    def start_background(self) -> None:
        """Start server in background thread"""
        import threading

        def run_server():
            self.run(debug=False)

        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        logger.info(f"Dashboard HTTP Server started in background on {self.host}:{self.port}")


def create_server(host: str = "127.0.0.1", port: int = 5000, debug: bool = False) -> Optional[DashboardHTTPServer]:
    """Create and return a dashboard HTTP server"""
    try:
        return DashboardHTTPServer(host=host, port=port, debug=debug)
    except RuntimeError as e:
        logger.error(f"Cannot create HTTP server: {e}")
        return None
