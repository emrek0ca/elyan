from __future__ import annotations

from importlib import import_module
from typing import Any

__all__ = [
    "LearningControlPlane",
    "OperatorControlPlane",
    "SkillRegistry",
    "SecurityLayer",
    "get_learning_control_plane",
    "get_operator_control_plane",
    "get_security_layer",
    "skill_registry",
    "security_layer",
]

_EXPORTS = {
    "LearningControlPlane": (".learning", "LearningControlPlane"),
    "OperatorControlPlane": (".control_plane", "OperatorControlPlane"),
    "SkillRegistry": (".registry", "SkillRegistry"),
    "SecurityLayer": (".security", "SecurityLayer"),
    "get_learning_control_plane": (".learning", "get_learning_control_plane"),
    "get_operator_control_plane": (".control_plane", "get_operator_control_plane"),
    "get_security_layer": (".security", "get_security_layer"),
    "skill_registry": (".registry", "skill_registry"),
    "security_layer": (".security", "security_layer"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(target[0], __name__)
    value = getattr(module, target[1])
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
