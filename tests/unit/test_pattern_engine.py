from __future__ import annotations

from core.ambient.pattern_engine import Pattern, PatternEngine


def test_record_activity_and_detect_patterns(tmp_path) -> None:
    engine = PatternEngine(storage_path=tmp_path / "activity.jsonl")
    engine.record_activity({"workspace_id": "ws-1", "actor_id": "user-1", "action": "weekly_report", "target": "finance"})
    engine.record_activity({"workspace_id": "ws-1", "actor_id": "user-1", "action": "weekly_report", "target": "finance"})
    engine.record_activity({"workspace_id": "ws-1", "actor_id": "user-1", "action": "weekly_report", "target": "finance"})

    patterns = engine.detect_patterns()

    assert len(patterns) == 1
    assert patterns[0].frequency == 3
    assert patterns[0].trigger_conditions["action"] == "weekly_report"


def test_suggest_automation_returns_none_when_confidence_is_low(tmp_path) -> None:
    engine = PatternEngine(storage_path=tmp_path / "activity.jsonl")
    pattern = Pattern(
        id="pattern-1",
        description="Tek seferlik rapor hazirlama",
        frequency=1,
        confidence=0.6,
        trigger_conditions={"action": "weekly_report"},
    )

    assert engine.suggest_automation(pattern) is None


def test_suggest_automation_returns_none_when_feature_flag_is_disabled(tmp_path) -> None:
    engine = PatternEngine(storage_path=tmp_path / "activity.jsonl")
    pattern = Pattern(
        id="pattern-1",
        description="Her pazartesi rapor hazirlama",
        frequency=6,
        confidence=0.9,
        trigger_conditions={"action": "weekly_report"},
    )

    assert engine.suggest_automation(pattern) is None


def test_suggest_automation_returns_payload_when_flag_enabled(tmp_path) -> None:
    engine = PatternEngine(
        storage_path=tmp_path / "activity.jsonl",
        runtime_policy={"feature_flags": {"ambient_pattern_engine": True}},
    )
    pattern = Pattern(
        id="pattern-1",
        description="Her pazartesi rapor hazirlama",
        frequency=6,
        confidence=0.9,
        trigger_conditions={"action": "weekly_report", "target": "finance"},
    )

    suggestion = engine.suggest_automation(pattern)

    assert suggestion is not None
    assert suggestion["pattern_id"] == "pattern-1"
    assert suggestion["action"] == "weekly_report"
