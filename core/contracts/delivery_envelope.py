from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DeliveryAttachment:
    path: str
    type: str = "file"
    name: str = ""
    mime: str = ""
    size_bytes: int = 0
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "name": self.name,
            "mime": self.mime,
            "size_bytes": int(self.size_bytes or 0),
            "sha256": self.sha256,
        }


@dataclass
class DeliveryEnvelope:
    status: str
    text_summary: str = ""
    attachments: list[DeliveryAttachment] = field(default_factory=list)
    artifact_manifest: list[dict[str, Any]] = field(default_factory=list)
    channel_payload: dict[str, Any] = field(default_factory=dict)
    fallback_payload: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "text_summary": self.text_summary,
            "attachments": [item.to_dict() for item in self.attachments],
            "artifact_manifest": list(self.artifact_manifest),
            "channel_payload": dict(self.channel_payload),
            "fallback_payload": dict(self.fallback_payload),
            "errors": list(self.errors),
        }


__all__ = ["DeliveryAttachment", "DeliveryEnvelope"]
