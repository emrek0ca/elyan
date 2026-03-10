from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class CapabilityRuntime:
    capability_id: str
    workflow_id: str
    actions: frozenset[str]
    evaluator: Callable[..., dict[str, Any]]

    def supports(self, action: str) -> bool:
        return str(action or "").strip().lower() in self.actions


__all__ = ["CapabilityRuntime"]
