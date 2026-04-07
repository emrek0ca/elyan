from __future__ import annotations

import pytest

from core.cognitive_layer_integrator import CognitiveLayerIntegrator


def test_deadlock_recovery_action_standardization():
    integrator = CognitiveLayerIntegrator()
    assert integrator._standardize_recovery_action("switch_to_diffuse_mode") == "switch_to_diffuse"
    assert integrator._standardize_recovery_action("increase_timeout_and_retry") == "queue_with_backoff"
    assert integrator._standardize_recovery_action("escalate_to_human_approval") == "escalate_approval"
    assert integrator._standardize_recovery_action("unknown_action") == "safe_fallback"


@pytest.mark.asyncio
async def test_evaluate_consensus_applies_security_veto_block():
    integrator = CognitiveLayerIntegrator()
    decision = await integrator.evaluate_consensus(
        task_id="cons-task",
        user_id="local",
        task_type="general",
        proposals=[
            {
                "agent_id": "planner_primary",
                "action": "delete_file",
                "confidence": 0.9,
                "risk": "high",
                "rationale": "requested",
                "role": "planner",
            },
            {
                "agent_id": "security_policy_guard",
                "action": "delete_file",
                "confidence": 1.0,
                "risk": "critical",
                "rationale": "safety veto",
                "role": "security_policy",
            },
        ],
        context={"consensus_veto_policy": "block", "consensus_explore_exploit_level": 0.2},
    )

    assert decision["vetoed"] is True
    assert decision["blocked"] is True
    assert decision["requires_approval"] is False


def test_runtime_metrics_shape():
    integrator = CognitiveLayerIntegrator()
    metrics = integrator.get_runtime_metrics("local")
    assert "mode" in metrics
    assert "deadlock_rate" in metrics
    assert "consensus_overrides" in metrics
    assert "learning_score" in metrics
