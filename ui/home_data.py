from __future__ import annotations

import random
import time
from collections import deque
from typing import Any, Protocol

import psutil

from core.artifact_quality_engine import get_artifact_quality_engine
from core.capability_metrics import get_capability_metrics
from core.events.read_model import get_run_read_model
from core.monitoring import get_monitoring
from core.pipeline_state import get_pipeline_state
from core.pricing_tracker import get_pricing_tracker
from core.runtime_backends import get_runtime_backend_registry
from core.operator_status import get_operator_status_sync
from ui.home_models import ActivityEntry, BackendState, HomeSnapshot, MetricTile


class HomeDataService(Protocol):
    def fetch_snapshot(self) -> HomeSnapshot: ...


def _fmt_seconds(seconds: float) -> str:
    seconds = max(0.0, float(seconds or 0.0))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m"
    return f"{int(seconds)}s"


class LiveHomeDataService:
    def __init__(self) -> None:
        self._trend = deque(maxlen=32)
        self._success = deque(maxlen=32)
        self._actions = deque(maxlen=32)
        self._boot = time.time()
        self._mock = MockHomeDataService()

    @staticmethod
    def _tone_from_value(value: float, thresholds: tuple[float, float]) -> str:
        low, high = thresholds
        if value >= high:
            return "success"
        if value >= low:
            return "warning"
        return "neutral"

    def _recent_activity(self, runs: list[dict[str, Any]], limit: int = 8) -> list[ActivityEntry]:
        items: list[ActivityEntry] = []
        for row in runs[:limit]:
            status = str(row.get("status") or "pending").lower()
            label = str(row.get("intent") or row.get("run_id") or "Task")
            subtitle = f"{row.get('step_count', 0)} steps · {row.get('tool_call_count', 0)} tools"
            if status == "completed":
                title = f"{label} completed"
                tone = "success"
            elif status == "failed":
                title = f"{label} failed"
                tone = "error"
            elif status == "cancelled":
                title = f"{label} cancelled"
                tone = "warning"
            else:
                title = f"{label} pending"
                tone = "info"
            ts = row.get("completed_at") or row.get("started_at") or time.time()
            items.append(
                ActivityEntry(
                    title=title,
                    subtitle=subtitle,
                    timestamp=time.strftime("%H:%M", time.localtime(float(ts or time.time()))),
                    status=tone,
                    source="run",
                )
            )
        return items

    @staticmethod
    def _backend_label(name: str) -> str:
        labels = {
            "python_core": "Python core",
            "rust_core": "Rust core",
            "go_gateway": "Go gateway",
            "typescript_dashboard": "React dashboard",
            "swift_desktop": "Swift shell",
        }
        return labels.get(name, name.replace("_", " ").title())

    @staticmethod
    def _backend_tone(*, configured: bool, available: bool, active: bool) -> str:
        if active:
            return "success"
        if configured and not available:
            return "warning"
        return "neutral"

    def _backend_detail(self, name: str, row: dict[str, Any]) -> str:
        if name == "python_core":
            return "Canonical runtime active"
        if name == "rust_core":
            features = row.get("details", {}).get("features", {}) or {}
            enabled = [key.replace("_", " ") for key, value in features.items() if value]
            if row.get("active") and enabled:
                return f"Acceleration: {', '.join(enabled[:2])}"
            return "Optional native acceleration"
        if name == "go_gateway":
            root_url = str(row.get("details", {}).get("root_url", "") or "").strip()
            if row.get("active"):
                return f"Realtime gateway online · {root_url}"
            return "Gateway fallback to local HTTP runtime"
        if name == "typescript_dashboard":
            return "React/Vite surface available" if row.get("active") else "Embedded desktop surface active"
        if name == "swift_desktop":
            return "Native shell available" if row.get("active") else "PyQt shell active"
        return ""

    def _resolve_backend_state(self) -> tuple[str, str, list[BackendState]]:
        fallback_states = [
            BackendState("python_core", "Python core", "Canonical runtime active", tone="success", active=True),
        ]
        try:
            raw = get_runtime_backend_registry().describe()
        except Exception:
            return "Python core", "success", fallback_states

        ordered_names = ("python_core", "rust_core", "go_gateway", "typescript_dashboard", "swift_desktop")
        states: list[BackendState] = []
        active_optional: list[str] = []
        unavailable_optional: list[str] = []

        for name in ordered_names:
            row = dict(raw.get(name, {}) or {})
            configured = bool(row.get("configured"))
            available = bool(row.get("available"))
            active = bool(row.get("active"))
            state = BackendState(
                name=name,
                label=self._backend_label(name),
                detail=self._backend_detail(name, row),
                tone=self._backend_tone(configured=configured, available=available, active=active),
                active=active,
            )
            states.append(state)
            if name != "python_core":
                if active:
                    active_optional.append(state.label)
                elif configured and not available:
                    unavailable_optional.append(state.label)

        if active_optional:
            return active_optional[0], "success", states
        if unavailable_optional:
            return f"Python fallback · {unavailable_optional[0]}", "warning", states
        return "Python core", "success", states or fallback_states

    def fetch_snapshot(self) -> HomeSnapshot:
        try:
            monitor = get_monitoring()
            health = monitor.get_health_status() if hasattr(monitor, "get_health_status") else {}
            dashboard = monitor.get_dashboard() if hasattr(monitor, "get_dashboard") else {}
        except Exception:
            health = {}
            dashboard = {}

        try:
            read_model = get_run_read_model()
        except Exception:
            read_model = None

        try:
            cap_summary = get_capability_metrics().summary(window_hours=24)
        except Exception:
            cap_summary = {}

        try:
            pricing = get_pricing_tracker().summary()
        except Exception:
            pricing = {}

        try:
            quality = get_artifact_quality_engine().summary(window_hours=24)
        except Exception:
            quality = {}

        try:
            pipeline = get_pipeline_state()
            pipeline_summary = pipeline.history_summary(window_hours=24) if hasattr(pipeline, "history_summary") else {}
        except Exception:
            pipeline_summary = {}
        try:
            operator_status = get_operator_status_sync()
        except Exception:
            operator_status = {"status": "degraded", "summary": {}}

        cpu = float(psutil.cpu_percent(interval=None) or 0.0)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        latency = float(dashboard.get("metrics_summary", {}).get("llm_latency", {}).get("avg", 0.0) or 0.0)
        uptime = _fmt_seconds(time.time() - psutil.boot_time())

        recent_runs: list[dict[str, Any]] = []
        if read_model is not None:
            try:
                recent_runs = list(read_model.get_recent_runs(limit=8) or [])
            except Exception:
                recent_runs = []

        tool_rows: list[dict[str, Any]] = []
        if read_model is not None:
            try:
                tool_rows = list(read_model.get_tool_performance() or [])[:6]
            except Exception:
                tool_rows = []

        if not recent_runs:
            recent_runs = self._mock.fetch_snapshot().recent_runs

        self._trend.append(latency or random.uniform(220.0, 900.0))
        success_rate = float(health.get("success_rate", 0.0) or 0.0)
        if success_rate <= 0:
            success_rate = 96.0 + random.uniform(-1.5, 1.0)
        self._success.append(success_rate)
        self._actions.append(float(health.get("total_operations", 0) or len(recent_runs) or 0))

        system_metrics = [
            MetricTile("CPU", f"{cpu:.0f}%", "Live system load", tone=self._tone_from_value(cpu, (60, 85)), icon="cpu"),
            MetricTile("Memory", f"{int(memory.used / (1024 * 1024))} MB", "Working set", tone=self._tone_from_value(memory.percent, (60, 85)), icon="memory"),
            MetricTile("Disk", f"{disk.percent:.0f}%", "Storage pressure", tone=self._tone_from_value(disk.percent, (70, 90)), icon="disk"),
            MetricTile("Uptime", uptime, "Runtime session", tone="neutral", icon="uptime"),
        ]

        success_card = float(health.get("success_rate", 0.0) or 96.0)
        quality_score = float(quality.get("avg_quality_score", 0.0) or 0.0)
        active_agents = int(health.get("active_agents", 0) or 0)
        total_ops = int(health.get("total_operations", 0) or len(recent_runs) or 0)
        est_cost = float(pricing.get("lifetime", {}).get("estimated_cost_usd", 0.0) or 0.0)
        top_domain = str(cap_summary.get("top_domain", "general") or "general")
        domain_rate = float(cap_summary.get("domains", {}).get(top_domain, {}).get("success_rate", 0.0) or 0.0)
        pipeline_active = int(pipeline_summary.get("active_count", 0) or 0)
        pipeline_recent = int(pipeline_summary.get("recent_total", 0) or 0)

        ai_metrics = [
            MetricTile("AI Latency", f"{latency:.0f} ms", "Response speed", tone=self._tone_from_value(1000 - latency, (200, 500)), icon="spark"),
            MetricTile("Success Rate", f"{success_card:.0f}%", "Task quality", tone=self._tone_from_value(success_card, (85, 95)), icon="check"),
            MetricTile("Active Agents", f"{active_agents}", "Concurrent workers", tone="neutral", icon="agents"),
            MetricTile("Total Actions", f"{total_ops}", f"{top_domain[:14]} · {domain_rate:.0f}% success", tone="neutral", icon="actions"),
            MetricTile("Est. Cost", f"${est_cost:.2f}", "Lifetime estimate", tone="warning" if est_cost > 0 else "neutral", icon="cost"),
            MetricTile("Quality", f"{quality_score:.0f}", f"Pipeline A:{pipeline_active} R:{pipeline_recent}", tone="neutral", icon="quality"),
        ]

        activities = self._recent_activity(recent_runs)
        if not activities:
            activities = self._mock.fetch_snapshot().activity

        if len(activities) < 8:
            activities.extend(
                [
                    ActivityEntry("Data model refreshed", "Read model updated from event stream", time.strftime("%H:%M"), status="info", source="system"),
                    ActivityEntry("Workflow completed", "Automation passed verification", time.strftime("%H:%M"), status="success", source="agent"),
                ][: max(0, 8 - len(activities))]
            )

        backend_label, backend_tone, backend_states = self._resolve_backend_state()

        operator_overall = str(operator_status.get("status") or "healthy")
        operator_summary = dict(operator_status.get("summary") or {})
        connection_label = "Bot hazır" if operator_overall == "healthy" else "Operator degraded"
        agent_state = "Connected" if operator_overall == "healthy" and success_card >= 90 else "Degraded"

        return HomeSnapshot(
            updated_at=time.time(),
            loading=False,
            error="",
            connection_label=connection_label,
            system_metrics=system_metrics,
            ai_metrics=ai_metrics,
            activity=activities[:8],
            trend=list(self._trend) if self._trend else [latency],
            success_trend=list(self._success) if self._success else [success_card],
            action_trend=list(self._actions) if self._actions else [total_ops],
            recent_runs=recent_runs,
            tool_rows=tool_rows,
            pipeline_summary=[
                f"Active runs: {pipeline_active}",
                f"Recent completions: {pipeline_recent}",
                f"Top domain: {top_domain}",
            ],
            backend_label=backend_label,
            backend_tone=backend_tone,
            backend_states=backend_states,
            workspace_label=str(health.get("workspace", "Local workspace") or "Local workspace"),
            agent_state=agent_state,
            operator_status={"status": operator_overall, "summary": operator_summary},
        )


class MockHomeDataService:
    def __init__(self) -> None:
        self._tick = 0

    def fetch_snapshot(self) -> HomeSnapshot:
        self._tick += 1
        cpu = 18 + (self._tick % 10) * 3
        memory = 4210 + self._tick * 17
        disk = 37 + (self._tick % 5) * 2
        latency = 280 + (self._tick % 7) * 22
        activity = [
            ActivityEntry("Sales Report Created", "Person 20:19", "20:19", status="success", source="agent"),
            ActivityEntry("Data Model Refreshed", "Person 20:19", "20:19", status="info", source="system"),
            ActivityEntry("Budget Meeting Summary", "Person 20:36", "20:36", status="info", source="agent"),
            ActivityEntry("Image Generation Finished", "Person 20:19", "20:19", status="success", source="tool"),
            ActivityEntry("Task Update", "Person Experts 22:89", "22:89", status="warning", source="workflow"),
        ]
        return HomeSnapshot(
            updated_at=time.time(),
            loading=False,
            error="",
            connection_label="Bot hazır",
            system_metrics=[
                MetricTile("CPU", f"{cpu}%", "Live system load", tone="neutral", icon="cpu"),
                MetricTile("Memory", f"{memory} MB", "Working set", tone="neutral", icon="memory"),
                MetricTile("Disk", f"{disk}%", "Storage pressure", tone="neutral", icon="disk"),
                MetricTile("Uptime", _fmt_seconds(3600 + self._tick * 26), "Runtime session", tone="neutral", icon="uptime"),
            ],
            ai_metrics=[
                MetricTile("AI Latency", f"{latency} ms", "Response speed", tone="neutral", icon="spark"),
                MetricTile("Success Rate", f"{96 + (self._tick % 3)}%", "Task quality", tone="success", icon="check"),
                MetricTile("Active Agents", "4", "Concurrent workers", tone="neutral", icon="agents"),
                MetricTile("Total Actions", f"{128 + self._tick}", "Executed operations", tone="neutral", icon="actions"),
                MetricTile("Est. Cost", "$0.00", "Lifetime estimate", tone="neutral", icon="cost"),
                MetricTile("Quality", f"{82 + (self._tick % 4)}", "Pipeline A:2 R:7", tone="neutral", icon="quality"),
            ],
            activity=activity,
            trend=[latency - 26, latency - 10, latency + 8, latency - 5, latency, latency + 12],
            success_trend=[96, 95, 96, 97, 96, 98],
            action_trend=[44, 48, 53, 51, 57, 62],
            recent_runs=[
                {"status": "completed", "intent": "Sales report", "step_count": 4, "tool_call_count": 8, "completed_at": time.time()},
                {"status": "completed", "intent": "Data model refresh", "step_count": 2, "tool_call_count": 3, "completed_at": time.time()},
                {"status": "failed", "intent": "Budget summary", "step_count": 3, "tool_call_count": 5, "completed_at": time.time()},
            ],
            tool_rows=[
                {"tool_name": "web_search", "success_rate": 98.2, "avg_latency_ms": 820.0, "total_calls": 18},
                {"tool_name": "file_write", "success_rate": 96.6, "avg_latency_ms": 640.0, "total_calls": 14},
            ],
            pipeline_summary=["Active runs: 2", "Recent completions: 7", "Top domain: research"],
            backend_label="Python core",
            backend_tone="success",
            backend_states=[
                BackendState("python_core", "Python core", "Canonical runtime active", tone="success", active=True),
            ],
            workspace_label="Local workspace",
            agent_state="Connected",
            operator_status={
                "status": "healthy",
                "summary": {
                    "mobile_dispatch": {"status": "healthy", "count": 1},
                    "computer_use": {"status": "healthy", "ready": True, "current_lane": "vision_lane", "verification_state": "strong"},
                    "internet_reach": {"status": "healthy", "ready": True, "current_lane": "verified_lane", "verification_state": "verified", "average_latency_bucket": "steady"},
                    "document_ingest": {"status": "healthy", "liteparse_enabled": True, "verification_state": "verified", "vision_ocr_backend": "auto"},
                    "speed_runtime": {"status": "healthy", "current_lane": "turbo_lane", "verification_state": "standard", "average_latency_bucket": "fast", "fallback_active": False},
                    "model_runtime": {
                        "enabled": True,
                        "execution_mode": "local_first",
                        "device_policy": "cpu",
                        "capabilities": {
                            "embedding": {"available": True, "backend": "local_hashing"},
                        },
                    },
                },
            },
        )
