from __future__ import annotations

from typing import Any

from core.evaluation import get_evaluation_suite
from core.learning_digest import build_user_learning_digest
from core.personalization import get_personalization_manager
from core.task_brain import task_brain


class LearningControlPlane:
    def __init__(self, *, personalization: Any | None = None, evaluation_suite: Any | None = None) -> None:
        self.personalization = personalization or get_personalization_manager()
        self.evaluation_suite = evaluation_suite or get_evaluation_suite()

    @staticmethod
    def _compact_learning_digest(digest: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(digest, dict) or not digest:
            return {}
        next_actions: list[dict[str, Any]] = []
        for item in list(digest.get("next_actions") or [])[:3]:
            if not isinstance(item, dict):
                continue
            next_actions.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "reason": str(item.get("reason") or "").strip(),
                    "priority": str(item.get("priority") or "").strip(),
                }
            )
        prompt_hint = " ".join(str(digest.get("prompt_hint") or "").strip().split())
        return {
            "dominant_domain": str(digest.get("dominant_domain") or "").strip(),
            "learning_score": float(digest.get("learning_score", 0.0) or 0.0),
            "success_rate": float(digest.get("success_rate", 0.0) or 0.0),
            "top_topics": list(digest.get("top_topics") or [])[:5],
            "recent_lessons": list(digest.get("recent_lessons") or [])[:3],
            "next_actions": next_actions,
            "prompt_hint": prompt_hint[:320],
        }

    def _runtime_profile_for_user(self, user_id: str) -> dict[str, Any]:
        getter = getattr(self.personalization, "get_runtime_profile", None)
        if callable(getter):
            try:
                profile = getter(user_id)
                if isinstance(profile, dict):
                    return dict(profile)
            except Exception:
                pass
        fallback = getattr(self.personalization, "_runtime_profile", None)
        if callable(fallback):
            try:
                profile = fallback(user_id)
                if isinstance(profile, dict):
                    return dict(profile)
            except Exception:
                pass
        return {}

    def _feedback_events_for_user(self, user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        reward_service = getattr(self.personalization, "reward_service", None)
        if reward_service is None:
            return []
        list_feedback = getattr(reward_service, "list_feedback", None)
        if not callable(list_feedback):
            return []
        try:
            rows = list_feedback(user_id, limit=max(1, int(limit or 20)))
        except Exception:
            return []
        return [dict(row) for row in list(rows or []) if isinstance(row, dict)]

    def build_learning_digest(
        self,
        user_id: str,
        *,
        request_meta: dict[str, Any] | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        meta = dict(request_meta or {})
        feedback_events = self._feedback_events_for_user(uid, limit=max(20, int(limit or 10) * 3))
        if not feedback_events:
            reward_service = getattr(self.personalization, "reward_service", None)
            aggregate = {}
            aggregate_fn = getattr(reward_service, "aggregate_user_feedback", None)
            if callable(aggregate_fn):
                try:
                    aggregate = dict(aggregate_fn(uid) or {})
                except Exception:
                    aggregate = {}
            if aggregate:
                feedback_events = [
                    {
                        "event_type": "feedback_score",
                        "reward": float(aggregate.get("avg_reward", 0.0) or 0.0),
                        "metadata": dict(aggregate),
                        "created_at": 0.0,
                    }
                ]
        tasks = []
        try:
            tasks = list(task_brain.list_for_user(uid, limit=max(1, int(limit or 10))))
        except Exception:
            tasks = []
        runtime_profile = self._runtime_profile_for_user(uid)
        request_text = str(meta.get("request") or meta.get("user_input") or meta.get("text") or "").strip()
        return build_user_learning_digest(
            uid,
            tasks=tasks,
            feedback_events=feedback_events,
            runtime_profile=runtime_profile,
            request_text=request_text,
            limit=limit,
        )

    async def get_runtime_context(self, user_id: str, request_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        runtime_context = await self.personalization.get_runtime_context(user_id, request_meta or {})
        digest = self.build_learning_digest(
            user_id,
            request_meta=request_meta or {},
            limit=10,
        )
        runtime_context["learning_digest"] = digest
        learning_hint = str(digest.get("prompt_hint") or "").strip()
        if learning_hint:
            prompt = str(runtime_context.get("request_prompt") or "").strip()
            runtime_context["request_prompt"] = (
                f"{prompt}\n\n[Learning Notes]\n{learning_hint}".strip()
                if prompt
                else f"[Learning Notes]\n{learning_hint}"
            )
        return runtime_context

    def record_interaction(self, **kwargs: Any) -> dict[str, Any]:
        return self.personalization.record_interaction(**kwargs)

    def record_feedback(self, **kwargs: Any) -> dict[str, Any]:
        result = self.personalization.record_feedback(**kwargs)
        uid = str(kwargs.get("user_id") or "local")
        result["learning_digest"] = self.build_learning_digest(
            uid,
            request_meta={
                "request": str((kwargs.get("metadata") or {}).get("request") or ""),
                "event_type": str(kwargs.get("event_type") or ""),
            },
        )
        return result

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
        learning_digest = self.build_learning_digest(
            user_id,
            request_meta={"request": str(user_input or ""), "action": action, "intent": intent},
        )
        meta.setdefault("learning_hint", self._compact_learning_digest(learning_digest))
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
            "learning_digest": learning_digest,
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
            "learning_digest": self.build_learning_digest(uid, limit=8),
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
