from __future__ import annotations

from typing import Any

from core.evaluation import get_evaluation_suite
from core.personalization import get_personalization_manager


class LearningControlPlane:
    def __init__(self, *, personalization: Any | None = None, evaluation_suite: Any | None = None) -> None:
        self.personalization = personalization or get_personalization_manager()
        self.evaluation_suite = evaluation_suite or get_evaluation_suite()

    async def get_runtime_context(self, user_id: str, request_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self.personalization.get_runtime_context(user_id, request_meta or {})

    def record_interaction(self, **kwargs: Any) -> dict[str, Any]:
        return self.personalization.record_interaction(**kwargs)

    def record_feedback(self, **kwargs: Any) -> dict[str, Any]:
        return self.personalization.record_feedback(**kwargs)

    def summarize_user(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        memory_stats = self.personalization.memory_store.get_stats()
        reward_summary = self.personalization.reward_service.aggregate_user_feedback(uid)
        training_jobs = self.personalization.trainer_queue.list_jobs(uid, limit=5)
        return {
            "user_id": uid,
            "memory": {
                "interaction_count": self.personalization.memory_store.interaction_count(uid),
                "backend": dict(memory_stats.get("backend") or {}),
            },
            "reward": reward_summary,
            "recent_training_jobs": training_jobs,
        }

    def run_evaluation(self, target_id: str = "", suite_name: str = "offline") -> dict[str, Any]:
        return self.evaluation_suite.run(target_id, suite_name)

    def get_status(self) -> dict[str, Any]:
        return {
            "personalization": self.personalization.get_status(),
            "evaluation": self.evaluation_suite.summary(),
        }

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        return self.personalization.delete_user_data(user_id)


_plane: LearningControlPlane | None = None


def get_learning_control_plane() -> LearningControlPlane:
    global _plane
    if _plane is None:
        _plane = LearningControlPlane()
    return _plane
