from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AttachmentRef:
    """Structured attachment reference for channel adapters."""

    path: str
    type: str = "file"
    mime: str = "application/octet-stream"
    name: str = ""
    sha256: str = ""
    size_bytes: int = 0
    source: str = "agent"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "type": self.type,
            "mime": self.mime,
            "name": self.name,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "source": self.source,
        }


@dataclass
class AgentResponse:
    """Backward-compatible structured response envelope for the agent."""

    run_id: str
    text: str
    attachments: List[AttachmentRef] = field(default_factory=list)
    evidence_manifest_path: str = ""
    status: str = "success"  # success | partial | failed
    error: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "text": self.text,
            "attachments": [a.to_dict() for a in self.attachments],
            "evidence_manifest_path": self.evidence_manifest_path,
            "status": self.status,
            "error": self.error,
            "metadata": self.metadata,
        }

    def to_unified_attachments(self) -> List[Dict[str, Any]]:
        return [a.to_dict() for a in self.attachments]
