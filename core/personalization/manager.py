from __future__ import annotations

from pathlib import Path
from typing import Any

from config.elyan_config import elyan_config
from core.user_profile import get_user_profile_store
from utils.logger import get_logger

from .adapters import AdapterArtifactStore, AdapterRegistry
from .memory import PersonalMemoryStore
from .retrieval import MemoryIndexer, MemoryRetriever, MemoryReranker
from .reward import RewardEventStore, RewardService
from .training import AdapterEvaluator, AdapterPromoter, AdapterTrainer, TrainerQueue

logger = get_logger("personalization.manager")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


class PersonalizationManager:
    DEFAULT_CONFIG: dict[str, Any] = {
        "enabled": True,
        "mode": "hybrid",
        "vector_backend": "lancedb",
        "graph_backend": "sqlite",
        "feedback_policy": "explicit_safe_implicit",
        "retrieval": {
            "top_k": 5,
            "max_context_tokens": 512,
        },
        "adapters": {
            "cache": {"max_hot": 32},
            "storage_root": "",
        },
        "training": {
            "min_examples": 50,
            "cooldown_minutes": 60,
        },
    }

    def __init__(self, config: dict[str, Any] | None = None):
        raw_config = dict(config or elyan_config.get("personalization", {}) or {})
        self.config = _deep_merge(self.DEFAULT_CONFIG, raw_config)
        self.enabled = bool(self.config.get("enabled", True))
        adapters_cfg = dict(self.config.get("adapters") or {})
        cache_cfg = dict(adapters_cfg.get("cache") or {})
        storage_root = str(adapters_cfg.get("storage_root") or "").strip()
        adapter_root = Path(storage_root).expanduser() if storage_root else None
        self.artifact_store = AdapterArtifactStore(storage_root=adapter_root)
        self.adapter_registry = AdapterRegistry(
            self.artifact_store,
            max_hot=int(cache_cfg.get("max_hot", 32) or 32),
        )
        self.memory_store = PersonalMemoryStore(
            vector_backend=str(self.config.get("vector_backend") or "lancedb"),
            graph_backend=str(self.config.get("graph_backend") or "sqlite"),
        )
        self.reward_service = RewardService()
        self.reward_events = RewardEventStore(self.reward_service)
        self.memory_indexer = MemoryIndexer(self.memory_store)
        self.memory_reranker = MemoryReranker()
        self.memory_retriever = MemoryRetriever(self.memory_store, self.memory_reranker)
        training_cfg = dict(self.config.get("training") or {})
        min_examples = int(training_cfg.get("min_examples", 50) or 50)
        cooldown_minutes = int(training_cfg.get("cooldown_minutes", 60) or 60)
        self.adapter_trainer = AdapterTrainer(
            memory_store=self.memory_store,
            reward_service=self.reward_service,
            artifact_store=self.artifact_store,
        )
        self.adapter_evaluator = AdapterEvaluator(
            memory_store=self.memory_store,
            reward_service=self.reward_service,
            min_examples=min_examples,
        )
        self.adapter_promoter = AdapterPromoter(self.artifact_store)
        self.trainer_queue = TrainerQueue(
            memory_store=self.memory_store,
            reward_service=self.reward_service,
            artifact_store=self.artifact_store,
            trainer=self.adapter_trainer,
            evaluator=self.adapter_evaluator,
            min_examples=min_examples,
            cooldown_minutes=cooldown_minutes,
        )
        self.feedback_policy = str(self.config.get("feedback_policy") or "explicit_safe_implicit")
        self._legacy_profile_store = get_user_profile_store()

    @staticmethod
    def _base_model_id(provider: str, model: str) -> str:
        provider_name = str(provider or "").strip().lower()
        model_name = str(model or "").strip()
        return f"{provider_name}:{model_name}" if provider_name else model_name

    def _runtime_profile(self, user_id: str) -> dict[str, Any]:
        try:
            legacy = dict(self._legacy_profile_store.profile_summary(str(user_id or "local")) or {})
        except Exception:
            legacy = {}
        personal = dict(self.memory_store.retrieve_context(str(user_id or "local"), "", k=1, token_budget=128).get("profile") or {})
        merged = dict(legacy)
        for key, value in personal.items():
            if value not in ("", None) and value != [] and value != {}:
                merged[key] = value
        return merged

    async def get_runtime_context(self, user_id: str, request_meta: dict[str, Any] | None = None) -> dict[str, Any]:
        uid = str(user_id or "local")
        meta = dict(request_meta or {})
        request = str(meta.get("request") or meta.get("user_input") or "").strip()
        provider = str(meta.get("provider") or elyan_config.get("models.default.provider", "ollama") or "ollama").strip().lower()
        model = str(meta.get("model") or elyan_config.get("models.default.model", "") or "").strip()
        base_model_id = str(meta.get("base_model_id") or self._base_model_id(provider, model)).strip()
        retrieval_cfg = dict(self.config.get("retrieval") or {})
        retrieval = self.memory_retriever.retrieve(
            request,
            uid,
            int(retrieval_cfg.get("max_context_tokens", 512) or 512),
            k=int(retrieval_cfg.get("top_k", 5) or 5),
        )
        adapter_binding = self.adapter_registry.resolve_binding(uid, base_model_id, provider) if self.enabled else {
            "state": "none",
            "status": "disabled",
            "reason": "personalization_disabled",
        }
        training_decision = self.trainer_queue.preview_training_decision(
            uid,
            base_model_id,
            interaction_count=int(retrieval.get("interaction_count", 0) or 0),
        )
        runtime_profile = self._runtime_profile(uid)
        context = {
            "runtime_profile": runtime_profile,
            "retrieved_memory_context": str(retrieval.get("text") or ""),
            "retrieved_memory": {
                "profile": dict(retrieval.get("profile") or {}),
                "vector_hits": list(retrieval.get("vector_hits") or []),
                "graph_edges": list(retrieval.get("graph_edges") or []),
                "backend": dict(retrieval.get("backend") or {}),
            },
            "adapter_binding": adapter_binding,
            "reward_policy": {
                "policy": self.feedback_policy,
                "supports_explicit": True,
                "supports_safe_implicit": True,
            },
            "training_decision": training_decision,
            "provider": provider,
            "model": model,
            "base_model_id": base_model_id,
        }
        context["request_prompt"] = self.build_personalized_prompt(request, context)
        return context

    def build_personalized_prompt(self, user_input: str, runtime_context: dict[str, Any] | None = None) -> str:
        context = dict(runtime_context or {})
        blocks: list[str] = []
        profile = context.get("runtime_profile", {}) if isinstance(context.get("runtime_profile"), dict) else {}
        if profile:
            preferred_language = str(profile.get("preferred_language") or "").strip()
            response_length_bias = str(profile.get("response_length_bias") or "").strip()
            top_topics = list(profile.get("top_topics") or [])
            lines: list[str] = []
            if preferred_language:
                lines.append(f"Preferred language: {preferred_language}")
            if response_length_bias:
                lines.append(f"Response length bias: {response_length_bias}")
            if top_topics:
                lines.append(f"Top topics: {', '.join(top_topics[:6])}")
            if lines:
                blocks.append("[User Profile]\n" + "\n".join(lines))
        memory_text = str(context.get("retrieved_memory_context") or "").strip()
        if memory_text:
            blocks.append(memory_text)
        if not blocks:
            return str(user_input or "")
        return "\n\n".join([*blocks, f"[Current Request]\n{str(user_input or '').strip()}"]).strip()

    def record_interaction(
        self,
        *,
        user_id: str,
        user_input: str,
        assistant_output: str,
        intent: str = "",
        action: str = "",
        success: bool = True,
        metadata: dict[str, Any] | None = None,
        privacy_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        meta = dict(metadata or {})
        record = self.memory_store.write_interaction(
            user_id=uid,
            user_input=user_input,
            assistant_output=assistant_output,
            intent=intent,
            action=action,
            success=success,
            reward_evidence=dict(meta.get("reward_evidence") or {}),
            metadata=meta,
            privacy_flags=privacy_flags,
        )
        base_model_id = str(meta.get("base_model_id") or self._base_model_id(meta.get("provider", ""), meta.get("model", ""))).strip()
        training_job = None
        if base_model_id:
            decision = self.trainer_queue.preview_training_decision(uid, base_model_id)
            if decision.get("eligible"):
                training_job = self.trainer_queue.enqueue_user_update(
                    user_id=uid,
                    base_model_id=base_model_id,
                    strategy=str(self.config.get("mode") or "hybrid"),
                    metadata={"source": "record_interaction", "action": action, "intent": intent},
                )
        return {
            **record,
            "training_job": training_job,
        }

    def index_interaction(
        self,
        *,
        user_id: str,
        user_input: str,
        assistant_output: str,
        intent: str = "",
        action: str = "",
        success: bool = True,
        metadata: dict[str, Any] | None = None,
        privacy_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        meta = dict(metadata or {})
        return self.memory_indexer.index_interaction(
            user_id=uid,
            user_input=user_input,
            assistant_output=assistant_output,
            intent=intent,
            action=action,
            success=success,
            reward_evidence=dict(meta.get("reward_evidence") or {}),
            metadata=meta,
            privacy_flags=privacy_flags,
        )

    def record_feedback(
        self,
        *,
        user_id: str,
        interaction_id: str,
        event_type: str,
        score: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        meta = dict(metadata or {})
        result = self.reward_events.record(
            user_id=uid,
            interaction_id=interaction_id,
            event_type=event_type,
            score=score,
            metadata=meta,
        )
        base_model_id = str(meta.get("base_model_id") or self._base_model_id(meta.get("provider", ""), meta.get("model", ""))).strip()
        queue_result = None
        if base_model_id:
            decision = self.trainer_queue.preview_training_decision(uid, base_model_id)
            if decision.get("eligible"):
                queue_result = self.trainer_queue.enqueue_user_update(
                    user_id=uid,
                    base_model_id=base_model_id,
                    strategy=str(self.config.get("mode") or "hybrid"),
                    metadata={"source": "record_feedback", "event_type": event_type},
                )
        return {**result, "training_job": queue_result}

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "mode": str(self.config.get("mode") or "hybrid"),
            "feedback_policy": self.feedback_policy,
            "memory": self.memory_store.get_stats(),
            "reward": self.reward_service.get_stats(),
            "adapters": self.adapter_registry.stats(),
            "training": self.trainer_queue.get_stats(),
            "retrieval": {
                "top_k": int((self.config.get("retrieval") or {}).get("top_k", 5) or 5),
                "max_context_tokens": int((self.config.get("retrieval") or {}).get("max_context_tokens", 512) or 512),
            },
        }

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        self.adapter_registry.evict_user(uid)
        return {
            "user_id": uid,
            "memory": self.memory_store.delete_user(uid),
            "reward": self.reward_service.delete_user(uid),
            "adapters": self.artifact_store.delete_user(uid),
            "training": self.trainer_queue.delete_user(uid),
        }


_manager: PersonalizationManager | None = None


def get_personalization_manager() -> PersonalizationManager:
    global _manager
    if _manager is None:
        _manager = PersonalizationManager()
    return _manager
