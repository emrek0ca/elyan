from __future__ import annotations

import json
import math
import os
import random
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Deque, Dict, List

from core.observability.logger import get_structured_logger
from core.persistence import get_runtime_database

slog = get_structured_logger("policy_learner")

RESPONSE_ACTIONS = [
    "concise_answer",
    "detailed_explanation",
    "code_first",
    "step_by_step",
    "proactive_suggestions",
    "ask_clarification",
]


def _default_state_path() -> Path:
    return Path(os.path.expanduser("~/.elyan/policy_weights.json")).expanduser()


def _softmax(logits: List[float]) -> List[float]:
    if not logits:
        return []
    max_logit = max(logits)
    exps = [math.exp(value - max_logit) for value in logits]
    total = sum(exps) or 1.0
    return [value / total for value in exps]


def _dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


@dataclass(slots=True)
class _Experience:
    state: List[float]
    action: str
    reward: float
    next_state: List[float]


class ResponsePolicyLearner:
    def __init__(
        self,
        state_path: str | Path | None = None,
        *,
        learning_rate: float = 0.05,
        workspace_id: str = "local-workspace",
        user_id: str = "local-user",
    ):
        self.state_path = Path(state_path or _default_state_path()).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.learning_rate = float(learning_rate)
        self.workspace_id = str(workspace_id or "local-workspace")
        self.user_id = str(user_id or "local-user")
        self._lock = RLock()
        self._learning_repo = None
        self._learning_repo_unavailable = False
        self.policy_weights: Dict[str, List[float]] = {action: [0.1] * 64 for action in RESPONSE_ACTIONS}
        self.experience_buffer: Deque[_Experience] = deque(maxlen=1000)
        self._load()

    def _repo(self):
        if self._learning_repo_unavailable:
            return None
        if self._learning_repo is not None:
            return self._learning_repo
        try:
            self._learning_repo = get_runtime_database().learning
        except Exception:
            self._learning_repo_unavailable = True
            self._learning_repo = None
        return self._learning_repo

    def _load(self) -> None:
        repo = self._repo()
        if repo is not None:
            try:
                profile = repo.get_user_preference_profile(workspace_id=self.workspace_id, user_id=self.user_id) or {}
                metadata = dict(profile.get("metadata") or {})
                weights = metadata.get("response_policy_weights")
                if isinstance(weights, dict):
                    for action, vector in weights.items():
                        if isinstance(vector, list) and len(vector) == 64:
                            self.policy_weights[action] = [float(v) for v in vector]
                    return
            except Exception as exc:
                slog.log_event("policy_db_load_error", {"error": str(exc)}, level="warning")
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            weights = raw.get("policy_weights", {})
            if isinstance(weights, dict):
                for action, vector in weights.items():
                    if isinstance(vector, list) and len(vector) == 64:
                        self.policy_weights[action] = [float(v) for v in vector]
        except Exception as exc:
            slog.log_event("policy_load_error", {"error": str(exc)}, level="warning")

    def _persist(self) -> None:
        repo = self._repo()
        if repo is not None:
            try:
                current = repo.get_user_preference_profile(workspace_id=self.workspace_id, user_id=self.user_id) or {}
                repo.upsert_user_preference_profile(
                    workspace_id=self.workspace_id,
                    user_id=self.user_id,
                    explanation_style=str(current.get("explanation_style") or "concise"),
                    approval_sensitivity_hint=str(current.get("approval_sensitivity_hint") or "balanced"),
                    preferred_route=str(current.get("preferred_route") or "balanced"),
                    preferred_model=str(current.get("preferred_model") or ""),
                    task_templates=list(current.get("task_templates") or []),
                    metadata={
                        **dict(current.get("metadata") or {}),
                        "response_policy_weights": self.policy_weights,
                        "experience_count": len(self.experience_buffer),
                        "learning_rate": self.learning_rate,
                    },
                )
                return
            except Exception as exc:
                slog.log_event("policy_db_persist_error", {"error": str(exc)}, level="warning")
        try:
            payload = {"policy_weights": self.policy_weights}
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except Exception as exc:
            slog.log_event("policy_persist_error", {"error": str(exc)}, level="warning")

    def select_action(self, state_features: List[float]) -> str:
        features = list((state_features or [])[:64])
        if len(features) < 64:
            features.extend([0.0] * (64 - len(features)))
        with self._lock:
            logits = [_dot(features, self.policy_weights[action]) for action in RESPONSE_ACTIONS]
            probs = _softmax(logits)
            if not probs:
                return RESPONSE_ACTIONS[0]
            choice = random.choices(RESPONSE_ACTIONS, weights=probs, k=1)[0]
            return choice

    def record_feedback(
        self,
        state: List[float],
        action: str,
        reward: float,
        next_state: List[float],
    ) -> None:
        features = list((state or [])[:64])
        if len(features) < 64:
            features.extend([0.0] * (64 - len(features)))
        with self._lock:
            self.experience_buffer.append(
                _Experience(state=features, action=str(action), reward=float(reward), next_state=list(next_state or [])[:64])
            )
            repo = self._repo()
            if repo is not None:
                try:
                    repo.record_operational_feedback(
                        workspace_id=self.workspace_id,
                        user_id=self.user_id,
                        category="response_policy",
                        entity_id=str(action),
                        outcome="positive" if float(reward) >= 0.0 else "negative",
                        reward=float(reward),
                        latency_ms=0.0,
                        recovery_count=0,
                        payload={"next_state_dim": len(list(next_state or [])[:64])},
                    )
                except Exception as exc:
                    slog.log_event("policy_feedback_persist_error", {"error": str(exc)}, level="warning")
            if len(self.experience_buffer) >= 32:
                self._update_policy()
                self._persist()

    def _update_policy(self) -> None:
        batch = list(self.experience_buffer)[-32:]
        if not batch:
            return
        baseline = sum(exp.reward for exp in batch) / len(batch)
        for exp in batch:
            advantage = exp.reward - baseline
            weights = self.policy_weights.setdefault(exp.action, [0.1] * 64)
            for i, feature in enumerate(exp.state[:64]):
                weights[i] += self.learning_rate * advantage * feature

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {"policy_weights": self.policy_weights}
