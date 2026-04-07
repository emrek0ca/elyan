from __future__ import annotations

import hashlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from core.db import Repository, get_db_manager
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _sha256_for_path(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8192)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


@dataclass
class ProjectBrief:
    project_id: str
    workspace_id: str = "local-workspace"
    title: str = ""
    objective: str = ""
    root_path: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProjectArtifact:
    artifact_id: str
    project_id: str
    phase: str
    artifact_type: str
    file_path: str = ""
    sha256: str = ""
    manifest: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)


@dataclass
class ExecutionEvidence:
    evidence_id: str
    project_id: str
    phase: str
    status: str
    details: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_now)


class ProjectRunner:
    def __init__(self, base_path: str | Path | None = None) -> None:
        root = Path(base_path or (resolve_elyan_data_dir() / "projects")).expanduser()
        root.mkdir(parents=True, exist_ok=True)
        self.base_path = root
        self.repo = Repository(get_db_manager())

    def _project_dir(self, project_id: str) -> Path:
        path = self.base_path / str(project_id or "project")
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _write_json(self, target: Path, payload: dict[str, Any]) -> str:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return str(target)

    def _store_manifest(self, artifact: ProjectArtifact) -> None:
        self.repo.execute(
            """
            INSERT OR REPLACE INTO artifact_manifests(
                artifact_id, project_id, phase, artifact_type, file_path, sha256, manifest_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id,
                artifact.project_id,
                artifact.phase,
                artifact.artifact_type,
                artifact.file_path,
                artifact.sha256,
                json.dumps(dict(artifact.manifest or {}), sort_keys=True),
                float(artifact.created_at or _now()),
                _now(),
            ),
        )

    def scan(self, brief: ProjectBrief) -> dict[str, Any]:
        project_dir = self._project_dir(brief.project_id)
        payload = {"brief": asdict(brief), "phase": "scan", "created_at": _now()}
        path = self._write_json(project_dir / "scan.json", payload)
        return {"ok": True, "phase": "scan", "path": path, "project_id": brief.project_id}

    def plan(self, brief: ProjectBrief, *, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        project_dir = self._project_dir(brief.project_id)
        payload = {"brief": asdict(brief), "inputs": dict(inputs or {}), "phase": "plan", "created_at": _now()}
        path = self._write_json(project_dir / "plan.json", payload)
        return {"ok": True, "phase": "plan", "path": path, "project_id": brief.project_id}

    def scaffold(self, brief: ProjectBrief, *, artifact_type: str = "manifest", file_path: str = "", manifest: dict[str, Any] | None = None) -> dict[str, Any]:
        project_dir = self._project_dir(brief.project_id)
        resolved_file = Path(file_path).expanduser() if file_path else Path("")
        sha256 = _sha256_for_path(resolved_file) if file_path else ""
        artifact = ProjectArtifact(
            artifact_id=f"artifact_{brief.project_id}_{int(_now() * 1000)}",
            project_id=brief.project_id,
            phase="scaffold",
            artifact_type=str(artifact_type or "manifest"),
            file_path=str(resolved_file) if file_path else "",
            sha256=sha256,
            manifest=dict(manifest or {}),
        )
        self._store_manifest(artifact)
        path = self._write_json(project_dir / "scaffold.json", {"artifact": asdict(artifact), "created_at": _now()})
        return {"ok": True, "phase": "scaffold", "path": path, "artifact": asdict(artifact)}

    def verify(self, artifact: ProjectArtifact) -> dict[str, Any]:
        exists = True
        if artifact.file_path:
            path = Path(artifact.file_path).expanduser()
            exists = path.exists()
            current_hash = _sha256_for_path(path) if exists else ""
            ok = exists and (not artifact.sha256 or artifact.sha256 == current_hash)
        else:
            ok = bool(artifact.manifest)
            current_hash = str(artifact.manifest.get("sha256") or "")
        evidence = ExecutionEvidence(
            evidence_id=f"evidence_{artifact.project_id}_{int(_now() * 1000)}",
            project_id=artifact.project_id,
            phase="verify",
            status="ok" if ok else "failed",
            details={"artifact_id": artifact.artifact_id, "exists": exists, "sha256": current_hash},
        )
        self._write_json(self._project_dir(artifact.project_id) / "verify.json", {"evidence": asdict(evidence)})
        return {"ok": ok, "phase": "verify", "evidence": asdict(evidence)}

    def deliver(self, brief: ProjectBrief, *, artifacts: list[ProjectArtifact] | None = None) -> dict[str, Any]:
        payload = {
            "brief": asdict(brief),
            "artifacts": [asdict(item) for item in (artifacts or [])],
            "phase": "deliver",
            "created_at": _now(),
        }
        path = self._write_json(self._project_dir(brief.project_id) / "deliver.json", payload)
        return {"ok": True, "phase": "deliver", "path": path}


_project_runner: ProjectRunner | None = None


def get_project_runner(base_path: str | Path | None = None) -> ProjectRunner:
    global _project_runner
    if base_path is not None:
        return ProjectRunner(base_path=base_path)
    if _project_runner is None:
        _project_runner = ProjectRunner()
    return _project_runner


__all__ = [
    "ExecutionEvidence",
    "ProjectArtifact",
    "ProjectBrief",
    "ProjectRunner",
    "get_project_runner",
]
