from __future__ import annotations

import pytest
from types import SimpleNamespace

from core.learning_control import LearningControlPlane


class _Personalization:
    def __init__(self):
        self.interactions = []
        self.feedback = []
        self.memory_store = type(
            "_MemoryStore",
            (),
            {
                "get_stats": staticmethod(lambda: {"backend": {"vector_effective": "sqlite_fallback"}}),
                "interaction_count": staticmethod(lambda _user_id: 2),
            },
        )()
        self.reward_service = type(
            "_RewardService",
            (),
            {
                "aggregate_user_feedback": staticmethod(lambda _user_id: {"feedback_events": 2, "avg_reward": 0.75}),
                "list_feedback": staticmethod(lambda _user_id, limit=20: [
                    {
                        "event_type": "correction",
                        "reward": -0.8,
                        "metadata": {"wrong_action": "browser", "corrected_text": "tıkla"},
                        "created_at": 1.0,
                    },
                    {
                        "event_type": "like",
                        "reward": 1.0,
                        "metadata": {"source": "manual"},
                        "created_at": 2.0,
                    },
                ][:limit]),
            },
        )()
        self.trainer_queue = type(
            "_TrainerQueue",
            (),
            {"list_jobs": staticmethod(lambda _user_id, limit=5: [{"job_id": "job-1", "limit": limit}])},
        )()
        self._runtime_profile = {
            "preferred_language": "tr-TR",
            "response_length_bias": "short",
            "top_topics": ["browser", "automation"],
            "preferred_topics": ["browser"],
        }

    async def get_runtime_context(self, user_id, request_meta=None):
        return {"user_id": user_id, "request": request_meta.get("request") if isinstance(request_meta, dict) else ""}

    def get_runtime_profile(self, user_id):
        return dict(self._runtime_profile)

    def record_interaction(self, **kwargs):
        self.interactions.append(kwargs)
        return {"interaction_id": "i1"}

    def record_feedback(self, **kwargs):
        self.feedback.append(kwargs)
        return {"event_id": "e1"}

    def get_status(self):
        return {"enabled": True, "mode": "hybrid"}

    def delete_user_data(self, user_id):
        return {"user_id": user_id, "deleted": True}


class _EvaluationSuite:
    def run(self, target_id="", suite_name="offline"):
        return {"target_id": target_id, "suite_name": suite_name}

    def summary(self):
        return {"suite_name": "offline"}


class _PrivacyStore:
    def __init__(self):
        self.decisions = []
        self.entries = []
        self.deleted = []

    def record_privacy_decision(self, **kwargs):
        self.decisions.append(kwargs)
        return {"decision_id": f"decision-{len(self.decisions)}"}

    def record_dataset_entry(self, **kwargs):
        self.entries.append(kwargs)
        return {"entry_id": f"entry-{len(self.entries)}"}

    def summary(self, **kwargs):
        return {
            "workspace_id": kwargs.get("workspace_id", "local-workspace"),
            "user_id": kwargs.get("user_id", "local"),
            "policy": {},
            "consent": {},
            "classification_counts": {"operational": len(self.decisions)},
            "learning_scope_counts": {"workspace": len(self.entries)},
            "shared_learning_eligible": len(self.entries),
            "redacted_entries": len(self.entries),
            "total_entries": len(self.entries),
            "recent_entries": [],
            "what_is_learned": ["operational signals"],
            "what_is_excluded": ["personal data"],
            "retention_policy": {},
        }

    def export_bundle(self, **kwargs):
        return {"workspace_id": kwargs.get("workspace_id", "local-workspace"), "user_id": kwargs.get("user_id", "local")}

    def delete_user_data(self, user_id, **kwargs):
        payload = {"user_id": user_id, "workspace_id": kwargs.get("workspace_id", "local-workspace"), "deleted": {"dataset_entries": 1}}
        self.deleted.append(payload)
        return payload


class _RuntimeDB:
    def __init__(self):
        self.privacy = _PrivacyStore()


def test_learning_control_delegates_and_summarizes_user():
    personalization = _Personalization()
    plane = LearningControlPlane(personalization=personalization, evaluation_suite=_EvaluationSuite())

    interaction = plane.record_interaction(user_id="u1", user_input="merhaba", assistant_output="selam")
    feedback = plane.record_feedback(user_id="u1", interaction_id="i1", event_type="like")
    summary = plane.summarize_user("u1")
    evaluation = plane.run_evaluation("adapter-v1", "offline")

    assert interaction["interaction_id"] == "i1"
    assert feedback["event_id"] == "e1"
    assert summary["memory"]["interaction_count"] == 2
    assert summary["reward"]["avg_reward"] == 0.75
    assert evaluation["target_id"] == "adapter-v1"
    assert evaluation["suite_name"] == "offline"


def test_learning_control_records_latency_reward():
    personalization = _Personalization()
    plane = LearningControlPlane(personalization=personalization, evaluation_suite=_EvaluationSuite())

    result = plane.record_latency(
        user_id="u1",
        interaction_id="i-latency",
        latency_ms=120.0,
        target_ms=800.0,
        metadata={"channel": "cli"},
    )

    assert result["event_id"] == "e1"
    assert personalization.feedback[-1]["event_type"] == "latency_reward"
    assert personalization.feedback[-1]["metadata"]["latency_ms"] == 120.0
    assert personalization.feedback[-1]["metadata"]["target_ms"] == 800.0


@pytest.mark.asyncio
async def test_learning_control_builds_digest_and_injects_prompt(monkeypatch):
    personalization = _Personalization()
    plane = LearningControlPlane(personalization=personalization, evaluation_suite=_EvaluationSuite())

    class _TaskBrain:
        def list_for_user(self, user_id, limit=10, states=None):
            _ = states
            return [
                SimpleNamespace(
                    objective="browser demo hazırla",
                    context={"action": "browser", "user_input": "browser demo"},
                    state="completed",
                    artifacts=[{"path": "/tmp/trace.png", "type": "image"}],
                    history=[{"state": "pending", "ts": 1.0}, {"state": "completed", "ts": 2.0}],
                    created_at=1.0,
                    updated_at=2.0,
                ),
                SimpleNamespace(
                    objective="OpenGauss query",
                    context={"action": "query", "user_input": "sql"},
                    state="partial",
                    artifacts=[],
                    history=[{"state": "pending", "ts": 3.0}, {"state": "partial", "ts": 4.0}],
                    created_at=3.0,
                    updated_at=4.0,
                ),
            ][:limit]

    monkeypatch.setattr("core.learning_control.task_brain", _TaskBrain())

    digest = plane.build_learning_digest("u1", request_meta={"request": "browser demo"})
    context = await plane.get_runtime_context("u1", {"request": "browser demo"})

    assert digest["task_count"] == 2
    assert digest["dominant_domain"] == "browser"
    assert digest["feedback_summary"]["correction_count"] == 1
    assert digest["next_actions"][0]["title"] == "Load correction hints"
    assert "Preferred language: tr-TR" in digest["prompt_hint"]
    assert "learning_digest" in context
    assert "[Learning Notes]" in context["request_prompt"]


def test_learning_control_persists_compact_learning_hint(monkeypatch):
    personalization = _Personalization()
    plane = LearningControlPlane(personalization=personalization, evaluation_suite=_EvaluationSuite())

    class _TaskBrain:
        def list_for_user(self, user_id, limit=10, states=None):
            _ = (user_id, limit, states)
            return [
                SimpleNamespace(
                    objective="browser demo hazırla",
                    context={"action": "browser"},
                    state="completed",
                    artifacts=[{"path": "/tmp/trace.png", "type": "image"}],
                    history=[{"state": "pending", "ts": 1.0}, {"state": "completed", "ts": 2.0}],
                    created_at=1.0,
                    updated_at=2.0,
                )
            ]

    monkeypatch.setattr("core.learning_control.task_brain", _TaskBrain())

    result = plane.record_turn(
        user_id="u1",
        user_input="browser demo hazırla",
        assistant_output="tamam",
        action="browser",
        intent="demo",
        success=True,
        duration_ms=75.0,
    )

    assert result["learning_digest"]["dominant_domain"] == "browser"
    assert personalization.interactions[-1]["metadata"]["learning_hint"]["dominant_domain"] == "browser"
    titles = [item["title"] for item in personalization.interactions[-1]["metadata"]["learning_hint"]["next_actions"]]
    assert "Default to screenshots" in titles


def test_learning_control_records_privacy_artifacts_for_latency(monkeypatch):
    personalization = _Personalization()
    plane = LearningControlPlane(personalization=personalization, evaluation_suite=_EvaluationSuite())
    runtime_db = _RuntimeDB()
    monkeypatch.setattr("core.learning_control.get_runtime_database", lambda: runtime_db)

    result = plane.record_latency(
        user_id="u1",
        interaction_id="latency-1",
        latency_ms=250.0,
        target_ms=800.0,
        metadata={"channel": "desktop"},
    )

    assert result["event_id"] == "e1"
    assert runtime_db.privacy.decisions[-1]["classification"] == "operational"
    assert runtime_db.privacy.entries[-1]["text"] == "latency_reward"
    assert runtime_db.privacy.entries[-1]["metadata"]["privacy_decision_id"] == "decision-1"


def test_learning_control_privacy_delete_includes_runtime_data(monkeypatch):
    personalization = _Personalization()
    plane = LearningControlPlane(personalization=personalization, evaluation_suite=_EvaluationSuite())
    runtime_db = _RuntimeDB()
    monkeypatch.setattr("core.learning_control.get_runtime_database", lambda: runtime_db)

    summary = plane.get_privacy_summary("u1", workspace_id="workspace-a")
    exported = plane.export_privacy_bundle("u1", workspace_id="workspace-a")
    deleted = plane.delete_user_data("u1")

    assert summary["workspace_id"] == "workspace-a"
    assert exported["privacy"]["workspace_id"] == "workspace-a"
    assert deleted["privacy"]["deleted"]["dataset_entries"] == 1
