"""
Dashboard API CLI commands - Phase 5-3

Commands:
- dashboard-api start: Start the HTTP server
- dashboard-api status: Check API status
- dashboard-api metrics: Show available metrics
"""

import subprocess
import sys
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


def start_server(args) -> Dict[str, Any]:
    """Start dashboard API server"""
    try:
        import flask
    except ImportError:
        return {
            "success": False,
            "error": "Flask required. Install with: pip install flask flask-cors"
        }

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 5000)
    debug = getattr(args, "debug", False)

    try:
        from api.http_server import DashboardHTTPServer

        server = DashboardHTTPServer(host=host, port=port, debug=debug)

        print(f"""
╭─────────────────────────────────────────────────────────────────╮
│ Dashboard API Server Starting                                   │
├─────────────────────────────────────────────────────────────────┤
│ Host:           {host}
│ Port:           {port}
│ Debug:          {debug}
├─────────────────────────────────────────────────────────────────┤
│ API Documentation:  http://{host}:{port}/api/v1/docs
│ Health Check:       http://{host}:{port}/health
│
│ Endpoints:
│   • GET /api/v1/cognitive/state
│   • GET /api/v1/predictions/errors
│   • GET /api/v1/deadlock/stats
│   • GET /api/v1/deadlock/timeline?hours=24
│   • GET /api/v1/sleep/consolidation
│   • GET /api/v1/cache/performance
│   • GET /api/v1/metrics/history?name=<metric>&limit=100
│   • GET /api/v1/metrics/summary?name=<metric>
│   • GET /api/v1/metrics/available
│
│ Press Ctrl+C to stop
╰─────────────────────────────────────────────────────────────────╯
""")

        server.run(debug=debug)

        return {"success": True, "message": "Server started"}

    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def check_status(args) -> Dict[str, Any]:
    """Check API server status"""
    try:
        import requests
    except ImportError:
        return {
            "success": False,
            "error": "requests library required. Install with: pip install requests"
        }

    host = getattr(args, "host", "127.0.0.1")
    port = getattr(args, "port", 5000)

    try:
        response = requests.get(f"http://{host}:{port}/health", timeout=2)

        if response.status_code == 200:
            data = response.json()
            return {
                "success": True,
                "status": data.get("status"),
                "service": data.get("service"),
                "timestamp": data.get("timestamp")
            }
        else:
            return {
                "success": False,
                "error": f"Server returned status {response.status_code}"
            }

    except requests.exceptions.ConnectionError:
        return {
            "success": False,
            "error": f"Could not connect to API server at {host}:{port}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e)
        }


def show_metrics(args) -> Dict[str, Any]:
    """Show available metrics"""
    try:
        from api.dashboard_api import get_dashboard_api

        api = get_dashboard_api()
        result = api.list_available_metrics()

        if result["success"]:
            print(f"\nAvailable Metrics ({result['count']} total):\n")
            for i, metric in enumerate(result["metrics"], 1):
                print(f"  {i:2d}. {metric}")

            if result["metrics"]:
                print(f"\nUsage: elyan dashboard-api metrics <metric-name>")
            return result
        else:
            return result

    except Exception as e:
        logger.error(f"Failed to get metrics: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def show_metric_data(args) -> Dict[str, Any]:
    """Show specific metric data"""
    metric_name = getattr(args, "metric_name", None)

    if not metric_name:
        return {
            "success": False,
            "error": "Metric name required"
        }

    try:
        from api.dashboard_api import get_dashboard_api

        api = get_dashboard_api()
        summary = api.get_metrics_summary(metric_name)

        if summary["success"]:
            data = summary["data"]
            print(f"\nMetric: {metric_name}")
            print(f"  Count:  {data['count']}")
            print(f"  Min:    {data['min']:.2f}")
            print(f"  Max:    {data['max']:.2f}")
            print(f"  Avg:    {data['avg']:.2f}")
            print(f"  Latest: {data['latest']:.2f}\n")

            return summary
        else:
            return summary

    except Exception as e:
        logger.error(f"Failed to get metric data: {e}")
        return {
            "success": False,
            "error": str(e)
        }


def handle_dashboard_api_command(args) -> Dict[str, Any]:
    """Main handler for dashboard-api commands"""
    subcommand = getattr(args, "subcommand", None)

    if subcommand == "start":
        return start_server(args)
    elif subcommand == "status":
        return check_status(args)
    elif subcommand == "metrics":
        if hasattr(args, "metric_name") and args.metric_name:
            return show_metric_data(args)
        else:
            return show_metrics(args)
    else:
        return {
            "success": False,
            "error": f"Unknown subcommand: {subcommand}"
        }
