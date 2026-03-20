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

    def record_latency(
        self,
        *,
        user_id: str,
        interaction_id: str,
        latency_ms: float,
        target_ms: float = 800.0,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = dict(metadata or {})
        meta["latency_ms"] = float(latency_ms or 0.0)
        meta["target_ms"] = float(target_ms or 800.0)
        meta.setdefault("channel", str(meta.get("channel") or ""))
        return self.personalization.record_feedback(
            user_id=user_id,
            interaction_id=interaction_id,
            event_type="latency_reward",
            score=float(latency_ms or 0.0),
            metadata=meta,
        )

    def record_turn(
        self,
        *,
        user_id: str,
        user_input: str,
        assistant_output: str,
        action: str = "",
        success: bool = True,
        duration_ms: float = 0.0,
        intent: str = "",
        metadata: dict[str, Any] | None = None,
        privacy_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = dict(metadata or {})
        interaction = self.personalization.record_interaction(
            user_id=user_id,
            user_input=user_input,
            assistant_output=assistant_output,
            intent=intent or str(meta.get("intent") or action or ""),
            action=action,
            success=bool(success),
            metadata=meta,
            privacy_flags=privacy_flags,
        )
        latency_result = {}
        interaction_id = str(interaction.get("interaction_id") or "").strip()
        if interaction_id and duration_ms is not None:
            latency_result = self.record_latency(
                user_id=user_id,
                interaction_id=interaction_id,
                latency_ms=float(duration_ms or 0.0),
                target_ms=float(meta.get("latency_budget_ms", 800) or 800),
                metadata={**meta, "action": action, "success": bool(success)},
            )
        return {
            **interaction,
            "latency_reward": latency_result,
            "duration_ms": float(duration_ms or 0.0),
        }

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
