from __future__ import annotations

from types import SimpleNamespace

from runtime import reasoning_policy


def _route(*, confidence: float = 0.95, steps: list[dict] | None = None):
    return SimpleNamespace(
        confidence=confidence,
        is_multi_step=bool(steps and len(steps) > 1),
        steps=tuple(steps or []),
        plan_preview=None,
        intent="task",
        reason="task",
        tool_name="sys_info",
        requires_confirmation=False,
    )


def test_atomic_high_confidence_route_keeps_fast_path() -> None:
    decision = reasoning_policy.decide_reasoning_path(_route())

    assert decision.use_structured_planner is False
    assert decision.reason == "atomic_fast_path"


def test_multi_step_and_data_flow_routes_use_structured_planner() -> None:
    multi = reasoning_policy.decide_reasoning_path(
        _route(
            steps=[
                {"id": "research", "capability": "web_research", "args": {}},
                {
                    "id": "write",
                    "capability": "document_write",
                    "dependsOn": ["research"],
                    "args": {},
                },
            ]
        )
    )
    data_flow = reasoning_policy.decide_reasoning_path(
        _route(
            steps=[
                {
                    "id": "download",
                    "capability": "browser_session.download",
                    "forEach": "{{steps.links.result.items}}",
                    "args": {},
                }
            ]
        )
    )

    assert multi.use_structured_planner is True
    assert multi.reason == "multi_step"
    assert data_flow.use_structured_planner is True
    assert data_flow.reason == "data_flow"


def test_trusted_work_order_plan_is_not_replanned() -> None:
    decision = reasoning_policy.decide_reasoning_path(
        None,
        work_order={
            "requiredCapabilities": ["web_research", "spreadsheet_write"],
            "planPreview": {
                "steps": [
                    {"id": "research", "capability": "web_research", "args": {}},
                    {"id": "write", "capability": "spreadsheet_write", "args": {}},
                ]
            },
        },
    )

    assert decision.use_structured_planner is False
    assert decision.reason == "trusted_work_order_plan"


def test_high_confidence_known_transform_plan_uses_validated_fast_path() -> None:
    routed = SimpleNamespace(
        confidence=0.91,
        is_multi_step=True,
        steps=(
            {"id": "read", "capability": "document_read", "args": {"path": "/tmp/report.pdf"}},
            {
                "id": "write",
                "capability": "presentation_write",
                "dependsOn": ["read"],
                "args": {"outputPath": "/tmp/report.pptx"},
            },
        ),
        plan_preview=None,
        intent="document_transform",
        reason="selected_document_transform",
        tool_name="presentation_write",
        requires_confirmation=True,
    )

    decision = reasoning_policy.decide_reasoning_path(routed)

    assert decision.use_structured_planner is False
    assert decision.reason == "validated_deterministic_plan"


def test_work_order_with_multiple_capabilities_requires_reasoning() -> None:
    decision = reasoning_policy.decide_reasoning_path(
        None,
        work_order={"requiredCapabilities": ["web_research", "spreadsheet_write"]},
    )

    assert decision.use_structured_planner is True
    assert decision.reason == "multi_capability_work_order"


def test_goal_context_normalizes_private_scope_and_invalid_step_budget() -> None:
    context = reasoning_policy.build_goal_context(
        query="local task",
        work_order={
            "privacyClass": "side_effect",
            "execution": {"maxSteps": "invalid"},
            "capabilityScope": ["document_read", "document_write"],
        },
    )

    assert context["contract"] == reasoning_policy.GOAL_CONTEXT_CONTRACT
    assert context["goalContract"]["privacy"] == "local_private"
    assert context["goalContract"]["objective"] == "local task"
    assert context["workOrder"]["maxSteps"] == 16
    assert reasoning_policy.allowed_capabilities(context) == {
        "document_read",
        "document_write",
    }
