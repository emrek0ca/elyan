from __future__ import annotations

from typing import Any

from core.evaluation import get_evaluation_suite
from core.learning_digest import build_user_learning_digest
from core.personalization import get_personalization_manager
from core.personalization.policy_learning import LearningSignal, get_policy_learning_store
from core.task_brain import task_brain


class LearningControlPlane:
    def __init__(self, *, personalization: Any | None = None, evaluation_suite: Any | None = None) -> None:
        self.personalization = personalization or get_personalization_manager()
        self.evaluation_suite = evaluation_suite or get_evaluation_suite()
        self.policy_learning = get_policy_learning_store()

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
        user_id = str(kwargs.get("user_id") or "local")
        if not self.policy_learning.is_learning_enabled(user_id):
            return {"success": True, "skipped": "learning_paused_or_opt_out", "user_id": user_id}
        return self.personalization.record_interaction(**kwargs)

    def record_feedback(self, **kwargs: Any) -> dict[str, Any]:
        uid = str(kwargs.get("user_id") or "local")
        if not self.policy_learning.is_learning_enabled(uid):
            return {
                "success": True,
                "skipped": "learning_paused_or_opt_out",
                "user_id": uid,
                "learning_digest": self.build_learning_digest(uid, request_meta={"event_type": str(kwargs.get("event_type") or "")}),
            }

        result = self.personalization.record_feedback(**kwargs)
        event_type = str(kwargs.get("event_type") or "").strip().lower()
        score_raw = kwargs.get("score")
        metadata = dict(kwargs.get("metadata") or {})
        task_type = str(metadata.get("task_type") or metadata.get("capability_domain") or "general")
        action = str(metadata.get("action") or metadata.get("tool") or event_type or "feedback")
        reward = None
        if isinstance(score_raw, (int, float)):
            score_value = float(score_raw)
            if "latency" in event_type:
                reward = max(-1.0, min(1.0, 1.0 - min(1.0, score_value / max(1.0, float(metadata.get("target_ms", 800.0))))))
            else:
                reward = max(-1.0, min(1.0, score_value))
        self.policy_learning.record_signal(
            LearningSignal(
                user_id=uid,
                task_type=task_type,
                action=action,
                agent_id=str(metadata.get("agent_id") or metadata.get("model") or "feedback"),
                outcome="success" if bool(metadata.get("success", True)) else "failed",
                latency_ms=float(metadata.get("latency_ms", 0.0) or 0.0),
                reward=reward,
                retry_count=int(metadata.get("retry_count", 0) or 0),
                approval_required=bool(metadata.get("approval_required", False)),
                approval_granted=bool(metadata.get("approval_granted", True)),
                source="explicit",
                metadata=metadata,
            )
        )
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
        uid = str(user_id or "local")
        if not self.policy_learning.is_learning_enabled(uid):
            return {
                "success": True,
                "skipped": "learning_paused_or_opt_out",
                "duration_ms": float(duration_ms or 0.0),
                "learning_digest": self.build_learning_digest(uid, request_meta={"request": str(user_input or "")}),
            }
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
        task_type = str(meta.get("task_type") or meta.get("capability_domain") or intent or "general")
        source = "implicit" if not meta.get("explicit_feedback") else "explicit"
        self.policy_learning.record_signal(
            LearningSignal(
                user_id=uid,
                task_type=task_type,
                action=str(action or "chat"),
                agent_id=str(meta.get("agent_id") or meta.get("provider") or "runtime"),
                outcome="success" if bool(success) else "failed",
                latency_ms=float(duration_ms or 0.0),
                retry_count=int(meta.get("retry_count", 0) or 0),
                approval_required=bool(meta.get("approval_required", False)),
                approval_granted=bool(meta.get("approval_granted", True)),
                source=source,
                metadata=meta,
            )
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

    def get_learning_summary(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        digest = self.build_learning_digest(uid, limit=8)
        policy = self.policy_learning.get_user_policy(uid)
        status = self.policy_learning.get_status(uid)
        next_actions: list[dict[str, Any]] = []
        for item in list(digest.get("next_actions") or [])[:2]:
            if not isinstance(item, dict):
                continue
            next_actions.append(
                {
                    "title": str(item.get("title") or "").strip(),
                    "reason": str(item.get("reason") or "").strip(),
                    "priority": str(item.get("priority") or "").strip(),
                }
            )
        return {
            "user_id": uid,
            "learning_mode": str(policy.get("learning_mode") or "hybrid"),
            "retention_policy": str(policy.get("retention_policy") or "long"),
            "paused": bool(policy.get("paused", False)),
            "opt_out": bool(policy.get("opt_out", False)),
            "learning_score": float(digest.get("learning_score", 0.0) or 0.0),
            "success_rate": float(digest.get("success_rate", 0.0) or 0.0),
            "dominant_domain": str(digest.get("dominant_domain") or "general"),
            "top_topics": list(digest.get("top_topics") or [])[:3],
            "recent_lessons": list(digest.get("recent_lessons") or [])[:2],
            "next_actions": next_actions,
            "prompt_hint": str(digest.get("prompt_hint") or "").strip()[:180],
            "signal_count": int(status.get("signals", 0) or 0),
            "action_count": int(status.get("actions", 0) or 0),
            "agent_count": int(status.get("agents", 0) or 0),
        }

    def run_evaluation(self, target_id: str = "", suite_name: str = "offline") -> dict[str, Any]:
        return self.evaluation_suite.run(target_id, suite_name)

    def get_status(self) -> dict[str, Any]:
        return {
            "personalization": self.personalization.get_status(),
            "evaluation": self.evaluation_suite.summary(),
            "policy_learning": self.policy_learning.get_status(),
        }

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        return {
            "personalization": self.personalization.delete_user_data(user_id),
            "policy_learning": self.policy_learning.delete_user_data(user_id),
        }

    def set_learning_paused(self, paused: bool, *, user_id: str = "local") -> dict[str, Any]:
        return self.policy_learning.set_user_policy(user_id, paused=bool(paused))

    def set_learning_opt_out(self, user_id: str, opt_out: bool) -> dict[str, Any]:
        return self.policy_learning.set_user_policy(user_id, opt_out=bool(opt_out))

    def set_learning_preferences(
        self,
        *,
        user_id: str,
        learning_mode: str | None = None,
        retention_policy: str | None = None,
    ) -> dict[str, Any]:
        return self.policy_learning.set_user_policy(
            user_id,
            learning_mode=learning_mode,
            retention_policy=retention_policy,
        )


_plane: LearningControlPlane | None = None


def get_learning_control_plane() -> LearningControlPlane:
    global _plane
    if _plane is None:
        _plane = LearningControlPlane()
    return _plane
