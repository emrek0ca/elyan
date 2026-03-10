from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass
class HybridModelPlan:
    role: str
    routing_role: str
    critic_role: str
    tool_first: bool = False
    prefer_local: bool = False
    tier: str = "balanced"

    def to_dict(self) -> Dict[str, object]:
        return {
            "role": self.role,
            "routing_role": self.routing_role,
            "critic_role": self.critic_role,
            "tool_first": self.tool_first,
            "prefer_local": self.prefer_local,
            "tier": self.tier,
        }


def build_hybrid_model_plan(
    capability_domain: str,
    workflow_id: str,
    *,
    current_role: str = "inference",
) -> HybridModelPlan:
    cap = str(capability_domain or "").strip().lower()
    workflow = str(workflow_id or "").strip().lower()
    base_role = str(current_role or "inference").strip().lower() or "inference"

    if cap == "research" or workflow == "research_workflow":
        return HybridModelPlan(
            role="research_worker",
            routing_role="router",
            critic_role="critic",
            tool_first=False,
            prefer_local=False,
            tier="strong",
        )

    if cap in {"coding", "website"} or workflow in {"coding_workflow", "website_delivery_workflow"}:
        return HybridModelPlan(
            role="code_worker",
            routing_role="router",
            critic_role="critic",
            tool_first=False,
            prefer_local=False,
            tier="strong",
        )

    if cap in {"screen_operator", "desktop_control", "browser"} or workflow == "screen_operator_workflow":
        return HybridModelPlan(
            role="router",
            routing_role="router",
            critic_role="critic",
            tool_first=True,
            prefer_local=True,
            tier="cheap",
        )

    return HybridModelPlan(
        role=base_role if base_role not in {"", "unknown"} else "inference",
        routing_role="router",
        critic_role="critic",
        tool_first=False,
        prefer_local=base_role in {"inference", "router"},
        tier="balanced",
    )


__all__ = ["HybridModelPlan", "build_hybrid_model_plan"]
