from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class TelemetryEvent:
    event: str
    request_id: str
    machine_id: str = ""
    selected_capability: str = ""
    workflow_path: list[str] = field(default_factory=list)
    extracted_params: dict[str, Any] = field(default_factory=dict)
    tool_name: str = ""
    status: str = ""
    latency_ms: int = 0
    memory_mb: float = 0.0
    retry_count: int = 0
    payload: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "event": self.event,
            "request_id": self.request_id,
            "machine_id": self.machine_id,
            "selected_capability": self.selected_capability,
            "workflow_path": list(self.workflow_path),
            "extracted_params": dict(self.extracted_params),
            "tool_name": self.tool_name,
            "status": self.status,
            "latency_ms": int(self.latency_ms or 0),
            "memory_mb": float(self.memory_mb or 0.0),
            "retry_count": int(self.retry_count or 0),
            "payload": dict(self.payload),
            "ts": float(self.ts),
        }


__all__ = ["TelemetryEvent"]
