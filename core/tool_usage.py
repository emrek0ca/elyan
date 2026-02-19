"""
Tool usage telemetry for runtime insights and dashboard analytics.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Dict, Any

_lock = threading.Lock()
_MAX_EVENTS = 300
_events = deque(maxlen=_MAX_EVENTS)
_stats: Dict[str, Dict[str, Any]] = {}


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def record_tool_usage(
    tool_name: str,
    *,
    success: bool,
    latency_ms: int,
    source: str = "agent",
    error: str = "",
) -> None:
    tool = str(tool_name or "").strip() or "unknown"
    lat = max(0, int(latency_ms or 0))
    event = {
        "tool": tool,
        "success": bool(success),
        "latency_ms": lat,
        "source": source,
        "error": (error or "")[:180],
        "ts": _now_iso(),
    }
    with _lock:
        _events.append(event)
        row = _stats.setdefault(
            tool,
            {
                "calls": 0,
                "success": 0,
                "failure": 0,
                "last_latency_ms": 0,
                "avg_latency_ms": 0.0,
                "last_success": None,
                "last_error": "",
                "last_used_at": "",
            },
        )
        row["calls"] += 1
        if success:
            row["success"] += 1
            row["last_error"] = ""
        else:
            row["failure"] += 1
            row["last_error"] = (error or "")[:180]
        row["last_latency_ms"] = lat
        # Rolling average
        n = row["calls"]
        row["avg_latency_ms"] = ((row["avg_latency_ms"] * (n - 1)) + lat) / max(1, n)
        row["last_success"] = bool(success)
        row["last_used_at"] = event["ts"]


def get_tool_usage_snapshot() -> Dict[str, Any]:
    with _lock:
        stats = {}
        for name, row in _stats.items():
            calls = int(row.get("calls", 0) or 0)
            succ = int(row.get("success", 0) or 0)
            stats[name] = {
                **row,
                "success_rate": round((succ / calls) * 100.0, 2) if calls else 0.0,
                "avg_latency_ms": round(float(row.get("avg_latency_ms", 0.0)), 2),
            }
        return {
            "stats": stats,
            "recent_events": list(_events),
            "total_calls": sum(int(v.get("calls", 0) or 0) for v in _stats.values()),
        }


def reset_tool_usage() -> None:
    with _lock:
        _events.clear()
        _stats.clear()
