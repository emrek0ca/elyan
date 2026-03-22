from __future__ import annotations

import asyncio
from types import SimpleNamespace

from core.contracts.operator_runtime import OperatorOutcome
from core.operator_control_plane import OperatorControlPlane


class _RuntimeControl:
    async def prepare_turn(self, **kwargs):
        _ = kwargs
        return {
            "request_id": kwargs.get("request_id", "req-1"),
            "user_id": kwargs.get("user_id", "u1"),
            "channel": kwargs.get("channel", "cli"),
            "session_id": kwargs.get("request_id", "req-1"),
            "request_class": "direct_action",
            "execution_path": "fast",
            "request_prompt": kwargs.get("request", ""),
            "operator_trace": {"route_domain": "screen_operator"},
            "model_runtime": {"selected_model": {"provider": "ollama", "model": "llama3.2"}},
            "sync": {"state": "routing"},
        }


class _RuntimeControlWorkflow(_RuntimeControl):
    async def prepare_turn(self, **kwargs):
        payload = await super().prepare_turn(**kwargs)
        payload["request_class"] = "workflow"
        payload["execution_path"] = "deep"
        payload["operator_trace"] = {"route_domain": "workflow"}
        return payload


class _ModelOrchestrator:
    def get_best_available(self, role):
        return {"provider": "ollama", "model": "llama3.2", "role": role}


class _Policy:
    def __init__(self):
        self.level = "Confirmed"
        self.allow_system_actions = True
        self.allow_destructive_actions = False
        self.require_confirmation_for_risky = True


class _PolicyEngine:
    def resolve(self, _level):
        return _Policy()


class _Actuator:
    def get_status(self):
        return {"enabled": True, "active": False, "process_mode": False}


def _capability_plan():
    return SimpleNamespace(
        domain="screen_operator",
        confidence=0.91,
        objective="control desktop",
        workflow_id="desktop_loop",
        primary_action="vision_operator_loop",
        preferred_tools=["open_app"],
        output_artifacts=["screen_state"],
        quality_checklist=["verify"],
        learning_tags=["screen"],
        complexity_tier="low",
        suggested_job_type="system_automation",
        multi_agent_recommended=False,
        orchestration_mode="single_agent",
        workflow_profile_applicable=False,
        requires_design_phase=False,
        requires_worktree=False,
        content_kind="task",
        output_formats=[],
        style_profile="executive",
        source_policy="trusted",
        quality_contract=[],
        memory_scope="task_routed",
        preview="desktop control",
    )


def test_operator_control_plane_plans_real_time_request():
    plane = OperatorControlPlane(
        runtime_control=_RuntimeControl(),
        model_orchestrator=_ModelOrchestrator(),
        policy_engine=_PolicyEngine(),
        real_time_actuator=_Actuator(),
    )

    result = asyncio.run(
        plane.plan_request(
            request_id="req-1",
            user_id="u1",
            request="Safari’de openai.com aç",
            channel="telegram",
            device_id="mac",
            context={"request_id": "req-1", "device_id": "mac", "provider": "ollama", "model": "llama3.2"},
            capability_plan=_capability_plan(),
            metadata={"channel": "telegram"},
        )
    )

    assert result["request_class"] == "direct_action"
    assert result["real_time"]["needs_real_time"] is True
    assert result["model_selection"]["provider"] == "ollama"
    assert result["skill"]["name"] in {"browser", "system"}
    assert result["capability"]["requires_real_time"] is True


def test_operator_control_plane_handle_returns_operator_outcome():
    plane = OperatorControlPlane(
        runtime_control=_RuntimeControl(),
        model_orchestrator=_ModelOrchestrator(),
        policy_engine=_PolicyEngine(),
        real_time_actuator=_Actuator(),
    )

    async def _executor(plan):
        _ = plan
        return {
            "success": True,
            "status": "completed",
            "response_text": "done",
            "evidence": [{"kind": "screenshot", "path": "/tmp/frame.png"}],
            "artifacts": [{"path": "/tmp/out.txt"}],
            "verification": {"success": True},
            "latency_ms": 12.5,
        }

    outcome = asyncio.run(
        plane.handle(
            "Safari’de openai.com aç",
            user_id="u1",
            channel="telegram",
            device_id="mac",
            context={
                "request_id": "req-2",
                "device_id": "mac",
                "provider": "ollama",
                "model": "llama3.2",
                "execute": True,
                "tool_runner": _executor,
                "capability_plan": _capability_plan(),
            },
        )
    )

    assert isinstance(outcome, OperatorOutcome)
    assert outcome.success is True
    assert outcome.status == "completed"
    assert outcome.artifacts[0]["path"] == "/tmp/out.txt"
    assert outcome.execution_path == "fast"
    assert outcome.model_runtime["selected_model"]["provider"] == "ollama"


def test_operator_control_plane_attaches_task_plan_and_autonomy():
    plane = OperatorControlPlane(
        runtime_control=_RuntimeControlWorkflow(),
        model_orchestrator=_ModelOrchestrator(),
        policy_engine=_PolicyEngine(),
        real_time_actuator=_Actuator(),
    )

    result = asyncio.run(
        plane.plan_request(
            request_id="req-3",
            user_id="u1",
            request="Araştırma yapıp kısa bir rapor hazırla",
            channel="telegram",
            device_id="mac",
            context={"request_id": "req-3", "device_id": "mac", "provider": "ollama", "model": "llama3.2"},
            capability_plan=SimpleNamespace(
                domain="workflow",
                confidence=0.89,
                objective="research report",
                workflow_id="research_report",
                primary_action="research_document_delivery",
                preferred_tools=["advanced_research"],
                output_artifacts=["report"],
                quality_checklist=["verify"],
                learning_tags=["research"],
                complexity_tier="medium",
                suggested_job_type="workflow",
                multi_agent_recommended=True,
                orchestration_mode="multi_agent",
                workflow_profile_applicable=True,
                requires_design_phase=True,
                requires_worktree=False,
                content_kind="research_delivery",
                output_formats=["md"],
                style_profile="executive",
                source_policy="trusted",
                quality_contract=["citations"],
                memory_scope="task_routed",
                preview="research report",
                requires_real_time=False,
            ),
            metadata={"channel": "telegram"},
        )
    )

    assert result["autonomy"]["mode"] in {"auto", "auto-with-resume", "needs-consent", "needs-approval", "block"}
    assert isinstance(result["task_plan"], dict)
    assert isinstance(result["task_card"], dict)
    assert result["operator_trace"]["task_plan_ready"] is True
    assert result["task_plan"]["steps"]
