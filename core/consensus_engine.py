from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any

from core.personalization.policy_learning import get_policy_learning_store
from utils.logger import get_logger

logger = get_logger("consensus_engine")


def _now() -> float:
    return time.time()


@dataclass
class AgentProposal:
    agent_id: str
    action: str
    confidence: float
    risk: str
    rationale: str
    est_cost: float = 0.0
    est_latency: float = 0.0
    domain_match: float = 1.0
    stability: float = 0.8
    role: str = "worker"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConsensusDecision:
    task_id: str
    user_id: str
    selected_action: str
    score: float
    vetoed: bool = False
    requires_approval: bool = False
    blocked: bool = False
    reason: str = ""
    winning_agent: str = ""
    alternatives: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    decided_at: float = field(default_factory=_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "user_id": self.user_id,
            "selected_action": self.selected_action,
            "score": self.score,
            "vetoed": self.vetoed,
            "requires_approval": self.requires_approval,
            "blocked": self.blocked,
            "reason": self.reason,
            "winning_agent": self.winning_agent,
            "alternatives": list(self.alternatives),
            "metadata": dict(self.metadata),
            "decided_at": self.decided_at,
        }


class ConsensusEngine:
    """Weighted majority consensus with security veto support."""

    def __init__(self) -> None:
        self.learning = get_policy_learning_store()
        self._security_role_markers = ("security", "policy", "risk")

    @staticmethod
    def _normalize_risk(risk: str) -> str:
        token = str(risk or "low").strip().lower()
        if token in {"critical", "high", "medium", "low"}:
            return token
        return "low"

    @staticmethod
    def _risk_score(risk: str) -> float:
        risk_map = {"low": 1.0, "medium": 0.8, "high": 0.55, "critical": 0.3}
        return risk_map.get(risk, 0.8)

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, float(value)))

    def _derive_weight(
        self,
        *,
        user_id: str,
        task_type: str,
        proposal: AgentProposal,
        latency_budget_ms: float,
    ) -> float:
        metrics = self.learning.get_agent_metrics(user_id, task_type, proposal.agent_id)
        success_rate = self._clamp(float(metrics.get("success_rate", proposal.confidence)))
        learned_latency_score = self._clamp(float(metrics.get("latency_score", 0.7)))
        stability = self._clamp(float(metrics.get("stability", proposal.stability)))
        domain_match = self._clamp(proposal.domain_match)

        est_latency = max(0.0, float(proposal.est_latency or 0.0))
        if latency_budget_ms > 0:
            est_latency_score = self._clamp(1.0 - min(1.0, est_latency / latency_budget_ms))
            latency_score = (0.6 * learned_latency_score) + (0.4 * est_latency_score)
        else:
            latency_score = learned_latency_score

        weight = (
            (0.45 * success_rate)
            + (0.25 * domain_match)
            + (0.20 * latency_score)
            + (0.10 * stability)
        )
        return self._clamp(weight)

    @staticmethod
    def _deterministic_seed(task_id: str, user_id: str, choices: list[str]) -> int:
        payload = f"{task_id}|{user_id}|{'|'.join(sorted(choices))}"
        digest = hashlib.sha256(payload.encode("utf-8", errors="ignore")).hexdigest()
        return int(digest[:16], 16)

    def resolve(
        self,
        *,
        task_id: str,
        user_id: str,
        task_type: str,
        proposals: list[AgentProposal],
        veto_policy: str = "require_approval",
        explore_exploit_level: float = 0.25,
        latency_budget_ms: float = 120000.0,
        metadata: dict[str, Any] | None = None,
    ) -> ConsensusDecision:
        if not proposals:
            return ConsensusDecision(
                task_id=str(task_id or ""),
                user_id=str(user_id or "local"),
                selected_action="",
                score=0.0,
                blocked=True,
                reason="no_proposals",
                metadata=dict(metadata or {}),
            )

        uid = str(user_id or "local").strip() or "local"
        ttype = str(task_type or "general").strip().lower() or "general"
        veto_policy = str(veto_policy or "require_approval").strip().lower()
        if veto_policy not in {"require_approval", "block"}:
            veto_policy = "require_approval"
        epsilon = self._clamp(float(explore_exploit_level or 0.25))

        action_scores: dict[str, float] = {}
        action_agents: dict[str, str] = {}
        normalized_proposals: list[dict[str, Any]] = []
        vetoed = False
        veto_reason = ""

        for proposal in proposals:
            action = str(proposal.action or "").strip().lower()
            if not action:
                continue
            risk = self._normalize_risk(proposal.risk)
            conf = self._clamp(float(proposal.confidence or 0.0))
            weight = self._derive_weight(
                user_id=uid,
                task_type=ttype,
                proposal=proposal,
                latency_budget_ms=max(1.0, float(latency_budget_ms or 1.0)),
            )
            weighted_score = (conf * weight) * self._risk_score(risk)
            action_scores[action] = action_scores.get(action, 0.0) + weighted_score
            action_agents.setdefault(action, str(proposal.agent_id or "unknown"))
            normalized_proposals.append(
                {
                    "agent_id": str(proposal.agent_id or "unknown"),
                    "action": action,
                    "confidence": conf,
                    "risk": risk,
                    "role": str(proposal.role or "worker"),
                    "weight": weight,
                    "weighted_score": weighted_score,
                }
            )
            role_low = str(proposal.role or "").strip().lower()
            if risk in {"high", "critical"} and any(marker in role_low for marker in self._security_role_markers):
                vetoed = True
                veto_reason = f"security_veto:{risk}"

        if not action_scores:
            return ConsensusDecision(
                task_id=str(task_id or ""),
                user_id=uid,
                selected_action="",
                score=0.0,
                blocked=True,
                reason="no_scored_actions",
                metadata={"proposals": normalized_proposals, **dict(metadata or {})},
            )

        rankings = sorted(action_scores.items(), key=lambda item: item[1], reverse=True)
        top_score = rankings[0][1]
        top_actions = [action for action, score in rankings if abs(score - top_score) < 1e-9]

        if len(top_actions) == 1:
            selected_action = top_actions[0]
        else:
            seed = self._deterministic_seed(str(task_id or ""), uid, top_actions)
            rng = random.Random(seed)
            if rng.random() < epsilon:
                selected_action = rng.choice(sorted(top_actions))
            else:
                selected_action = sorted(top_actions)[0]

        decision = ConsensusDecision(
            task_id=str(task_id or ""),
            user_id=uid,
            selected_action=selected_action,
            score=float(action_scores.get(selected_action, 0.0)),
            vetoed=vetoed,
            requires_approval=bool(vetoed and veto_policy == "require_approval"),
            blocked=bool(vetoed and veto_policy == "block"),
            reason=veto_reason if vetoed else "weighted_majority",
            winning_agent=action_agents.get(selected_action, ""),
            alternatives=[
                {"action": action, "score": float(score), "agent_id": action_agents.get(action, "")}
                for action, score in rankings[:5]
            ],
            metadata={"epsilon": epsilon, "veto_policy": veto_policy, "proposals": normalized_proposals, **dict(metadata or {})},
        )

        logger.debug(
            "consensus_resolved "
            + json.dumps(
                {
                    "task_id": decision.task_id,
                    "selected_action": decision.selected_action,
                    "score": decision.score,
                    "vetoed": decision.vetoed,
                    "blocked": decision.blocked,
                },
                ensure_ascii=False,
            )
        )
        return decision


_consensus_engine: ConsensusEngine | None = None


def get_consensus_engine() -> ConsensusEngine:
    global _consensus_engine
    if _consensus_engine is None:
        _consensus_engine = ConsensusEngine()
    return _consensus_engine

