"""
Run Store - canonical persistent storage for legacy async runs and evidence runs.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.observability.logger import get_structured_logger
from core.persistence import get_runtime_database
from core.security.contracts import DataClassification, classify_value, max_classification
from core.security.encrypted_vault import get_encrypted_vault
from core.storage_paths import resolve_runs_root
from core.telemetry.events import TelemetryEvent
from core.telemetry.metrics import sample_runtime_metrics
from core.telemetry.run_store import TelemetryRunStore
from core.text_artifacts import existing_text_path, write_text_artifact
from security.privacy_guard import sanitize_object

slog = get_structured_logger("run_store")


@dataclass
class RunStep:
    """Single step in a run."""

    step_id: str
    name: str
    status: str
    started_at: float
    completed_at: Optional[float] = None
    error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return self.completed_at - self.started_at
        return None


@dataclass
class RunRecord:
    """Single execution run record."""

    run_id: str
    session_id: str
    status: str
    intent: str
    steps: List[Dict[str, Any]] = field(default_factory=list)
    tool_calls: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=lambda: datetime.now().timestamp())
    completed_at: Optional[float] = None
    error: Optional[str] = None
    workflow_state: Optional[str] = None
    task_type: Optional[str] = None
    artifact_path: Optional[str] = None
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    review_report: Optional[Dict[str, Any]] = None
    workflow_history: List[Dict[str, Any]] = field(default_factory=list)
    assigned_agents: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    workspace_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def duration_seconds(self) -> Optional[float]:
        if self.completed_at:
            return self.completed_at - self.started_at
        return None


class RunStore:
    """Canonical store for legacy async runs and evidence artifacts."""

    def __init__(self, store_path: Optional[str | Path] = None, *, run_id: Optional[str] = None):
        self._lock = asyncio.Lock()
        self._capability_selected_emitted = False
        self._plan_created_emitted = False
        self._vault = get_encrypted_vault()
        self._run_index = get_runtime_database().run_index

        if run_id is not None or self._looks_like_run_id(store_path):
            self.run_id = str(run_id or store_path or "").strip() or f"run_{int(time.time())}"
            self.base_dir = (resolve_runs_root() / self.run_id).expanduser()
            self.store_path = self.base_dir
        else:
            root = Path(store_path).expanduser() if store_path else resolve_runs_root()
            self.run_id = str(run_id or root.name or "").strip()
            self.base_dir = root
            self.store_path = root

        self.base_dir.mkdir(parents=True, exist_ok=True)
        (self.base_dir / "artifacts").mkdir(parents=True, exist_ok=True)
        self.telemetry_store = TelemetryRunStore(self.run_id or f"run_{int(time.time())}", base_dir=self.base_dir)

        metrics = sample_runtime_metrics()
        self.telemetry_store.record_event(
            TelemetryEvent(
                event="run.started",
                request_id=self.run_id or self.telemetry_store.run_id,
                status="started",
                memory_mb=float(metrics.get("memory_mb") or 0.0),
                payload={"source": "run_store", "metrics": metrics},
            )
        )

    @staticmethod
    def _protected_fields() -> dict[str, DataClassification]:
        return {
            "steps": DataClassification.SENSITIVE,
            "tool_calls": DataClassification.SENSITIVE,
            "error": DataClassification.SENSITIVE,
            "artifacts": DataClassification.SENSITIVE,
            "review_report": DataClassification.INTERNAL,
            "workflow_history": DataClassification.INTERNAL,
            "metadata": DataClassification.INTERNAL,
        }

    def _protect_value(self, *, run_id: str, field_name: str, value: Any, default_classification: DataClassification) -> Any:
        if value in (None, "", [], {}):
            return value
        classification = classify_value(value, key=field_name)
        classification = max_classification(classification, default_classification)
        context = f"run_store:{run_id}:{field_name}"
        try:
            encrypted = self._vault.encrypt(value, context=context)
            return {
                "__elyan_encrypted__": True,
                "classification": classification.value,
                "envelope": encrypted,
            }
        except Exception as exc:
            slog.log_event(
                "run_store_encrypt_fallback",
                {"run_id": run_id, "field": field_name, "error": str(exc)},
                level="warning",
            )
            return {
                "__elyan_redacted__": True,
                "classification": classification.value,
                "value": sanitize_object(value),
            }

    def _restore_value(self, *, run_id: str, field_name: str, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        if value.get("__elyan_encrypted__") is True and isinstance(value.get("envelope"), dict):
            context = f"run_store:{run_id}:{field_name}"
            try:
                return self._vault.decrypt(dict(value.get("envelope") or {}), context=context)
            except Exception as exc:
                slog.log_event(
                    "run_store_decrypt_error",
                    {"run_id": run_id, "field": field_name, "error": str(exc)},
                    level="warning",
                )
                return sanitize_object(value)
        if value.get("__elyan_redacted__") is True:
            return value.get("value")
        return value

    def _serialize_run_record(self, run: RunRecord) -> dict[str, Any]:
        payload = run.to_dict()
        run_id = str(payload.get("run_id") or run.run_id or "")
        for field_name, classification in self._protected_fields().items():
            if field_name in payload:
                payload[field_name] = self._protect_value(
                    run_id=run_id,
                    field_name=field_name,
                    value=payload.get(field_name),
                    default_classification=classification,
                )
        return payload

    def _hydrate_run_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        data = dict(payload or {})
        run_id = str(data.get("run_id") or "")
        for field_name in self._protected_fields():
            if field_name in data:
                data[field_name] = self._restore_value(run_id=run_id, field_name=field_name, value=data.get(field_name))
        return data

    @staticmethod
    def _write_json_atomic(file_path: Path, payload: dict[str, Any]) -> None:
        temp_path = file_path.with_suffix(".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, default=str)
        temp_path.replace(file_path)

    def _read_run_payload(self, file_path: Path) -> Optional[dict[str, Any]]:
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _looks_like_run_id(value: object) -> bool:
        if value is None or isinstance(value, Path):
            return False
        if not isinstance(value, str):
            return False
        raw = value.strip()
        if not raw:
            return False
        if raw.startswith(("~", ".", os.sep)):
            return False
        if os.altsep and os.altsep in raw:
            return False
        if os.sep in raw:
            return False
        if raw.startswith("run_"):
            return True
        return False

    @staticmethod
    def _safe_json(value: Any) -> Any:
        try:
            json.dumps(value, ensure_ascii=False, default=str)
            return value
        except Exception:
            return str(value)

    async def record_run(self, run: RunRecord) -> None:
        async with self._lock:
            try:
                file_path = self.store_path / f"{run.run_id}.json"
                self._write_json_atomic(file_path, self._serialize_run_record(run))
                self._run_index.upsert_run(run.to_dict())
                slog.log_event("run_recorded", {"run_id": run.run_id, "status": run.status})
            except Exception as e:
                slog.log_event("run_record_error", {"run_id": run.run_id, "error": str(e)}, level="error")

    async def get_run(self, run_id: str) -> Optional[RunRecord]:
        async with self._lock:
            try:
                file_path = self.store_path / f"{run_id}.json"
                payload = self._read_run_payload(file_path)
                if not payload:
                    return None
                data = self._hydrate_run_payload(payload)
                return RunRecord(**data)
            except Exception as e:
                slog.log_event("run_get_error", {"run_id": run_id, "error": str(e)}, level="warning")
                return None

    async def list_runs(self, limit: int = 20, status: Optional[str] = None) -> List[RunRecord]:
        async with self._lock:
            try:
                runs = []
                files = sorted(self.store_path.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
                for file_path in files[: limit * 2]:
                    try:
                        payload = self._read_run_payload(file_path)
                        if not payload:
                            continue
                        run = RunRecord(**self._hydrate_run_payload(payload))
                        if status is None or run.status == status:
                            runs.append(run)
                            if len(runs) >= limit:
                                break
                    except Exception as e:
                        slog.log_event("run_list_file_error", {"file": file_path.name, "error": str(e)}, level="warning")
                return runs
            except Exception as e:
                slog.log_event("run_list_error", {"error": str(e)}, level="error")
                return []

    async def cancel_run(self, run_id: str) -> bool:
        async with self._lock:
            try:
                file_path = self.store_path / f"{run_id}.json"
                payload = self._read_run_payload(file_path)
                if not payload:
                    return False
                payload["status"] = "cancelled"
                payload["completed_at"] = datetime.now().timestamp()
                self._write_json_atomic(file_path, payload)
                self._run_index.mark_status(run_id, status="cancelled", completed_at=float(payload["completed_at"]))
                slog.log_event("run_cancelled", {"run_id": run_id})
                return True
            except Exception as e:
                slog.log_event("run_cancel_error", {"run_id": run_id, "error": str(e)}, level="error")
                return False

    async def cleanup_old_runs(self, days: int = 7) -> int:
        async with self._lock:
            try:
                cutoff = datetime.now().timestamp() - (days * 86400)
                deleted = 0
                for file_path in self.store_path.glob("*.json"):
                    try:
                        if file_path.stat().st_mtime < cutoff:
                            file_path.unlink()
                            deleted += 1
                    except Exception:
                        pass
                if deleted > 0:
                    slog.log_event("runs_cleanup", {"deleted": deleted})
                return deleted
            except Exception as e:
                slog.log_event("run_cleanup_error", {"error": str(e)}, level="error")
                return 0

    async def get_step_timeline(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = await self.get_run(run_id)
        if not run:
            return None

        if not run.steps:
            return {
                "run_id": run_id,
                "steps": [],
                "total_duration": run.duration_seconds(),
                "critical_path": [],
                "step_count": 0,
            }

        timeline = []
        for step_data in run.steps:
            step = step_data if isinstance(step_data, dict) else asdict(step_data)
            timeline.append(
                {
                    "step_id": step.get("step_id", f"step_{len(timeline)}"),
                    "name": step.get("name", "Unknown"),
                    "status": step.get("status", "unknown"),
                    "start": step.get("started_at", 0),
                    "duration": (
                        step.get("completed_at", step.get("started_at", 0)) - step.get("started_at", 0)
                        if step.get("completed_at")
                        else 0
                    ),
                    "dependencies": step.get("dependencies", []),
                    "error": step.get("error"),
                }
            )

        critical_path = self._calculate_critical_path(timeline)
        return {
            "run_id": run_id,
            "steps": timeline,
            "total_duration": run.duration_seconds(),
            "critical_path": critical_path,
            "step_count": len(timeline),
            "run_status": run.status,
        }

    def _calculate_critical_path(self, steps: List[Dict[str, Any]]) -> List[str]:
        if not steps:
            return []

        start_steps = [s for s in steps if not s.get("dependencies")]
        if not start_steps:
            return [s["step_id"] for s in steps[:1]]

        visited = set()

        def find_longest_path(step_id: str) -> float:
            if step_id in visited:
                return 0
            visited.add(step_id)

            step = next((s for s in steps if s["step_id"] == step_id), None)
            if not step:
                return 0

            duration = step.get("duration", 0)
            max_child_duration = 0
            for s in steps:
                if step_id in s.get("dependencies", []):
                    child_duration = find_longest_path(s["step_id"])
                    if child_duration > max_child_duration:
                        max_child_duration = child_duration
            return duration + max_child_duration

        longest_path: List[str] = []
        longest_duration = 0
        for start_step in start_steps:
            visited.clear()
            duration = find_longest_path(start_step["step_id"])
            if duration > longest_duration:
                longest_duration = duration
                longest_path = [start_step["step_id"]]

        return longest_path

    def write_task(
        self,
        task_spec: Dict[str, Any] | None,
        *,
        user_input: str = "",
        metadata: Dict[str, Any] | None = None,
        task_state: Dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "run_id": self.run_id or self.telemetry_store.run_id,
            "user_input": str(user_input or ""),
            "task_spec": self._safe_json(task_spec or {}),
            "metadata": self._safe_json(metadata or {}),
            "task_state": self._safe_json(task_state or {}),
            "written_at": time.time(),
        }
        out = self.base_dir / "task.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        meta = payload["metadata"] if isinstance(payload["metadata"], dict) else {}
        task_state_payload = payload["task_state"] if isinstance(payload["task_state"], dict) else {}
        task_context = task_state_payload.get("context") if isinstance(task_state_payload.get("context"), dict) else {}
        capability = str(meta.get("capability_domain") or task_context.get("capability_domain") or "").strip()
        workflow_id = str(meta.get("workflow_id") or task_context.get("workflow_id") or "").strip()
        action = str(meta.get("action") or task_context.get("action") or "").strip()

        if capability and not self._capability_selected_emitted:
            self.telemetry_store.record_event(
                TelemetryEvent(
                    event="capability.selected",
                    request_id=self.run_id or self.telemetry_store.run_id,
                    selected_capability=capability,
                    workflow_path=[workflow_id] if workflow_id else [],
                    status=str(meta.get("phase") or "selected"),
                    payload={"action": action, "job_type": str(meta.get("job_type") or task_context.get("job_type") or "")},
                )
            )
            self._capability_selected_emitted = True

        subtasks = task_state_payload.get("subtasks") if isinstance(task_state_payload.get("subtasks"), list) else []
        if subtasks and not self._plan_created_emitted:
            self.telemetry_store.record_event(
                TelemetryEvent(
                    event="plan.created",
                    request_id=self.run_id or self.telemetry_store.run_id,
                    selected_capability=capability,
                    workflow_path=[workflow_id] if workflow_id else [],
                    status="created",
                    payload={
                        "step_count": len(subtasks),
                        "action": action,
                        "job_type": str(meta.get("job_type") or task_context.get("job_type") or ""),
                    },
                )
            )
            self._plan_created_emitted = True

        self.telemetry_store.write_summary(
            {
                "status": str((metadata or {}).get("status") or "task_recorded"),
                "user_input": str(user_input or ""),
                "task_spec": payload["task_spec"],
                "task_state": payload["task_state"],
                "metadata": payload["metadata"],
            }
        )
        return str(out)

    def write_evidence(
        self,
        *,
        manifest_path: str = "",
        steps: List[Dict[str, Any]] | None = None,
        artifacts: List[Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        payload = {
            "run_id": self.run_id or self.telemetry_store.run_id,
            "manifest_path": str(manifest_path or ""),
            "steps": self._safe_json(list(steps or [])),
            "artifacts": self._safe_json(list(artifacts or [])),
            "metadata": self._safe_json(metadata or {}),
            "written_at": time.time(),
        }
        out = self.base_dir / "evidence.json"
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self.telemetry_store.write_artifact_manifest(list(payload["artifacts"]))
        self.telemetry_store.write_verification(
            {
                "status": str((metadata or {}).get("status") or "evidence_recorded"),
                "manifest_path": payload["manifest_path"],
                "steps": payload["steps"],
                "artifacts": payload["artifacts"],
                "metadata": payload["metadata"],
            }
        )
        self.telemetry_store.record_event(
            TelemetryEvent(
                event="verify.finished",
                request_id=self.run_id or self.telemetry_store.run_id,
                status=str((metadata or {}).get("status") or "evidence_recorded"),
                payload={
                    "manifest_path": payload["manifest_path"],
                    "artifact_count": len(payload["artifacts"]),
                    "step_count": len(payload["steps"]),
                },
            )
        )
        return str(out)

    def write_summary(
        self,
        *,
        status: str,
        response_text: str,
        error: str = "",
        artifacts: List[Dict[str, Any]] | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> str:
        lines = [
            f"# Run Summary ({self.run_id or self.telemetry_store.run_id})",
            "",
            f"- Status: {status}",
            f"- Error: {error or '-'}",
            "",
            "## Response",
            "",
            str(response_text or "").strip() or "-",
            "",
            "## Artifacts",
        ]
        for art in list(artifacts or []):
            if not isinstance(art, dict):
                continue
            path = str(art.get("path") or "").strip()
            sha = str(art.get("sha256") or "").strip()
            if not path:
                continue
            row = f"- {path}"
            if sha:
                row += f" (sha256: {sha})"
            lines.append(row)

        meta = metadata or {}
        if isinstance(meta, dict):
            if str(meta.get("workflow_profile") or "").strip():
                lines.append(f"- Workflow profile: {str(meta.get('workflow_profile') or '').strip()}")
            if str(meta.get("workflow_phase") or "").strip():
                lines.append(f"- Workflow phase: {str(meta.get('workflow_phase') or '').strip()}")
            if str(meta.get("execution_route") or "").strip():
                lines.append(f"- Execution route: {str(meta.get('execution_route') or '').strip()}")
            if str(meta.get("autonomy_mode") or "").strip():
                lines.append(f"- Autonomy mode: {str(meta.get('autonomy_mode') or '').strip()}")
            if str(meta.get("autonomy_policy") or "").strip():
                lines.append(f"- Autonomy policy: {str(meta.get('autonomy_policy') or '').strip()}")
            if isinstance(meta.get("orchestration_decision_path"), list) and meta.get("orchestration_decision_path"):
                lines.append(
                    "- Decision path: "
                    + " > ".join(str(item).strip() for item in list(meta.get("orchestration_decision_path") or []) if str(item).strip())
                )
            if str(meta.get("approval_status") or "").strip():
                lines.append(f"- Approval status: {str(meta.get('approval_status') or '').strip()}")
            if str(meta.get("plan_progress") or "").strip():
                lines.append(f"- Plan progress: {str(meta.get('plan_progress') or '').strip()}")
            if str(meta.get("review_status") or "").strip():
                lines.append(f"- Review status: {str(meta.get('review_status') or '').strip()}")
            if str(meta.get("workspace_mode") or "").strip():
                lines.append(f"- Workspace mode: {str(meta.get('workspace_mode') or '').strip()}")
            if str(meta.get("design_artifact_path") or "").strip():
                lines.append(f"- Design artifact: {str(meta.get('design_artifact_path') or '').strip()}")
            if str(meta.get("plan_artifact_path") or "").strip():
                lines.append(f"- Plan artifact: {str(meta.get('plan_artifact_path') or '').strip()}")
            if str(meta.get("review_artifact_path") or "").strip():
                lines.append(f"- Review artifact: {str(meta.get('review_artifact_path') or '').strip()}")
            if str(meta.get("workspace_report_path") or "").strip():
                lines.append(f"- Workspace report: {str(meta.get('workspace_report_path') or '').strip()}")
            if str(meta.get("finish_branch_report_path") or "").strip():
                lines.append(f"- Finish branch report: {str(meta.get('finish_branch_report_path') or '').strip()}")
            if "claim_coverage" in meta:
                lines.append(f"- Claim coverage: {float(meta.get('claim_coverage', 0.0) or 0.0):.2f}")
            if "critical_claim_coverage" in meta:
                lines.append(f"- Critical claim coverage: {float(meta.get('critical_claim_coverage', 0.0) or 0.0):.2f}")
            if "uncertainty_count" in meta:
                lines.append(f"- Uncertainty count: {int(meta.get('uncertainty_count', 0) or 0)}")
            if "conflict_count" in meta:
                lines.append(f"- Conflict count: {int(meta.get('conflict_count', 0) or 0)}")
            if "manual_review_claim_count" in meta:
                lines.append(f"- Manual review claims: {int(meta.get('manual_review_claim_count', 0) or 0)}")
            if str(meta.get("claim_map_path") or "").strip():
                lines.append(f"- Claim map: {str(meta.get('claim_map_path') or '').strip()}")
            if str(meta.get("revision_summary_path") or "").strip():
                lines.append(f"- Revision summary: {str(meta.get('revision_summary_path') or '').strip()}")
            if "team_quality_avg" in meta:
                lines.append(f"- Team quality avg: {float(meta.get('team_quality_avg', 0.0) or 0.0):.2f}")
            if "team_parallel_waves" in meta:
                lines.append(f"- Team parallel waves: {int(meta.get('team_parallel_waves', 0) or 0)}")
            if "team_max_wave_size" in meta:
                lines.append(f"- Team max wave size: {int(meta.get('team_max_wave_size', 0) or 0)}")
            if "team_parallelizable_packets" in meta:
                lines.append(f"- Team parallelizable packets: {int(meta.get('team_parallelizable_packets', 0) or 0)}")
            if "team_serial_packets" in meta:
                lines.append(f"- Team serial packets: {int(meta.get('team_serial_packets', 0) or 0)}")
            if "team_ownership_conflicts" in meta:
                lines.append(f"- Team ownership conflicts: {int(meta.get('team_ownership_conflicts', 0) or 0)}")
            if "team_research_claim_coverage" in meta:
                lines.append(f"- Team research claim coverage: {float(meta.get('team_research_claim_coverage', 0.0) or 0.0):.2f}")
            if "team_research_critical_claim_coverage" in meta:
                lines.append(
                    f"- Team research critical coverage: {float(meta.get('team_research_critical_claim_coverage', 0.0) or 0.0):.2f}"
                )
            if "team_research_uncertainty_count" in meta:
                lines.append(f"- Team research uncertainty count: {int(meta.get('team_research_uncertainty_count', 0) or 0)}")
        if meta:
            lines.extend(["", "## Metadata", "", "```json", json.dumps(meta, ensure_ascii=False, indent=2, default=str), "```"])

        out = Path(write_text_artifact(self.base_dir, "summary.txt", "\n".join(lines).strip() + "\n"))
        self.telemetry_store.write_delivery(
            {
                "status": str(status or ""),
                "text_summary": str(response_text or "").strip(),
                "errors": [str(error or "").strip()] if str(error or "").strip() else [],
                "artifact_manifest": list(artifacts or []),
                "metadata": meta,
            }
        )
        self.telemetry_store.record_event(
            TelemetryEvent(
                event="deliver.finished",
                request_id=self.run_id or self.telemetry_store.run_id,
                status=str(status or ""),
                payload={"artifact_count": len(list(artifacts or [])), "error": str(error or "")},
            )
        )
        self.telemetry_store.record_event(
            TelemetryEvent(
                event="run.completed",
                request_id=self.run_id or self.telemetry_store.run_id,
                status=str(status or ""),
                payload={"error": str(error or ""), "artifact_count": len(list(artifacts or []))},
            )
        )
        return str(out)

    def write_logs(self, lines: List[str] | None = None) -> str:
        out = self.base_dir / "logs.txt"
        payload = "\n".join(str(x) for x in (lines or []) if str(x).strip())
        out.write_text(payload + ("\n" if payload else ""), encoding="utf-8")
        return str(out)

    @staticmethod
    def list_recent_run_dirs(limit: int = 20) -> List[Path]:
        root = resolve_runs_root().expanduser()
        if not root.exists():
            return []
        candidates: list[tuple[float, Path]] = []
        for p in root.iterdir():
            if not p.is_dir():
                continue
            try:
                mtime = float(p.stat().st_mtime)
            except Exception:
                mtime = 0.0
            candidates.append((mtime, p))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in candidates[: max(1, int(limit))]]

    @staticmethod
    def load_task_from_run(run_dir: Path) -> Dict[str, Any]:
        task_path = Path(run_dir) / "task.json"
        if not task_path.exists():
            return {}
        try:
            payload = json.loads(task_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return payload
        except Exception:
            pass
        return {}

    @classmethod
    def find_latest_failed_task(cls, limit: int = 30) -> Dict[str, Any]:
        for run_dir in cls.list_recent_run_dirs(limit=limit):
            summary = existing_text_path(run_dir / "summary.txt")
            if not summary.exists():
                continue
            try:
                content = summary.read_text(encoding="utf-8").lower()
            except Exception:
                continue
            if "- status: failed" not in content:
                continue
            task_payload = cls.load_task_from_run(run_dir)
            if task_payload:
                task_payload["_run_dir"] = str(run_dir)
                return task_payload
        return {}


_run_store: Optional[RunStore] = None


def get_run_store(store_path: Optional[str] = None) -> RunStore:
    """Get or create the run store singleton."""
    global _run_store
    if _run_store is None:
        _run_store = RunStore(store_path)
    return _run_store


__all__ = ["RunRecord", "RunStep", "RunStore", "get_run_store"]
