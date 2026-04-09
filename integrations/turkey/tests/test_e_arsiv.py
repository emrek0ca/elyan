from __future__ import annotations

import httpx

from core.privacy.data_governance import PrivacyEngine
from integrations.turkey.e_arsiv import EArsivConfig, EArsivConnector, EArsivCredentials


class _FakeAuditLogger:
    def __init__(self) -> None:
        self.operations: list[dict[str, object]] = []

    def log_operation(self, **kwargs):
        self.operations.append(dict(kwargs))
        return len(self.operations)


class _FakeSession:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls: list[dict[str, object]] = []

    def request(self, method: str, url: str, **kwargs):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": dict(kwargs.get("headers") or {}),
                "timeout": kwargs.get("timeout"),
            }
        )
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_health_check_uses_test_endpoint(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    session = _FakeSession(
        [httpx.Response(200, request=httpx.Request("GET", "https://earsiv-test.example.com/health"))]
    )
    connector = EArsivConnector(
        config=EArsivConfig(
            production_base_url="https://earsiv-prod.example.com",
            test_base_url="https://earsiv-test.example.com",
            health_path="health",
        ),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3"),
    )

    health = connector.health_check()

    assert health.is_healthy is True
    assert session.calls[0]["url"] == "https://earsiv-test.example.com/health"
    assert audit_logger.operations[0]["action"] == "health_check"


def test_test_credentials_requires_consent(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    session = _FakeSession([])
    connector = EArsivConnector(
        config=EArsivConfig(
            production_base_url="https://earsiv-prod.example.com",
            test_base_url="https://earsiv-test.example.com",
            credential_check_path="auth/check",
        ),
        credentials=EArsivCredentials(username="demo", password="secret"),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3"),
        user_id="user-1",
        workspace_id="ws-1",
    )

    assert connector.test_credentials() is False
    assert session.calls == []
    assert "KVKK" in str(audit_logger.operations[0]["result"]["error"])


def test_test_credentials_retries_with_backoff(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    privacy_engine = PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3")
    privacy_engine.set_consent(
        "user-1",
        workspace_id="ws-1",
        scope="turkey_connector.e_arsiv",
        granted=True,
        metadata={"allow_personal_data_learning": True},
    )
    session = _FakeSession(
        [
            httpx.ConnectError("timeout"),
            httpx.Response(200, request=httpx.Request("GET", "https://earsiv-test.example.com/auth/check")),
        ]
    )
    sleep_calls: list[float] = []
    connector = EArsivConnector(
        config=EArsivConfig(
            production_base_url="https://earsiv-prod.example.com",
            test_base_url="https://earsiv-test.example.com",
            credential_check_path="auth/check",
        ),
        credentials=EArsivCredentials(username="demo", password="secret"),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=privacy_engine,
        user_id="user-1",
        workspace_id="ws-1",
        max_attempts=2,
        retry_backoff_seconds=0.2,
        sleeper=sleep_calls.append,
    )

    assert connector.test_credentials() is True
    assert sleep_calls == [0.2]
    assert [entry["success"] for entry in audit_logger.operations] == [False, True]
