from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class ConnectorHealth:
    is_healthy: bool
    latency_ms: float
    last_error: str | None = None


class ConnectorBase(ABC):
    @abstractmethod
    def get_name(self) -> str:
        """Return the stable connector identifier."""

    @abstractmethod
    def health_check(self) -> ConnectorHealth:
        """Run a connectivity check and report connector health."""

    @abstractmethod
    def test_credentials(self) -> bool:
        """Validate the configured credentials for the connector."""
