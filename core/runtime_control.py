from __future__ import annotations

from typing import Any

from config.elyan_config import elyan_config
from core.device_sync import get_device_sync_store
from core.learning_control import get_learning_control_plane
from core.ml import RuntimeContext, get_action_ranker, get_clarification_classifier, get_intent_scorer, get_model_runtime
from core.reliability import get_outcome_store


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


class RuntimeControlPlane:
    DEFAULT_CONFIG: dict[str, Any] = {
        "enabled": True,
        "fast_path_threshold": 0.68,
        "clarify_threshold": 0.55,
        "latency_budgets_ms": {
            "direct_action": 800,
            "research": 2500,
            "coding": 3000,
            "workflow": 2500,
            "chat": 1200,
        },
        "sync": {
            "enabled": True,
            "max_devices_per_user": 8,
            "stale_minutes": 1440,
        },
    }

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        *,
        learning_control: Any | None = None,
        model_runtime: Any | None = None,
        intent_scorer: Any | None = None,
        action_ranker: Any | None = None,
        clarification_classifier: Any | None = None,
        outcome_store: Any | None = None,
        sync_store: Any | None = None,
    ) -> None:
        raw = dict(config or elyan_config.get("runtime_control", {}) or {})
        self.config = _deep_merge(self.DEFAULT_CONFIG, raw)
        self.learning_control = learning_control or get_learning_control_plane()
        self.model_runtime = model_runtime or get_model_runtime()
        self.intent_scorer = intent_scorer or get_intent_scorer()
        self.action_ranker = action_ranker or get_action_ranker()
        self.clarification_classifier = clarification_classifier or get_clarification_classifier()
        self.outcome_store = outcome_store or get_outcome_store()
        self.sync_store = sync_store or get_device_sync_store()

    @staticmethod
    def _coerce_mapping(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        if hasattr(value, "to_dict"):
            try:
                result = value.to_dict()
            except Exception:
                return {}
            if isinstance(result, dict):
                return result
        return {}

    @staticmethod
    def _normalize_request_class(label: str, *, request_contract: dict[str, Any], route_decision: dict[str, Any], capability_plan: dict[str, Any], text: str) -> str:
        normalized = str(label or "").strip().lower()
        if normalized in {"file", "browser", "open_app", "open_url", "read_file", "write_file", "list_files"}:
            return "direct_action"
        if normalized in {"research", "browser_search", "search_web"}:
            return "research"
        if normalized in {"code", "coding", "create_coding_project", "create_website"}:
            return "coding"
        if normalized in {"workflow", "task", "operator", "planner"}:
            return "workflow"

        route_mode = str(route_decision.get("mode") or request_contract.get("route_mode") or capability_plan.get("suggested_job_type") or "").strip().lower()
        if route_mode in {"file", "browser", "direct_action"}:
            return "direct_action"
        if route_mode in {"research", "document"}:
            return "research"
        if route_mode in {"code", "coding"}:
            return "coding"
        if route_mode in {"workflow", "operator", "task"}:
            return "workflow"

        content_kind = str(request_contract.get("content_kind") or "").strip().lower()
        if content_kind in {"browser", "file"}:
            return "direct_action"
        if content_kind in {"research"}:
            return "research"
        if content_kind in {"code", "coding"}:
            return "coding"

        low = str(text or "").lower()
        if any(token in low for token in ("araştır", "arastir", "research")):
            return "research"
        if any(token in low for token in ("python", "kod", "react", "typescript", "html", "css")):
            return "coding"
        if any(token in low for token in ("dosya", "kaydet", "safari", "chrome", "browser", "masaüst", "desktop", "http://", "https://")):
            return "direct_action"
        return "workflow"

    def _select_execution_path(self, request_class: str, intent_prediction: dict[str, Any], clarification_policy: dict[str, Any]) -> str:
        confidence = float(intent_prediction.get("confidence", 0.0) or 0.0)
        if bool(clarification_policy.get("should_clarify")):
            return "deep"
        if request_class == "direct_action" and confidence >= float(self.config.get("fast_path_threshold", 0.68) or 0.68):
            return "fast"
        if request_class == "chat" and confidence >= 0.6:
            return "fast"
        return "deep"

    def _latency_budget_ms(self, request_class: str) -> int:
        budgets = dict(self.config.get("latency_budgets_ms") or {})
        return int(budgets.get(request_class, budgets.get("workflow", 2500)) or 2500)

    async def prepare_turn(
        self,
        *,
        request_id: str,
        user_id: str,
        request: str,
        channel: str,
        provider: str,
        model: str,
        base_model_id: str,
        quick_intent: Any = None,
        parsed_intent: Any = None,
        route_decision: Any = None,
        request_contract: dict[str, Any] | None = None,
        capability_plan: Any = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        meta = dict(metadata or {})
        contract = dict(request_contract or {})
        route_map = self._coerce_mapping(route_decision)
        capability_map = self._coerce_mapping(capability_plan)
        personalization = await self.learning_control.get_runtime_context(
            uid,
            {
                "request": request,
                "channel": channel,
                "provider": provider,
                "model": model,
                "base_model_id": base_model_id,
                "metadata": meta,
            },
        )
        model_runtime = self.model_runtime.snapshot()
        intent_prediction = dict(
            self.intent_scorer.score(
                request,
                quick_intent=quick_intent,
                parsed_intent=parsed_intent,
            )
            or {}
        )
        request_class = self._normalize_request_class(
            str(intent_prediction.get("label") or ""),
            request_contract=contract,
            route_decision=route_map,
            capability_plan=capability_map,
            text=request,
        )
        route_rankings = self.action_ranker.rank(
            intent_prediction,
            [
                request_class,
                str(route_map.get("mode") or "").strip().lower(),
                str(contract.get("route_mode") or "").strip().lower(),
                str(capability_map.get("suggested_job_type") or "").strip().lower(),
                str(contract.get("content_kind") or "").strip().lower(),
            ],
            {
                "route_decision": route_map,
                "request_contract": contract,
                "capability_plan": capability_map,
            },
        )
        route_choice = dict(route_rankings[0] or {}) if route_rankings else {}
        clarification_policy = dict(
            self.clarification_classifier.classify(
                request,
                intent_prediction=intent_prediction,
                route_choice=route_choice,
                request_contract=contract,
            )
            or {}
        )
        execution_path = self._select_execution_path(request_class, intent_prediction, clarification_policy)
        latency_budget_ms = self._latency_budget_ms(request_class)
        device_id = str(meta.get("device_id") or meta.get("client_id") or "primary")
        session_id = str(meta.get("session_id") or meta.get("channel_session_id") or "default")
        sync = self.sync_store.record_request(
            request_id=request_id,
            user_id=uid,
            channel=channel,
            request_text=request,
            request_class=request_class,
            execution_path=execution_path,
            device_id=device_id,
            session_id=session_id,
            state="routing",
            metadata={
                "provider": provider,
                "model": model,
                "base_model_id": base_model_id,
                "route_mode": str(route_map.get("mode") or contract.get("route_mode") or ""),
                "workflow_profile": str(meta.get("workflow_profile") or ""),
            },
        )

        self.outcome_store.record_decision(
            request_id=request_id,
            user_id=uid,
            kind="intent_prediction",
            selected=str(intent_prediction.get("label") or "unknown"),
            confidence=float(intent_prediction.get("confidence", 0.0) or 0.0),
            raw_confidence=float(intent_prediction.get("raw_confidence", 0.0) or 0.0),
            channel=channel,
            source=str(intent_prediction.get("source") or "heuristic"),
            metadata={"advisory": str(intent_prediction.get("advisory") or "")},
        )
        self.outcome_store.record_decision(
            request_id=request_id,
            user_id=uid,
            kind="request_class",
            selected=request_class,
            confidence=float(intent_prediction.get("confidence", 0.0) or 0.0),
            raw_confidence=float(intent_prediction.get("raw_confidence", 0.0) or 0.0),
            channel=channel,
            source="runtime_control",
            metadata={"execution_path": execution_path},
        )
        if route_choice:
            self.outcome_store.record_decision(
                request_id=request_id,
                user_id=uid,
                kind="route_choice",
                selected=str(route_choice.get("candidate") or "unknown"),
                confidence=float(route_choice.get("score", 0.0) or 0.0),
                raw_confidence=float(route_choice.get("score", 0.0) or 0.0),
                channel=channel,
                source="action_ranker",
                metadata={"reasons": list(route_choice.get("reasons") or []), "rankings": route_rankings[:5]},
            )
        if clarification_policy:
            self.outcome_store.record_decision(
                request_id=request_id,
                user_id=uid,
                kind="clarification_policy",
                selected=str(clarification_policy.get("decision") or "proceed"),
                confidence=float(clarification_policy.get("confidence", 0.0) or 0.0),
                raw_confidence=float(clarification_policy.get("confidence", 0.0) or 0.0),
                channel=channel,
                source="clarification_classifier",
                metadata={"reasons": list(clarification_policy.get("reasons") or [])},
            )

        context = RuntimeContext(
            request_id=str(request_id or ""),
            user_id=uid,
            channel=str(channel or "cli"),
            request_class=request_class,
            execution_path=execution_path,
            latency_budget_ms=latency_budget_ms,
            intent_prediction=intent_prediction,
            route_choice=route_choice,
            clarification_policy=clarification_policy,
            personalization={
                "runtime_profile": dict(personalization.get("runtime_profile") or {}),
                "retrieved_memory_context": str(personalization.get("retrieved_memory_context") or ""),
                "retrieved_memory": dict(personalization.get("retrieved_memory") or {}),
                "adapter_binding": dict(personalization.get("adapter_binding") or {}),
                "reward_policy": dict(personalization.get("reward_policy") or {}),
                "training_decision": dict(personalization.get("training_decision") or {}),
                "provider": str(personalization.get("provider") or provider),
                "model": str(personalization.get("model") or model),
                "base_model_id": str(personalization.get("base_model_id") or base_model_id),
            },
            model_runtime=model_runtime,
            sync=sync,
            metadata={"route_rankings": route_rankings[:5], **meta},
        )
        payload = context.to_dict()
        payload["route_rankings"] = route_rankings[:5]
        payload["request_prompt"] = str(personalization.get("request_prompt") or request)
        return payload

    def record_stage(
        self,
        *,
        request_id: str,
        user_id: str,
        channel: str,
        state: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = dict(metadata or {})
        return self.sync_store.record_stage(
            request_id=request_id,
            user_id=user_id,
            channel=channel,
            state=state,
            device_id=str(meta.get("device_id") or meta.get("client_id") or "primary"),
            session_id=str(meta.get("session_id") or meta.get("channel_session_id") or "default"),
            metadata=meta,
        )

    def finalize_turn(
        self,
        *,
        request_id: str,
        user_id: str,
        channel: str,
        final_outcome: str,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        meta = dict(metadata or {})
        return self.sync_store.record_outcome(
            request_id=request_id,
            user_id=user_id,
            channel=channel,
            final_outcome=final_outcome,
            success=success,
            device_id=str(meta.get("device_id") or meta.get("client_id") or "primary"),
            session_id=str(meta.get("session_id") or meta.get("channel_session_id") or "default"),
            metadata=meta,
        )

    def get_status(self) -> dict[str, Any]:
        return {
            "enabled": bool(self.config.get("enabled", True)),
            "fast_path_threshold": float(self.config.get("fast_path_threshold", 0.68) or 0.68),
            "clarify_threshold": float(self.config.get("clarify_threshold", 0.55) or 0.55),
            "latency_budgets_ms": dict(self.config.get("latency_budgets_ms") or {}),
            "sync": self.sync_store.stats(),
        }


_runtime_control: RuntimeControlPlane | None = None


def get_runtime_control_plane() -> RuntimeControlPlane:
    global _runtime_control
    if _runtime_control is None:
        _runtime_control = RuntimeControlPlane()
    return _runtime_control
