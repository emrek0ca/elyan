from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class OperatorAttachment:
    path: str
    type: str = "file"
    mime: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "mime": self.mime,
            "metadata": dict(self.metadata),
        }


@dataclass
class OperatorRequest:
    request_id: str
    host: str
    channel: str
    user_id: str
    machine_id: str
    input_text: str
    attachments: list[OperatorAttachment] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)
    safety_mode: str = "balanced_supervised"
    delivery_preferences: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "host": self.host,
            "channel": self.channel,
            "user_id": self.user_id,
            "machine_id": self.machine_id,
            "input_text": self.input_text,
            "attachments": [item.to_dict() for item in self.attachments],
            "constraints": dict(self.constraints),
            "safety_mode": self.safety_mode,
            "delivery_preferences": dict(self.delivery_preferences),
        }


@dataclass
class CapabilitySelection:
    capability: str
    workflow_id: str
    confidence: float
    extracted_params: dict[str, Any] = field(default_factory=dict)
    missing_params: list[str] = field(default_factory=list)
    routing_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "workflow_id": self.workflow_id,
            "confidence": float(self.confidence),
            "extracted_params": dict(self.extracted_params),
            "missing_params": list(self.missing_params),
            "routing_reason": self.routing_reason,
        }


@dataclass
class UserProfile:
    preferred_output_formats: list[str] = field(default_factory=list)
    style_preferences: dict[str, Any] = field(default_factory=dict)
    task_patterns: list[dict[str, Any]] = field(default_factory=list)
    capability_affinities: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    last_updated: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "preferred_output_formats": list(self.preferred_output_formats),
            "style_preferences": dict(self.style_preferences),
            "task_patterns": list(self.task_patterns),
            "capability_affinities": dict(self.capability_affinities),
            "confidence": float(self.confidence),
            "last_updated": float(self.last_updated or 0.0),
        }


__all__ = ["CapabilitySelection", "OperatorAttachment", "OperatorRequest", "UserProfile"]
