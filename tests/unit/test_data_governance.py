from core.privacy.data_governance import (
    ConsentPolicy,
    DataClassification,
    PrivacyEngine,
    build_privacy_decision,
)


def test_privacy_engine_personal_requires_consent(tmp_path):
    consent_db = tmp_path / "consent.db"
    runtime_db = tmp_path / "runtime.sqlite3"
    engine = PrivacyEngine(db_path=consent_db, runtime_db_path=runtime_db)
    decision = engine.decide(
        user_id="user-1",
        workspace_id="ws-1",
        source_kind="message",
        text="mail me at jane@example.com",
    )
    assert decision.classification is DataClassification.PERSONAL
    assert decision.shared_learning_eligible is False
    assert decision.reason in {"personal_data_requires_consent", "personal_data_default_denied"}


def test_privacy_engine_set_and_get_consent(tmp_path):
    engine = PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3")
    engine.set_consent(
        "user-1",
        workspace_id="ws-1",
        granted=True,
        metadata={"allow_personal_data_learning": True, "allow_global_aggregate": False},
    )
    consent = engine.get_consent("user-1", workspace_id="ws-1")
    assert consent["granted"] is True
    assert consent["policy"]["allow_personal_data_learning"] is True
    assert consent["policy"]["allow_global_aggregation"] is False


def test_build_privacy_decision_operational_redacts():
    decision = build_privacy_decision(
        user_id="user-1",
        workspace_id="ws-1",
        source_kind="operational",
        text="request id 123",
        payload={"token": "abc123"},
        consent_policy=ConsentPolicy(),
        classification=DataClassification.OPERATIONAL,
    )
    assert decision.redacted is True
    assert decision.shared_learning_eligible is True
    assert decision.payload["token"] == "[REDACTED]"
