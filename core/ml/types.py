from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


def _ts() -> float:
    return time.time()


@dataclass(slots=True)
class DecisionRecord:
    request_id: str
    user_id: str
    kind: str
    selected: str
    confidence: float
    raw_confidence: float = 0.0
    channel: str = ""
    source: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OutcomeRecord:
    request_id: str
    user_id: str
    action: str
    channel: str
    final_outcome: str
    success: bool
    verification_result: dict[str, Any] = field(default_factory=dict)
    user_feedback: dict[str, Any] = field(default_factory=dict)
    decision_trace: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class RewardEvent:
    event_id: str
    user_id: str
    interaction_id: str
    event_type: str
    reward: float
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class PreferencePair:
    pair_id: str
    user_id: str
    interaction_id: str
    chosen_response: str
    rejected_response: str
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ModelCapabilitySnapshot:
    kind: str
    available: bool
    backend: str
    device: str
    fallback: bool = False
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=_ts)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
