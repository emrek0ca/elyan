from __future__ import annotations

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
            {"aggregate_user_feedback": staticmethod(lambda _user_id: {"feedback_events": 1, "avg_reward": 0.75})},
        )()
        self.trainer_queue = type(
            "_TrainerQueue",
            (),
            {"list_jobs": staticmethod(lambda _user_id, limit=5: [{"job_id": "job-1", "limit": limit}])},
        )()

    async def get_runtime_context(self, user_id, request_meta=None):
        return {"user_id": user_id, "request": request_meta.get("request") if isinstance(request_meta, dict) else ""}

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
