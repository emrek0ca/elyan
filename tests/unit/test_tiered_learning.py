from core.learning.tiered_learning import LearningTier, TieredLearningHub, TieredSignal
from core.personalization.policy_learning import PolicyLearningStore
from core.privacy.data_governance import PrivacyEngine, DataClassification


def test_tiered_learning_records_workspace_signal(tmp_path):
    hub = TieredLearningHub(
        db_path=tmp_path / "tiered.sqlite3",
        privacy_engine=PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3"),
        policy_store=PolicyLearningStore(db_path=tmp_path / "policy_learning.sqlite3"),
    )
    result = hub.record(
        TieredSignal(
            user_id="user-1",
            workspace_id="ws-1",
            task_type="dispatch",
            source_kind="workspace",
            outcome="success",
            latency_ms=42,
            payload={"email": "x@y.com"},
            raw_metadata={"token": "secret"},
            classification=DataClassification.WORKSPACE,
        )
    )
    assert result["success"] is True
    assert result["tier"] == LearningTier.TIER2.value
    stats = hub.stats()
    assert stats["total_signals"] == 1


def test_tiered_learning_skips_when_opted_out(tmp_path):
    store = PolicyLearningStore(db_path=tmp_path / "policy_learning.sqlite3")
    store.set_user_policy("user-1", opt_out=True)
    hub = TieredLearningHub(
        db_path=tmp_path / "tiered.sqlite3",
        privacy_engine=PrivacyEngine(db_path=tmp_path / "consent.db", runtime_db_path=tmp_path / "runtime.sqlite3"),
        policy_store=store,
    )
    result = hub.record(TieredSignal(user_id="user-1", classification=DataClassification.OPERATIONAL))
    assert result["tier"] == LearningTier.SKIPPED.value
    assert result["skipped"] == "learning_paused_or_opt_out"
