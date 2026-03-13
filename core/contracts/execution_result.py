from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _looks_like_file_path(value: str) -> bool:
    text = str(value or "").strip()
    if not text:
        return False
    if text.startswith(("http://", "https://")):
        return False
    return "/" in text or "\\" in text or "." in Path(text).name


def infer_artifact_type(path: str, explicit_type: str = "") -> str:
    declared = str(explicit_type or "").strip().lower()
    if declared in {"file", "image", "text", "directory"}:
        return declared
    if declared in {"dir", "folder"}:
        return "directory"
    suffix = Path(str(path or "")).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return "image"
    if suffix in {".md", ".txt", ".json", ".csv", ".html", ".xml"}:
        return "text"
    return "file"


@dataclass
class ArtifactRecord:
    path: str
    type: str = "file"
    name: str = ""
    mime: str = ""
    size_bytes: int = 0
    sha256: str = ""
    tool: str = ""
    source: str = "execution"
    source_result: Dict[str, Any] = field(default_factory=dict)
    evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "path": self.path,
            "type": self.type,
            "name": self.name,
            "mime": self.mime,
            "size_bytes": int(self.size_bytes or 0),
            "sha256": self.sha256,
            "tool": self.tool,
            "source": self.source,
        }
        if self.source_result:
            payload["source_result"] = dict(self.source_result)
        if self.evidence:
            payload["evidence"] = dict(self.evidence)
        return payload


@dataclass
class ToolResult:
    status: str
    message: str = ""
    artifacts: List[ArtifactRecord] = field(default_factory=list)
    evidence: List[Dict[str, Any]] = field(default_factory=list)
    data: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "message": self.message,
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "evidence": list(self.evidence),
            "data": dict(self.data),
            "errors": list(self.errors),
            "metrics": dict(self.metrics),
            "raw": self.raw,
        }


@dataclass
class ExecutionResult(ToolResult):
    pass


def _coerce_error_list(payload: Any) -> List[str]:
    if isinstance(payload, list):
        return [str(item).strip() for item in payload if str(item or "").strip()]
    if isinstance(payload, str):
        clean = payload.strip()
        return [clean] if clean else []
    return []


def _coerce_data_map(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return dict(payload)
    return {}


def _append_candidate(candidates: List[ArtifactRecord], value: Any, *, tool: str, source: str, source_result: Dict[str, Any]) -> None:
    if isinstance(value, str):
        path = value.strip()
        if path and _looks_like_file_path(path):
            candidates.append(
                ArtifactRecord(
                    path=path,
                    type=infer_artifact_type(path),
                    name=Path(path).name,
                    tool=tool,
                    source=source,
                    source_result=dict(source_result),
                )
            )
        return
    if not isinstance(value, dict):
        return
    path = str(value.get("path") or value.get("file_path") or value.get("output_path") or value.get("image_path") or "").strip()
    if not path or not _looks_like_file_path(path):
        return
    candidates.append(
        ArtifactRecord(
            path=path,
            type=infer_artifact_type(path, str(value.get("type") or "")),
            name=str(value.get("name") or Path(path).name),
            mime=str(value.get("mime") or ""),
            size_bytes=int(value.get("size_bytes") or 0),
            sha256=str(value.get("sha256") or ""),
            tool=tool,
            source=str(value.get("source") or source),
            source_result=dict(source_result),
            evidence=dict(value.get("evidence") or {}) if isinstance(value.get("evidence"), dict) else {},
        )
    )


def collect_artifacts(payload: Any, *, tool: str = "", source: str = "execution") -> List[ArtifactRecord]:
    candidates: List[ArtifactRecord] = []
    source_result = payload if isinstance(payload, dict) else {}

    if isinstance(payload, str):
        _append_candidate(candidates, payload, tool=tool, source=source, source_result={})
        return candidates

    if not isinstance(payload, dict):
        return candidates

    for key in ("path", "file_path", "output_path", "screenshot", "image_path"):
        _append_candidate(candidates, payload.get(key), tool=tool, source=source, source_result=source_result)

    proof = payload.get("_proof")
    if isinstance(proof, dict):
        _append_candidate(candidates, proof.get("screenshot"), tool=tool, source=source, source_result=source_result)

    for key in ("paths", "files", "artifacts", "outputs"):
        value = payload.get(key)
        if isinstance(value, list):
            for item in value:
                _append_candidate(candidates, item, tool=tool, source=source, source_result=source_result)

    nested_result = payload.get("result")
    if nested_result is not None and nested_result is not payload:
        nested_tool = str(payload.get("tool") or tool)
        for artifact in collect_artifacts(nested_result, tool=nested_tool, source=source):
            candidates.append(artifact)

    if isinstance(payload.get("artifacts"), list):
        for artifact in list(payload.get("artifacts") or []):
            _append_candidate(candidates, artifact, tool=tool, source=source, source_result=source_result)

    deduped: Dict[str, ArtifactRecord] = {}
    for artifact in candidates:
        key = str(artifact.path or "").strip()
        if not key:
            continue
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = artifact
            continue
        existing_score = (
            1 if existing.type != "file" else 0,
            1 if bool(existing.mime) else 0,
            1 if bool(existing.size_bytes) else 0,
            1 if bool(existing.sha256) else 0,
        )
        candidate_score = (
            1 if artifact.type != "file" else 0,
            1 if bool(artifact.mime) else 0,
            1 if bool(artifact.size_bytes) else 0,
            1 if bool(artifact.sha256) else 0,
        )
        if candidate_score > existing_score:
            deduped[key] = artifact
    return list(deduped.values())


def collect_evidence(payload: Any) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    if not isinstance(payload, dict):
        return evidence

    raw = payload.get("evidence")
    if isinstance(raw, dict) and raw:
        evidence.append(dict(raw))
    elif isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and item:
                evidence.append(dict(item))

    citation_map = payload.get("citation_map")
    if isinstance(citation_map, dict) and citation_map:
        evidence.append({"type": "citation_map", "entries": len(citation_map)})

    source_urls = payload.get("source_urls")
    if isinstance(source_urls, list) and source_urls:
        evidence.append({"type": "source_urls", "count": len([url for url in source_urls if str(url).strip()])})
    return evidence


def collect_metrics(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    metrics: Dict[str, Any] = {}
    for key in ("duration_ms", "bytes_written", "size_bytes", "status_code", "quality_score", "total", "healthy", "unhealthy"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            metrics[key] = value
    return metrics


def coerce_execution_result(payload: Any, *, tool: str = "", source: str = "execution") -> ExecutionResult:
    if isinstance(payload, ExecutionResult):
        return payload

    if isinstance(payload, str):
        return ExecutionResult(
            status="success",
            message=payload.strip(),
            artifacts=collect_artifacts(payload, tool=tool, source=source),
            data={},
            errors=[],
            raw=payload,
        )

    if isinstance(payload, dict):
        success_flag = payload.get("success")
        status = str(payload.get("status") or "").strip().lower()
        if not status:
            if success_flag is False:
                status = "failed"
            elif payload.get("partial") is True:
                status = "partial"
            else:
                status = "success"
        message = str(
            payload.get("message")
            or payload.get("summary")
            or payload.get("output")
            or payload.get("error")
            or ""
        ).strip()
        errors = _coerce_error_list(payload.get("errors"))
        if not errors:
            errors = _coerce_error_list(payload.get("error"))
        data = _coerce_data_map(payload.get("data"))
        return ExecutionResult(
            status=status,
            message=message,
            artifacts=collect_artifacts(payload, tool=tool, source=source),
            evidence=collect_evidence(payload),
            data=data,
            errors=errors,
            metrics=collect_metrics(payload),
            raw=payload,
        )

    return ExecutionResult(status="success", message=str(payload or "").strip(), data={}, errors=[], raw=payload)


__all__ = [
    "ArtifactRecord",
    "ExecutionResult",
    "ToolResult",
    "coerce_execution_result",
    "collect_artifacts",
    "infer_artifact_type",
]
