from __future__ import annotations

import time
import uuid
from dataclasses import asdict
from typing import Any, Dict, Optional

from core.events.event_store import Event, EventStore, EventType
from core.events.read_model import RunReadModel
from core.learning.policy_learner import ResponsePolicyLearner
from core.learning.reward_shaper import RewardShaper
from core.learning.tool_bandit import ToolSelectionBandit
from core.multi_agent.contract_net import ContractNetProtocol
from core.multi_agent.specialists import get_specialist_registry
from core.multi_agent.consensus import SwarmConsensus
from core.multi_agent.world_model import SharedWorldModel
from core.observability.capacity_planner import CapacityPlanner
from core.observability.dora_metrics import MetricsCollector
from core.planning.htn_planner import HTNPlanner
from core.reasoning.uncertainty_engine import UncertaintyEngine
from core.resilience.circuit_breaker import CircuitBreakerRegistry
from core.unified_model_gateway import UnifiedModelGateway
from config.elyan_config import elyan_config


class ElyanRuntime:
    def __init__(self):
        self.event_store = EventStore()
        self.read_model = RunReadModel(self.event_store)
        self.htn_planner = HTNPlanner()
        self.uncertainty_engine = UncertaintyEngine()
        self.tool_bandit = ToolSelectionBandit(
            exploration_constant=float(elyan_config.get("observability.tool_bandit_exploration_constant", 2.0) or 2.0)
        )
        self.policy_learner = ResponsePolicyLearner()
        self.reward_shaper = RewardShaper()
        self.contract_net = ContractNetProtocol()
        self.specialists = get_specialist_registry()
        self.specialists.sync_contract_net(self.contract_net)
        self.model_gateway = UnifiedModelGateway(specialist_registry=self.specialists)
        self.world_model = SharedWorldModel()
        self.consensus = SwarmConsensus()
        self.circuit_registry = CircuitBreakerRegistry()
        self.metrics_collector = MetricsCollector(self.event_store)
        self.capacity_planner = CapacityPlanner(self.metrics_collector)

    def record_event(
        self,
        event_type: EventType,
        *,
        aggregate_id: str,
        aggregate_type: str,
        payload: Dict[str, Any] | None = None,
        causation_id: str | None = None,
    ) -> Optional[int]:
        event = Event(
            event_id=str(uuid.uuid4()),
            event_type=event_type,
            aggregate_id=str(aggregate_id),
            aggregate_type=str(aggregate_type),
            payload=dict(payload or {}),
            timestamp=time.time(),
            causation_id=causation_id,
        )
        try:
            return self.event_store.append(event)
        except Exception:
            return None

    def record_tool_outcome(self, task_category: str, tool_name: str, success: bool, latency_ms: float, *, user_satisfaction: float = 0.5) -> None:
        try:
            self.tool_bandit.record_outcome(task_category, tool_name, success, latency_ms, user_satisfaction=user_satisfaction)
        except Exception:
            pass

    def should_request_approval(self, action: str) -> bool:
        try:
            return self.uncertainty_engine.should_ask_approval(action)
        except Exception:
            return True


_runtime: Optional[ElyanRuntime] = None


def get_elyan_runtime() -> ElyanRuntime:
    global _runtime
    if _runtime is None:
        _runtime = ElyanRuntime()
    return _runtime
