from __future__ import annotations

from core.reliability.store import ConfidenceCalibrator, FailureClusterer, OutcomeStore, RegressionEvaluator


def test_outcome_store_records_decisions_and_outcomes(tmp_path):
    store = OutcomeStore(storage_root=tmp_path / "reliability")
    store.record_decision(
        request_id="req-1",
        user_id="u1",
        kind="route_choice",
        selected="code",
        confidence=0.8,
        raw_confidence=0.75,
        channel="cli",
        source="test",
    )
    store.record_outcome(
        request_id="req-1",
        user_id="u1",
        action="code",
        channel="cli",
        final_outcome="success",
        success=True,
        verification_result={"ok": True},
        decision_trace={"route_choice": {"candidate": "code"}},
        metadata={"tool_call_result": {"tool_count": 1}},
    )

    decisions = store.decisions_for_request("req-1")
    outcomes = store.recent_outcomes("u1", limit=5)

    assert decisions[0]["selected"] == "code"
    assert decisions[0]["success_label"] is True
    assert outcomes[0]["final_outcome"] == "success"
    assert store.stats()["outcomes"] == 1


def test_failure_clusterer_groups_similar_failures(tmp_path):
    store = OutcomeStore(storage_root=tmp_path / "reliability")
    for idx in range(2):
        store.record_outcome(
            request_id=f"req-{idx}",
            user_id="u1",
            action="browser",
            channel="dashboard",
            final_outcome="failed",
            success=False,
            verification_result={"ok": False, "reasons": ["missing_required_artifact"]},
            metadata={"error": f"/tmp/run{idx}/screen.png missing"},
        )

    clusterer = FailureClusterer(store)
    clusters = clusterer.cluster()

    assert clusters
    assert clusters[0]["count"] >= 2


def test_confidence_calibrator_uses_history_after_enough_samples(tmp_path):
    store = OutcomeStore(storage_root=tmp_path / "reliability")
    for idx in range(6):
        store.record_decision(
            request_id=f"req-{idx}",
            user_id="u1",
            kind="intent_prediction",
            selected="research",
            confidence=0.4,
            raw_confidence=0.4,
            channel="cli",
            source="test",
        )
        store.record_outcome(
            request_id=f"req-{idx}",
            user_id="u1",
            action="research",
            channel="cli",
            final_outcome="success",
            success=True,
        )

    calibrator = ConfidenceCalibrator(store)
    calibrated = calibrator.calibrate("intent_prediction", "research", 0.4)

    assert calibrated > 0.4


def test_regression_evaluator_summarizes_metrics(tmp_path):
    store = OutcomeStore(storage_root=tmp_path / "reliability")
    for idx in range(3):
        store.record_decision(
            request_id=f"req-{idx}",
            user_id="u1",
            kind="route_choice",
            selected="code",
            confidence=0.8,
            raw_confidence=0.8,
            channel="cli",
            source="test",
        )
        store.record_outcome(
            request_id=f"req-{idx}",
            user_id="u1",
            action="code",
            channel="cli",
            final_outcome="success" if idx < 2 else "failed",
            success=idx < 2,
            verification_result={"ok": idx < 2},
            metadata={"tool_call_result": {"tool_count": 1}},
        )

    evaluator = RegressionEvaluator(store, FailureClusterer(store))
    summary = evaluator.summary()
    deleted = store.delete_user("u1")

    assert "false_positive_execution_rate" in summary
    assert "verification_pass_rate" in summary
    assert deleted["deleted_outcomes"] == 3
