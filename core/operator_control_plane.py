from __future__ import annotations

import inspect
from typing import Any

from config.elyan_config import elyan_config
from core.capability_router import CapabilityPlan, CapabilityRouter, get_capability_router
from core.learning_control import LearningControlPlane, get_learning_control_plane
from core.ml import get_model_runtime
from core.model_orchestrator import ModelOrchestrator, model_orchestrator
from core.operator_policy import OperatorPolicy, OperatorPolicyEngine, get_operator_policy_engine
from core.realtime_actuator import RealTimeActuator, get_realtime_actuator
from core.runtime_control import RuntimeControlPlane, get_runtime_control_plane
from core.skills.registry import SkillRegistry, skill_registry
from core.contracts.operator_runtime import CapabilityManifest, OperatorOutcome, OperatorRequestModel, SkillManifest
from utils.logger import get_logger

logger = get_logger("operator_control_plane")


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


class OperatorControlPlane:
    DEFAULT_CONFIG: dict[str, Any] = {
        "enabled": True,
        "local_first": True,
        "real_time": {
            "enabled": True,
            "mode": "auto",
            "fps": 60,
            "screenpipe_url": "http://localhost:3030",
        },
        "model_roles": {
            "direct_action": "router",
            "research": "reasoning",
            "coding": "code",
            "workflow": "planning",
            "chat": "router",
        },
    }

    def __init__(
        self,
        *,
        runtime_control: RuntimeControlPlane | None = None,
        learning_control: LearningControlPlane | None = None,
        skill_registry: SkillRegistry | None = None,
        capability_router: CapabilityRouter | None = None,
        model_orchestrator: ModelOrchestrator | None = None,
        real_time_actuator: RealTimeActuator | None = None,
        policy_engine: OperatorPolicyEngine | None = None,
        config: dict[str, Any] | None = None,
    ) -> None:
        self.runtime_control = runtime_control or get_runtime_control_plane()
        self.learning_control = learning_control or get_learning_control_plane()
        self.skill_registry = skill_registry or globals()["skill_registry"]
        self.capability_router = capability_router or get_capability_router()
        self.model_orchestrator = model_orchestrator or globals()["model_orchestrator"]
        self.real_time_actuator = real_time_actuator or get_realtime_actuator()
        self.policy_engine = policy_engine or get_operator_policy_engine()
        raw_cfg = dict(config or elyan_config.get("operator", {}) or {})
        self.config = _deep_merge(self.DEFAULT_CONFIG, raw_cfg)

    @staticmethod
    def _coerce_request(request: Any, *, user_id: str, channel: str, device_id: str, context: dict[str, Any]) -> OperatorRequestModel:
        if isinstance(request, OperatorRequestModel):
            model = request
        elif hasattr(request, "to_dict"):
            try:
                model = OperatorRequestModel.from_any(request.to_dict())
            except Exception:
                model = OperatorRequestModel.from_any({})
        elif isinstance(request, dict):
            model = OperatorRequestModel.from_any(request)
        else:
            model = OperatorRequestModel.from_any({"input_text": str(request or "")})
        payload = model.model_dump()
        payload.setdefault("user_id", str(user_id or payload.get("user_id") or "local"))
        payload.setdefault("channel", str(channel or payload.get("channel") or "cli"))
        payload.setdefault("device_id", str(device_id or payload.get("device_id") or context.get("device_id") or "primary"))
        payload.setdefault("session_id", str(context.get("session_id") or payload.get("session_id") or "default"))
        payload.setdefault("host", str(context.get("host") or payload.get("host") or "localhost"))
        payload.setdefault("local_first", bool(context.get("local_first", True)))
        payload.setdefault("metadata", dict(context.get("metadata") or {}))
        if not payload.get("input_text"):
            payload["input_text"] = str(context.get("request") or context.get("text") or "")
        return OperatorRequestModel.model_validate(payload)

    def _model_role(self, request_class: str, capability_domain: str, skill_manifest: dict[str, Any] | None) -> str:
        role_map = dict(self.config.get("model_roles") or {})
        if skill_manifest and str(skill_manifest.get("latency_level") or "").strip().lower() == "real_time":
            return "router"
        if capability_domain in {"screen_operator", "real_time_control", "browser"}:
            return "router"
        return str(role_map.get(request_class) or role_map.get("workflow") or "router").strip().lower() or "router"

    def _build_capability_manifest(
        self,
        *,
        request: OperatorRequestModel,
        runtime_turn: dict[str, Any],
        capability_plan: CapabilityPlan | None,
        skill_manifest: dict[str, Any] | None,
        integration_resolution: dict[str, Any] | None,
        selected_model: dict[str, Any],
        request_class: str,
    ) -> CapabilityManifest:
        route_contract = dict(runtime_turn.get("request_contract") or {})
        if capability_plan is None:
            capability_plan = self.capability_router.route(request.input_text)
        integration = dict(integration_resolution or {})
        latency_level = str((skill_manifest or {}).get("latency_level") or "standard").strip().lower() or "standard"
        requires_real_time = latency_level == "real_time" or str(capability_plan.domain or "") in {"screen_operator", "real_time_control"}
        return CapabilityManifest(
            capability_id=str(capability_plan.workflow_id or route_contract.get("workflow_id") or request_class or "operator"),
            domain=str(capability_plan.domain or route_contract.get("domain") or request_class or "general"),
            request_class=request_class,
            confidence=float(capability_plan.confidence or route_contract.get("confidence", 0.0) or 0.0),
            objective=str(capability_plan.objective or route_contract.get("objective") or request.input_text),
            workflow_id=str(capability_plan.workflow_id or route_contract.get("workflow_id") or ""),
            primary_action=str(capability_plan.primary_action or route_contract.get("primary_action") or ""),
            preferred_tools=list(capability_plan.preferred_tools or []),
            output_artifacts=list(capability_plan.output_artifacts or []),
            quality_checklist=list(capability_plan.quality_checklist or []),
            learning_tags=list(capability_plan.learning_tags or []),
            complexity_tier=str(capability_plan.complexity_tier or "low"),
            suggested_job_type=str(capability_plan.suggested_job_type or "communication"),
            multi_agent_recommended=bool(capability_plan.multi_agent_recommended),
            orchestration_mode=str(capability_plan.orchestration_mode or "single_agent"),
            workflow_profile_applicable=bool(capability_plan.workflow_profile_applicable),
            requires_design_phase=bool(capability_plan.requires_design_phase),
            requires_worktree=bool(capability_plan.requires_worktree),
            content_kind=str(capability_plan.content_kind or route_contract.get("content_kind") or "task"),
            output_formats=list(capability_plan.output_formats or []),
            style_profile=str(capability_plan.style_profile or route_contract.get("style_profile") or "executive"),
            source_policy=str(capability_plan.source_policy or route_contract.get("source_policy") or "trusted"),
            quality_contract=list(capability_plan.quality_contract or []),
            memory_scope=str(capability_plan.memory_scope or route_contract.get("memory_scope") or "task_routed"),
            preview=str(capability_plan.preview or route_contract.get("preview") or ""),
            request_contract=dict(route_contract),
            latency_level=latency_level,
            requires_real_time=requires_real_time,
            integration_type=str(integration.get("integration_type") or (skill_manifest or {}).get("integration_type") or ""),
            required_scopes=list(integration.get("required_scopes") or (skill_manifest or {}).get("required_scopes") or []),
            auth_strategy=str(integration.get("auth_strategy") or (skill_manifest or {}).get("auth_strategy") or ""),
            fallback_policy=str(integration.get("fallback_policy") or (skill_manifest or {}).get("fallback_policy") or ""),
            supported_platforms=list(integration.get("supported_platforms") or (skill_manifest or {}).get("supported_platforms") or []),
            dependencies=list(integration.get("dependencies") or (skill_manifest or {}).get("dependencies") or []),
            approval_level=int(integration.get("approval_level") or (skill_manifest or {}).get("approval_level") or 0),
            model_role=str(selected_model.get("role") or "router"),
            selected_model=dict(selected_model),
            workflow_bundle=dict(integration.get("workflow_bundle") or (skill_manifest or {}).get("workflow_bundle") or {}),
            metadata={
                "approval_tools": list((skill_manifest or {}).get("approval_tools") or []),
                "blocked_tools": list((skill_manifest or {}).get("blocked_tools") or []),
                "evidence_contract": dict((skill_manifest or {}).get("evidence_contract") or {}),
                "integration": dict(integration or {}),
            },
        )

    def _build_skill_manifest(
        self,
        resolution: dict[str, Any],
        *,
        request_class: str,
        integration_resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        skill = dict(resolution.get("skill") or {})
        workflow = dict(resolution.get("workflow") or {})
        integration = dict(integration_resolution or resolution.get("integration") or {})
        if not skill:
            skill = dict(skill_registry.get_skill("system") or {})
        if integration:
            skill = {
                **skill,
                "integration_type": str(integration.get("integration_type") or skill.get("integration_type") or ""),
                "required_scopes": list(integration.get("required_scopes") or skill.get("required_scopes") or []),
                "auth_strategy": str(integration.get("auth_strategy") or skill.get("auth_strategy") or ""),
                "fallback_policy": str(integration.get("fallback_policy") or skill.get("fallback_policy") or ""),
                "supported_platforms": list(integration.get("supported_platforms") or skill.get("supported_platforms") or []),
                "dependencies": list(integration.get("dependencies") or skill.get("dependencies") or []),
                "approval_level": int(integration.get("approval_level") or skill.get("approval_level") or 0),
                "real_time": bool(integration.get("real_time", skill.get("real_time", False))),
                "workflow_bundle": dict(integration.get("workflow_bundle") or skill.get("workflow_bundle") or {}),
            }
        manifest = SkillManifest(
            skill_id=str(skill.get("name") or workflow.get("id") or request_class or "general"),
            name=str(skill.get("name") or workflow.get("name") or request_class or "general"),
            version=str(skill.get("version") or workflow.get("version") or "1.0.0"),
            description=str(skill.get("description") or workflow.get("description") or ""),
            category=str(skill.get("category") or workflow.get("category") or "general"),
            source=str(skill.get("source") or workflow.get("source") or "builtin"),
            integration_type=str(skill.get("integration_type") or ""),
            required_scopes=list(skill.get("required_scopes") or []),
            auth_strategy=str(skill.get("auth_strategy") or ""),
            fallback_policy=str(skill.get("fallback_policy") or ""),
            supported_platforms=list(skill.get("supported_platforms") or []),
            dependencies=list(skill.get("dependencies") or []),
            required_tools=list(skill.get("required_tools") or workflow.get("required_tools") or []),
            optional_tools=list(skill.get("optional_tools") or []),
            commands=list(skill.get("commands") or []),
            approval_tools=list(skill.get("approval_tools") or []),
            blocked_tools=list(skill.get("blocked_tools") or []),
            evidence_contract=dict(skill.get("evidence_contract") or {}),
            latency_level=str(skill.get("latency_level") or "standard"),
            auto_intent=bool(workflow.get("auto_intent") or False),
            enabled=bool(skill.get("enabled", True)),
            runtime_ready=bool(skill.get("runtime_ready", True)),
            workflow_id=str(workflow.get("id") or skill.get("workflow_id") or ""),
            trigger_markers=list(workflow.get("trigger_markers") or []),
            steps=[str(item) for item in list(workflow.get("steps") or [])],
            output_artifacts=list(workflow.get("output_artifacts") or []),
            quality_checklist=list(workflow.get("quality_checklist") or []),
            approval_level=int(skill.get("approval_level") or 0),
            real_time=bool(skill.get("real_time", False)),
            tool_policy=dict(workflow.get("tool_policy") or {}),
            output_contract=dict(workflow.get("output_contract") or {}),
            workflow_bundle=dict(skill.get("workflow_bundle") or integration.get("workflow_bundle") or {}),
            metadata={
                "request_class": request_class,
                "latency_level": str(skill.get("latency_level") or "standard"),
                "workflow_enabled": bool(workflow.get("enabled", True)),
                "workflow_runtime_ready": bool(workflow.get("runtime_ready", True)),
                "integration": dict(integration or {}),
            },
        )
        return manifest.model_dump()

    async def plan_request(
        self,
        *,
        request_id: str,
        user_id: str,
        request: Any,
        channel: str,
        device_id: str = "",
        context: dict[str, Any] | None = None,
        quick_intent: Any = None,
        parsed_intent: Any = None,
        route_decision: Any = None,
        request_contract: dict[str, Any] | None = None,
        capability_plan: CapabilityPlan | None = None,
        metadata: dict[str, Any] | None = None,
        provider: str = "",
        model: str = "",
        base_model_id: str = "",
    ) -> dict[str, Any]:
        meta = dict(metadata or {})
        ctx = dict(context or {})
        req = self._coerce_request(
            request,
            user_id=user_id,
            channel=channel,
            device_id=device_id or str(meta.get("device_id") or ctx.get("device_id") or "primary"),
            context={**ctx, "metadata": meta, "request": getattr(request, "input_text", None) or str(request or "")},
        )
        request_text = str(req.input_text or ctx.get("request") or meta.get("request") or "")
        if not provider:
            provider = str(ctx.get("provider") or meta.get("provider") or elyan_config.get("models.default.provider", "ollama") or "ollama")
        if not model:
            model = str(ctx.get("model") or meta.get("model") or elyan_config.get("models.default.model", "") or "")
        if not base_model_id:
            base_model_id = f"{str(provider or '').strip().lower()}:{str(model or '').strip()}" if provider else str(model or "")

        runtime_turn = await self.runtime_control.prepare_turn(
            request_id=request_id,
            user_id=str(user_id or "local"),
            request=request_text,
            channel=str(channel or "cli"),
            provider=str(provider or "ollama"),
            model=str(model or ""),
            base_model_id=str(base_model_id or ""),
            quick_intent=quick_intent,
            parsed_intent=parsed_intent,
            route_decision=route_decision,
            request_contract=request_contract,
            capability_plan=capability_plan,
            metadata=meta,
        )
        request_class = str(runtime_turn.get("request_class") or "workflow").strip().lower() or "workflow"
        route_plan = capability_plan or self.capability_router.route(request_text)
        skill_resolution = self.skill_registry.resolve_from_intent(
            {"text": request_text, "action": str((parsed_intent or {}).get("action") if isinstance(parsed_intent, dict) else ""), "request_class": request_class},
            {
                "quick_intent": quick_intent,
                "parsed_intent": parsed_intent if isinstance(parsed_intent, dict) else {},
                "attachments": list(ctx.get("attachments") or []),
                "capability_domain": str(getattr(route_plan, "domain", "") or ""),
                "metadata": meta,
            },
        )
        integration_resolution = dict(skill_resolution.get("integration") or {})
        skill_manifest = self._build_skill_manifest(
            skill_resolution,
            request_class=request_class,
            integration_resolution=integration_resolution,
        )
        model_role = self._model_role(request_class, str(getattr(route_plan, "domain", "") or ""), skill_manifest)
        selected_model = dict(self.model_orchestrator.get_best_available(model_role) or {})
        if not selected_model:
            selected_model = dict(self.model_orchestrator.get_best_available("router") or {})
        operator_policy: OperatorPolicy = self.policy_engine.resolve(str(req.safety_mode or ctx.get("autonomy_mode") or "Confirmed"))
        capability_manifest = self._build_capability_manifest(
            request=req,
            runtime_turn=runtime_turn,
            capability_plan=route_plan,
            skill_manifest=skill_manifest,
            integration_resolution=integration_resolution,
            selected_model=selected_model,
            request_class=request_class,
        )
        real_time_cfg = dict(self.config.get("real_time") or {})
        needs_real_time = bool(capability_manifest.requires_real_time or skill_manifest.get("latency_level") == "real_time")
        fast_path = str(runtime_turn.get("execution_path") or "").strip().lower() == "fast" and not bool(capability_manifest.multi_agent_recommended)
        model_selection = {
            "provider": str(selected_model.get("provider") or selected_model.get("type") or provider or "ollama"),
            "model": str(selected_model.get("model") or model or ""),
            "base_model_id": f"{str(selected_model.get('provider') or selected_model.get('type') or provider or '').strip().lower()}:{str(selected_model.get('model') or model or '').strip()}".strip(":"),
            "role": model_role,
            "local_first": bool(self.config.get("local_first", True)),
            "fallback": bool(selected_model.get("provider") and str(selected_model.get("provider")).strip().lower() not in {"ollama"}),
        }
        runtime_model = dict(runtime_turn.get("model_runtime") or {})
        runtime_model["selected_model"] = dict(model_selection)
        runtime_model["operator_policy"] = {
            "level": operator_policy.level,
            "allow_system_actions": operator_policy.allow_system_actions,
            "allow_destructive_actions": operator_policy.allow_destructive_actions,
            "require_confirmation_for_risky": operator_policy.require_confirmation_for_risky,
        }
        result = {
            **runtime_turn,
            "operator_request": req.model_dump(),
            "request_class": request_class,
            "skill": skill_manifest,
            "capability": capability_manifest.model_dump(),
            "integration": dict(integration_resolution or {}),
            "model_selection": model_selection,
            "real_time": {
                "enabled": bool(real_time_cfg.get("enabled", True)),
                "mode": str(real_time_cfg.get("mode") or "auto"),
                "fps": int(real_time_cfg.get("fps", 60) or 60),
                "screenpipe_url": str(real_time_cfg.get("screenpipe_url") or "http://localhost:3030"),
                "needs_real_time": needs_real_time,
            },
            "fast_path": bool(fast_path),
            "operator_policy": {
                "level": operator_policy.level,
                "allow_system_actions": operator_policy.allow_system_actions,
                "allow_destructive_actions": operator_policy.allow_destructive_actions,
                "require_confirmation_for_risky": operator_policy.require_confirmation_for_risky,
            },
            "model_runtime": runtime_model,
            "operator_trace": {
                "request_id": request_id,
                "route_domain": str(getattr(route_plan, "domain", "") or ""),
                "route_preview": str(getattr(route_plan, "preview", "") or ""),
                "skill_latency_level": str(skill_manifest.get("latency_level") or "standard"),
                "real_time_required": needs_real_time,
                "model_role": model_role,
            },
        }
        result["realtime_actuator"] = self.real_time_actuator.get_status() if hasattr(self.real_time_actuator, "get_status") else {}
        return result

    async def handle(
        self,
        request: Any,
        *,
        user_id: str,
        channel: str,
        device_id: str,
        context: dict[str, Any] | None = None,
    ) -> OperatorOutcome:
        ctx = dict(context or {})
        plan = await self.plan_request(
            request_id=str(ctx.get("request_id") or ctx.get("run_id") or ""),
            user_id=user_id,
            request=request,
            channel=channel,
            device_id=device_id,
            context=ctx,
            quick_intent=ctx.get("quick_intent"),
            parsed_intent=ctx.get("parsed_intent"),
            route_decision=ctx.get("route_decision"),
            request_contract=ctx.get("request_contract"),
            capability_plan=ctx.get("capability_plan"),
            metadata=dict(ctx.get("metadata") or {}),
            provider=str(ctx.get("provider") or ""),
            model=str(ctx.get("model") or ""),
            base_model_id=str(ctx.get("base_model_id") or ""),
        )
        execute = bool(ctx.get("execute", False))
        executor = ctx.get("tool_runner") or ctx.get("executor")
        actuation = {}
        if execute and callable(executor):
            try:
                maybe_result = executor(plan)
                actuation = await _maybe_await(maybe_result) or {}
            except Exception as exc:
                actuation = {"success": False, "status": "failed", "error": str(exc), "source": "executor"}
        elif execute and bool(plan.get("real_time", {}).get("needs_real_time")) and hasattr(self.real_time_actuator, "submit"):
            try:
                maybe_result = self.real_time_actuator.submit(
                    {
                        "instruction": plan.get("operator_request", {}).get("input_text", ""),
                        "mode": "control",
                        "context": dict(ctx.get("metadata") or {}),
                        "request": plan.get("operator_request", {}),
                    }
                )
                actuation = await _maybe_await(maybe_result) or {}
            except Exception as exc:
                actuation = {"success": False, "status": "failed", "error": str(exc), "source": "realtime_actuator"}
        status = str(actuation.get("status") or ("completed" if bool(actuation.get("success")) else "planned"))
        success = bool(actuation.get("success", status == "completed"))
        evidence = list(actuation.get("evidence") or [])
        artifacts = list(actuation.get("artifacts") or [])
        verification = dict(actuation.get("verification") or {})
        response_text = str(actuation.get("response_text") or actuation.get("message") or plan.get("request_prompt") or plan.get("operator_request", {}).get("input_text") or "")
        latency_ms = float(actuation.get("latency_ms") or 0.0)
        outcome = OperatorOutcome(
            request_id=str(ctx.get("request_id") or ctx.get("run_id") or ""),
            user_id=str(user_id or "local"),
            channel=str(channel or "cli"),
            device_id=str(device_id or "primary"),
            session_id=str(ctx.get("session_id") or ctx.get("channel_session_id") or "default"),
            status=status,
            success=success,
            response_text=response_text,
            request_class=str(plan.get("request_class") or ""),
            skill=dict(plan.get("skill") or {}),
            capability=dict(plan.get("capability") or {}),
            model_runtime=dict(plan.get("model_runtime") or {}),
            execution_path=str(plan.get("execution_path") or plan.get("operator_trace", {}).get("route_domain") or ""),
            evidence=evidence,
            artifacts=artifacts,
            verification=verification,
            decision_trace=dict(plan.get("operator_trace") or {}),
            latency_ms=latency_ms,
            fallback_reason=str(actuation.get("fallback_reason") or actuation.get("reason") or ""),
            metadata={
                **dict(ctx.get("metadata") or {}),
                "operator_plan": {
                    "request_class": plan.get("request_class"),
                    "fast_path": plan.get("fast_path"),
                    "real_time": plan.get("real_time"),
                    "integration": plan.get("integration"),
                },
                "actuation": actuation,
            },
        )
        return outcome

    def get_status(self) -> dict[str, Any]:
        runtime = get_model_runtime().snapshot()
        real_time_status = self.real_time_actuator.get_status() if hasattr(self.real_time_actuator, "get_status") else {}
        return {
            "enabled": bool(self.config.get("enabled", True)),
            "local_first": bool(self.config.get("local_first", True)),
            "runtime": runtime,
            "skills": {
                "enabled_count": len(skill_registry.list_skills(available=True, enabled_only=True)),
                "runtime_ready_count": len([item for item in skill_registry.list_skills(available=True, enabled_only=True) if item.get("runtime_ready", False)]),
                "workflow_count": len(skill_registry.list_workflows(enabled_only=True)),
            },
            "real_time": dict(self.config.get("real_time") or {}),
            "real_time_actuator": real_time_status,
        }


_OPERATOR_CONTROL_PLANE: OperatorControlPlane | None = None


def get_operator_control_plane() -> OperatorControlPlane:
    global _OPERATOR_CONTROL_PLANE
    if _OPERATOR_CONTROL_PLANE is None:
        _OPERATOR_CONTROL_PLANE = OperatorControlPlane()
    return _OPERATOR_CONTROL_PLANE


__all__ = ["OperatorControlPlane", "get_operator_control_plane"]
