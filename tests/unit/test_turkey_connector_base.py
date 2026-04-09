from __future__ import annotations

import pytest

from integrations.turkey.base import ConnectorBase, ConnectorHealth


class _DemoTurkeyConnector(ConnectorBase):
    def get_name(self) -> str:
        return "demo"

    def health_check(self) -> ConnectorHealth:
        return ConnectorHealth(is_healthy=True, latency_ms=12.5, last_error=None)

    def test_credentials(self) -> bool:
        return True


def test_connector_health_defaults_to_no_error() -> None:
    health = ConnectorHealth(is_healthy=True, latency_ms=42.0)

    assert health.is_healthy is True
    assert health.latency_ms == 42.0
    assert health.last_error is None


def test_turkey_connector_base_requires_contract_methods() -> None:
    with pytest.raises(TypeError):
        ConnectorBase()


def test_concrete_turkey_connector_can_implement_contract() -> None:
    connector = _DemoTurkeyConnector()

    assert connector.get_name() == "demo"
    assert connector.test_credentials() is True
    assert connector.health_check() == ConnectorHealth(
        is_healthy=True,
        latency_ms=12.5,
        last_error=None,
    )
