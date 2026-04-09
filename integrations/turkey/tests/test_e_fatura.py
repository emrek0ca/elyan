from __future__ import annotations

import httpx

from core.privacy.data_governance import PrivacyEngine
from integrations.turkey.e_fatura import EFaturaConfig, EFaturaConnector, EFaturaCredentials


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


def test_health_check_uses_test_endpoint_and_records_audit(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    session = _FakeSession(
        [
            httpx.Response(
                200,
                request=httpx.Request("GET", "https://efaturatest.gib.gov.tr"),
            )
        ]
    )
    connector = EFaturaConnector(
        config=EFaturaConfig(),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3"),
    )

    health = connector.health_check()

    assert health.is_healthy is True
    assert health.last_error is None
    assert session.calls[0]["url"] == "https://efaturatest.gib.gov.tr"
    assert audit_logger.operations[0]["action"] == "health_check"
    assert audit_logger.operations[0]["success"] is True


def test_test_credentials_requires_kvkk_consent_before_remote_call(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    session = _FakeSession([])
    connector = EFaturaConnector(
        credentials=EFaturaCredentials(username="demo", password="secret"),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3"),
        user_id="user-1",
        workspace_id="ws-1",
    )

    assert connector.test_credentials() is False
    assert session.calls == []
    assert audit_logger.operations[0]["success"] is False
    assert "KVKK" in str(audit_logger.operations[0]["result"]["error"])


def test_test_credentials_retries_with_backoff_and_succeeds(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    privacy_engine = PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3")
    privacy_engine.set_consent(
        "user-1",
        workspace_id="ws-1",
        scope="turkey_connector.e_fatura",
        granted=True,
        metadata={"allow_personal_data_learning": True},
    )
    session = _FakeSession(
        [
            httpx.ConnectError("baglanti hatasi"),
            httpx.Response(
                200,
                request=httpx.Request("GET", "https://efaturatest.gib.gov.tr"),
            ),
        ]
    )
    sleep_calls: list[float] = []
    connector = EFaturaConnector(
        credentials=EFaturaCredentials(username="demo", password="secret"),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=privacy_engine,
        user_id="user-1",
        workspace_id="ws-1",
        retry_backoff_seconds=0.25,
        max_attempts=2,
        sleeper=sleep_calls.append,
    )

    assert connector.test_credentials() is True
    assert len(session.calls) == 2
    assert sleep_calls == [0.25]
    assert [entry["success"] for entry in audit_logger.operations] == [False, True]


def test_test_credentials_returns_false_when_remote_service_rejects_credentials(tmp_path) -> None:
    audit_logger = _FakeAuditLogger()
    privacy_engine = PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3")
    privacy_engine.set_consent(
        "user-1",
        workspace_id="ws-1",
        scope="turkey_connector.e_fatura",
        granted=True,
        metadata={"allow_personal_data_learning": True},
    )
    session = _FakeSession(
        [
            httpx.Response(
                401,
                request=httpx.Request("GET", "https://efaturatest.gib.gov.tr"),
            )
        ]
    )
    connector = EFaturaConnector(
        credentials=EFaturaCredentials(username="demo", password="secret"),
        session=session,
        audit_logger=audit_logger,
        privacy_engine=privacy_engine,
        user_id="user-1",
        workspace_id="ws-1",
    )

    assert connector.test_credentials() is False
    assert len(session.calls) == 1
    assert audit_logger.operations[0]["success"] is False
    assert "kimlik" in str(audit_logger.operations[0]["result"]["error"]).lower()
