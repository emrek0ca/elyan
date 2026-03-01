from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from config.settings import ELYAN_DIR


def _stable_hash(payload: Any) -> str:
    try:
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        raw = str(payload)
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class LedgerStep:
    step: str
    tool: str
    status: str
    input_hash: str
    params_hash: str
    result_hash: str
    duration_ms: int
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step": self.step,
            "tool": self.tool,
            "status": self.status,
            "input_hash": self.input_hash,
            "params_hash": self.params_hash,
            "result_hash": self.result_hash,
            "duration_ms": self.duration_ms,
            "ts": self.ts,
        }


class ExecutionLedger:
    """Collects deterministic execution evidence and emits a manifest."""

    def __init__(self, run_id: str | None = None):
        self.run_id = str(run_id or f"run_{uuid.uuid4().hex[:12]}")
        self.base_dir = (ELYAN_DIR / "proofs" / self.run_id).expanduser()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.steps: List[LedgerStep] = []
        self.artifacts: List[Dict[str, Any]] = []
        self.started_at = time.time()

    def log_step(
        self,
        *,
        step: str,
        tool: str,
        status: str,
        input_payload: Any,
        params: Any,
        result: Any,
        duration_ms: int,
    ) -> None:
        self.steps.append(
            LedgerStep(
                step=str(step or "step"),
                tool=str(tool or ""),
                status=str(status or "unknown"),
                input_hash=_stable_hash(input_payload),
                params_hash=_stable_hash(params),
                result_hash=_stable_hash(result),
                duration_ms=max(0, int(duration_ms or 0)),
            )
        )
        self._collect_artifacts_from_result(tool=str(tool or ""), result=result)

    def _collect_artifacts_from_result(self, *, tool: str, result: Any) -> None:
        if not isinstance(result, dict):
            return

        candidates: List[str] = []
        source_result: Dict[str, Any] = {}
        for key in ("success", "status_code", "duration_ms", "url", "total", "healthy", "unhealthy", "results"):
            if key in result:
                source_result[key] = result.get(key)

        for key in ("path", "file_path", "output_path", "screenshot", "image_path"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                candidates.append(value.strip())

        proof = result.get("_proof")
        if isinstance(proof, dict):
            shot = proof.get("screenshot")
            if isinstance(shot, str) and shot.strip():
                candidates.append(shot.strip())
                source_result["_proof"] = {"screenshot": shot.strip()}

        for key in ("paths", "files", "artifacts", "outputs"):
            value = result.get(key)
            if isinstance(value, list):
                for v in value:
                    if isinstance(v, str) and str(v).strip():
                        candidates.append(str(v).strip())
                    elif isinstance(v, dict):
                        p = str(v.get("path") or v.get("file_path") or "").strip()
                        if p:
                            candidates.append(p)

        for raw in candidates:
            try:
                p = Path(raw).expanduser().resolve()
            except Exception:
                continue
            if not p.exists() or not p.is_file():
                continue
            path_str = str(p)
            if any(a.get("path") == path_str for a in self.artifacts):
                continue
            try:
                size = int(p.stat().st_size)
                sha = _file_sha256(p)
            except Exception:
                size = 0
                sha = ""
            entry: Dict[str, Any] = {
                "path": path_str,
                "name": p.name,
                "size_bytes": size,
                "sha256": sha,
                "tool": str(tool or ""),
            }
            if source_result:
                entry["source_result"] = dict(source_result)
            self.artifacts.append(entry)

    def write_manifest(self, *, status: str = "success", error: str = "", metadata: Dict[str, Any] | None = None) -> str:
        payload = {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "completed_at": time.time(),
            "status": status,
            "error": str(error or ""),
            "steps": [s.to_dict() for s in self.steps],
            "artifacts": list(self.artifacts),
            "metadata": dict(metadata or {}),
        }
        out = self.base_dir / "manifest.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(out)


__all__ = ["ExecutionLedger"]
