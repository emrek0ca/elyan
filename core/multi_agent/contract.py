"""
core/multi_agent/contract.py
─────────────────────────────────────────────────────────────────────────────
Deliverable Contract & Quality Gate Definitions.
Ensures agents follow a strict protocol and deliverables are complete.
"""

from __future__ import annotations
import json
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from pathlib import Path
import hashlib

@dataclass
class Artifact:
    path: str
    type: str  # 'html', 'css', 'js', 'image', 'code'
    mime: str = "text/plain"
    content: Optional[str] = None
    expected_size: int = 0
    actual_size: int = 0
    expected_sha256: Optional[str] = None
    actual_sha256: Optional[str] = None
    status: str = "pending" # pending, written, verified, failed
    validation_layers: List[str] = field(default_factory=list) # static, runtime, visual
    errors: List[str] = field(default_factory=list)
    # Strict Contract Fields
    required_sections: List[str] = field(default_factory=list)
    min_size_bytes: int = 0
    asset_source: str = "local" # local, remote
    encoding: str = "utf-8"
    line_endings: str = "LF"

    def calculate_sha256(self):
        if self.content:
            return hashlib.sha256(self.content.encode(self.encoding)).hexdigest()
        return None

    def to_artifact_map_entry(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "content": self.content,
            "mime": self.mime,
            "sha256": self.expected_sha256 or self.calculate_sha256(),
            "size_estimate": self.expected_size,
            "type": self.type,
            "encoding": self.encoding,
            "line_endings": self.line_endings,
        }

@dataclass
class JobMetrics:
    task_success_rate: float = 0.0
    tool_correctness: float = 1.0
    output_completeness: float = 0.0
    token_usage: int = 0
    duration_s: float = 0.0

@dataclass
class DeliverableContract:
    job_id: str
    goal: str
    job_type: str = "generic" # web_site, research, etc.
    artifacts: Dict[str, Artifact] = field(default_factory=dict)
    metrics: JobMetrics = field(default_factory=JobMetrics)
    audit_bundle_path: Optional[str] = None
    status: str = "open"
    contract_schema_version: str = "2.0"
    
    def add_artifact(self, path: str, type: str, content: str = None, mime: str = "text/plain", **kwargs):
        art = Artifact(
            path=path, 
            type=type, 
            content=content, 
            mime=mime,
            expected_size=len(content.encode("utf-8")) if content else 0
        )
        for k, v in kwargs.items():
            if hasattr(art, k):
                setattr(art, k, v)
                
        if content:
            art.expected_sha256 = art.calculate_sha256()
        self.artifacts[path] = art

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

    def to_artifact_map(self) -> Dict[str, Any]:
        """Returns the fully typed artifact map for the job."""
        return {
            path: artifact.to_artifact_map_entry() 
            for path, artifact in self.artifacts.items()
        }

    @staticmethod
    def get_contract_schema() -> Dict[str, Any]:
        """Returns the strict JSON schema required for returning an ArtifactMap."""
        return {
            "type": "object",
            "properties": {
                "artifacts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "Absolute file path"},
                            "type": {"type": "string", "enum": ["html", "css", "js", "image", "code", "document"]},
                            "mime": {"type": "string"},
                            "content": {"type": "string"},
                            "required_sections": {"type": "array", "items": {"type": "string"}},
                            "min_size_bytes": {"type": "integer"},
                            "asset_source": {"type": "string", "enum": ["local", "remote"]},
                            "encoding": {"type": "string", "default": "utf-8"},
                            "line_endings": {"type": "string", "default": "LF"}
                        },
                        "required": ["path", "type", "content"]
                    }
                }
            },
            "required": ["artifacts"]
        }
