from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class PluginManifest:
    """Minimal metadata contract for skill plugins."""

    name: str
    version: str
    description: str
    required_permissions: list[str] = field(default_factory=list)
    sandbox_required: bool = True


class SkillPlugin(ABC):
    """Base class for production skill plugins.

    The contract is intentionally small so plugins stay easy to audit and test.
    """

    @abstractmethod
    def get_manifest(self) -> PluginManifest:
        raise NotImplementedError

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self) -> bool:
        raise NotImplementedError


__all__ = ["PluginManifest", "SkillPlugin"]
