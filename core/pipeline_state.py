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

    def start(self, user_id: str = "unknown", user_input: str = "",
              domain: str = "", tasks: list = None) -> str:
        """Yeni bir pipeline oturumu başlatır ve ID döner."""
        pipeline_id = str(uuid.uuid4())[:8]
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

    def store(self, key: str, value: Any):
        """Bir adımın sonucunu belirli bir anahtarla saklar."""
        self._data[key] = value
        self._last_result = value

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
