from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MetricTile:
    label: str
    value: str
    hint: str = ""
    delta: str = ""
    tone: str = "neutral"
    icon: str = ""


@dataclass(slots=True)
class ActivityEntry:
    title: str
    subtitle: str
    timestamp: str
    status: str = "info"
    source: str = "system"
    icon: str = "dot"


@dataclass(slots=True)
class TrendSeries:
    label: str
    points: list[float] = field(default_factory=list)
    color: str = "#4C82FF"


@dataclass(slots=True)
class BackendState:
    name: str
    label: str
    detail: str = ""
    tone: str = "neutral"
    active: bool = False


@dataclass(slots=True)
class HomeSnapshot:
    updated_at: float = 0.0
    loading: bool = False
    error: str = ""
    connection_label: str = "Bot hazır"
    system_metrics: list[MetricTile] = field(default_factory=list)
    ai_metrics: list[MetricTile] = field(default_factory=list)
    activity: list[ActivityEntry] = field(default_factory=list)
    trend: list[float] = field(default_factory=list)
    success_trend: list[float] = field(default_factory=list)
    action_trend: list[float] = field(default_factory=list)
    recent_runs: list[dict[str, Any]] = field(default_factory=list)
    tool_rows: list[dict[str, Any]] = field(default_factory=list)
    pipeline_summary: list[str] = field(default_factory=list)
    backend_label: str = "Python core"
    backend_tone: str = "neutral"
    backend_states: list[BackendState] = field(default_factory=list)
    workspace_label: str = "Local workspace"
    agent_state: str = "Connected"
    operator_status: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def empty(cls) -> "HomeSnapshot":
        return cls(
            system_metrics=[
                MetricTile("CPU", "0%", "Live system load", tone="neutral", icon="cpu"),
                MetricTile("Memory", "0 MB", "Resident usage", tone="neutral", icon="memory"),
                MetricTile("Disk", "0%", "Storage pressure", tone="neutral", icon="disk"),
                MetricTile("Latency", "0 ms", "Network / tool latency", tone="neutral", icon="latency"),
            ],
            ai_metrics=[
                MetricTile("AI Latency", "0 ms", "Response speed", tone="neutral", icon="spark"),
                MetricTile("Success Rate", "100%", "Task quality", tone="success", icon="check"),
                MetricTile("Active Agents", "0", "Running workers", tone="neutral", icon="agents"),
                MetricTile("Total Actions", "0", "Executed operations", tone="neutral", icon="actions"),
            ],
            activity=[
                ActivityEntry("System booted", "Waiting for the first live signal", "now", status="info", source="system"),
            ],
            backend_label="Python core",
            backend_tone="success",
            backend_states=[
                BackendState("python_core", "Python core", "Agent runtime active", tone="success", active=True),
            ],
            operator_status={
                "status": "healthy",
                "summary": {
                    "mobile_dispatch": {"status": "healthy"},
                    "computer_use": {"status": "healthy"},
                    "internet_reach": {"status": "healthy"},
                    "document_ingest": {"status": "healthy"},
                    "speed_runtime": {"status": "healthy", "current_lane": "turbo_lane", "verification_state": "standard"},
                },
            },
        )
