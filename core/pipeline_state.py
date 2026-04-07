"""
core/pipeline_state.py
─────────────────────────────────────────────────────────────────────────────
Manages transient data flow between chained tasks. Enables steps to use 
outputs from previous operations as inputs.
"""

from __future__ import annotations
import re
import time
import uuid
from contextvars import ContextVar
from typing import Dict, Any, Optional

class PipelineState:
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._last_result: Any = None
        self._pipelines: Dict[str, Any] = {}
        self._history: list[Dict[str, Any]] = []
        self._max_history = 500

    def start(self, user_id: str = "unknown", user_input: str = "",
              domain: str = "", tasks: list = None, pipeline_id: str | None = None) -> str:
        """Yeni bir pipeline oturumu başlatır ve ID döner."""
        pipeline_id = str(pipeline_id or "").strip() or str(uuid.uuid4())[:8]
        self._pipelines[pipeline_id] = {
            "id": pipeline_id,
            "user_id": user_id,
            "user_input": user_input,
            "domain": domain,
            "tasks": tasks or [],
            "started_at": time.time(),
            "status": "running",
        }
        return pipeline_id

    def complete(self, pipeline_id: str, success: bool = True,
                 summary: str = "", quality_report: Any = None) -> None:
        """Pipeline oturumunu tamamlandı olarak işaretler."""
        if pipeline_id in self._pipelines:
            self._pipelines[pipeline_id].update({
                "status": "success" if success else "failed",
                "summary": summary,
                "quality_report": quality_report,
                "completed_at": time.time(),
            })
            pipeline = self._pipelines[pipeline_id]
            if not bool(pipeline.get("_history_recorded")):
                snapshot = {
                    "id": pipeline.get("id", pipeline_id),
                    "user_id": pipeline.get("user_id", "unknown"),
                    "domain": pipeline.get("domain", ""),
                    "status": pipeline.get("status", "success" if success else "failed"),
                    "started_at": float(pipeline.get("started_at") or 0.0),
                    "completed_at": float(pipeline.get("completed_at") or 0.0),
                    "quality_report": pipeline.get("quality_report"),
                }
                self._history.append(snapshot)
                if len(self._history) > self._max_history:
                    self._history = self._history[-self._max_history:]
                pipeline["_history_recorded"] = True

    def store(self, key: str, value: Any):
        """Bir adımın sonucunu belirli bir anahtarla saklar."""
        self._data[key] = value
        self._last_result = value

    def mark_task(self, pipeline_id: str, task_id: str, success: bool, reason: str = "") -> None:
        """Pipeline içindeki bir task'ın durumunu günceller."""
        pipeline = self._pipelines.get(pipeline_id)
        if not pipeline:
            return

        status = "success" if success else "failed"
        tasks = pipeline.setdefault("tasks", [])
        for task in tasks:
            if isinstance(task, dict) and str(task.get("id")) == str(task_id):
                task["status"] = status
                task["reason"] = reason
                task["updated_at"] = time.time()
                break
        else:
            tasks.append({
                "id": task_id,
                "status": status,
                "reason": reason,
                "updated_at": time.time(),
            })

        pipeline["updated_at"] = time.time()

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def resolve_placeholders(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Parametreler içindeki {{key}} yapılarını gerçek verilerle değiştirir."""
        if not isinstance(params, dict):
            return params
            
        resolved = {}
        for k, v in params.items():
            if isinstance(v, str):
                # {{step_name}} veya {{last_output}} kontrolü
                resolved[k] = self._replace_string(v)
            elif isinstance(v, dict):
                resolved[k] = self.resolve_placeholders(v)
            else:
                resolved[k] = v
        return resolved

    def _replace_string(self, text: str) -> Any:
        # Tam eşleşme: "{{key}}" -> direkt obje (dict/list olabilir)
        full_match = re.fullmatch(r"\{\{([^}]+)\}\}", text)
        if full_match:
            key = full_match.group(1).strip()
            if key == "last_output":
                return self._last_result
            return self._data.get(key, text)
            
        # Kısmi eşleşme: "Dosya: {{filename}}" -> string formatlama
        def _replacer(match):
            key = match.group(1).strip()
            if key == "last_output":
                return str(self._last_result or "")
            return str(self._data.get(key, f"{{{{{key}}}}}"))
            
        return re.sub(r"\{\{([^}]+)\}\}", _replacer, text)

    def clear(self):
        self._data.clear()
        self._last_result = None

    def history_summary(self, window_hours: int = 24) -> Dict[str, Any]:
        """Son pipeline aktivitesinin kısa özetini döndürür."""
        hours = max(1, int(window_hours))
        cutoff = time.time() - (hours * 3600)

        active_count = sum(
            1 for pipeline in self._pipelines.values()
            if str(pipeline.get("status", "running")) == "running"
        )

        recent = [
            entry for entry in self._history
            if float(entry.get("completed_at") or 0.0) >= cutoff
        ]
        recent_total = len(recent)
        recent_success = sum(
            1 for entry in recent if str(entry.get("status", "")).lower() in {"success", "completed"}
        )
        recent_failed = sum(
            1 for entry in recent if str(entry.get("status", "")).lower() == "failed"
        )

        quality_scores = []
        for entry in recent:
            report = entry.get("quality_report")
            if isinstance(report, dict):
                for key in ("overall_score", "score", "quality_score"):
                    try:
                        if key in report:
                            quality_scores.append(float(report[key]))
                            break
                    except Exception:
                        continue

        avg_quality = round(sum(quality_scores) / len(quality_scores), 1) if quality_scores else 0.0
        success_rate = round((recent_success / recent_total) * 100.0, 1) if recent_total else 0.0

        return {
            "window_hours": hours,
            "active_count": active_count,
            "history_count": len(self._history),
            "recent_total": recent_total,
            "recent_success_rate": success_rate,
            "recent_failed": recent_failed,
            "recent_avg_quality": avg_quality,
        }

_pipeline_state = PipelineState()
_pipeline_state_var: ContextVar[PipelineState | None] = ContextVar("pipeline_state_var", default=None)


def create_pipeline_state() -> PipelineState:
    """Create a fresh isolated pipeline state."""
    return PipelineState()


def set_current_pipeline_state(state: PipelineState | None):
    """Bind state to current async context and return reset token."""
    return _pipeline_state_var.set(state)


def reset_current_pipeline_state(token) -> None:
    """Reset current async-context pipeline state."""
    _pipeline_state_var.reset(token)

def get_pipeline_state() -> PipelineState:
    scoped = _pipeline_state_var.get()
    if isinstance(scoped, PipelineState):
        return scoped
    return _pipeline_state
