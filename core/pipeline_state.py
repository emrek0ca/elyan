"""
core/pipeline_state.py
─────────────────────────────────────────────────────────────────────────────
Manages transient data flow between chained tasks. Enables steps to use 
outputs from previous operations as inputs.
"""

from __future__ import annotations
import re
from typing import Dict, Any, Optional

class PipelineState:
    def __init__(self):
        self._data: Dict[str, Any] = {}
        self._last_result: Any = None

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

def get_pipeline_state() -> PipelineState:
    return _pipeline_state
