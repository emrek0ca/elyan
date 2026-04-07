from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Dict, List, Optional

from core.observability.logger import get_structured_logger

slog = get_structured_logger("uncertainty_engine")


def _default_state_path() -> Path:
    return Path(os.path.expanduser("~/.elyan/uncertainty_beliefs.json")).expanduser()


@dataclass(slots=True)
class Belief:
    claim: str
    probability: float
    evidence: List[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class UncertaintyEngine:
    def __init__(self, state_path: str | Path | None = None):
        self.state_path = Path(state_path or _default_state_path()).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._update_count = 0
        self.beliefs: Dict[str, Belief] = self._init_priors()
        self._load()

    def _init_priors(self) -> Dict[str, Belief]:
        return {
            "web_search_works": Belief("web_search_works", 0.92),
            "code_execution_safe": Belief("code_execution_safe", 0.78),
            "file_write_reversible": Belief("file_write_reversible", 0.65),
            "file_delete_safe": Belief("file_delete_safe", 0.40),
            "network_request_safe": Belief("network_request_safe", 0.85),
            "system_command_safe": Belief("system_command_safe", 0.55),
        }

    def _load(self) -> None:
        if not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            beliefs = raw.get("beliefs", {})
            if isinstance(beliefs, dict):
                for claim, payload in beliefs.items():
                    if not isinstance(payload, dict):
                        continue
                    self.beliefs[claim] = Belief(
                        claim=str(payload.get("claim") or claim),
                        probability=float(payload.get("probability") or 0.5),
                        evidence=list(payload.get("evidence") or [])[:10],
                        last_updated=float(payload.get("last_updated") or time.time()),
                    )
        except Exception as exc:
            slog.log_event("uncertainty_load_error", {"error": str(exc)}, level="warning")

    def _persist(self) -> None:
        try:
            payload = {"beliefs": {claim: asdict(belief) for claim, belief in self.beliefs.items()}}
            tmp = self.state_path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.state_path)
        except Exception as exc:
            slog.log_event("uncertainty_persist_error", {"error": str(exc)}, level="warning")

    def update_belief(self, claim: str, evidence: str, likelihood: float) -> float:
        with self._lock:
            belief = self.beliefs.setdefault(claim, Belief(claim, 0.5))
            prior = belief.probability
            likelihood = max(0.0, min(1.0, float(likelihood)))
            numerator = likelihood * prior
            denominator = numerator + ((1.0 - likelihood) * (1.0 - prior))
            posterior = numerator / denominator if denominator else prior
            belief.probability = max(0.0, min(1.0, posterior))
            belief.evidence = (belief.evidence + [str(evidence)])[-10:]
            belief.last_updated = time.time()
            self._update_count += 1
            if self._update_count % 5 == 0:
                self._persist()
            return belief.probability

    def should_ask_approval(self, action: str, threshold: float = 0.7) -> bool:
        with self._lock:
            belief = self.beliefs.get(action) or Belief(action, 0.5)
            return belief.probability < threshold

    def explain_uncertainty(self, action: str) -> str:
        with self._lock:
            belief = self.beliefs.get(action) or Belief(action, 0.5)
            evidence = ", ".join(belief.evidence[-3:]) if belief.evidence else "kanıt yok"
            return f"Bu işlemi %{belief.probability * 100:.0f} güvenle yapabilirim. Kanıtlar: {evidence}"

    def snapshot(self) -> Dict[str, Dict[str, object]]:
        with self._lock:
            return {claim: asdict(belief) for claim, belief in self.beliefs.items()}


_uncertainty_engine: Optional[UncertaintyEngine] = None


def get_uncertainty_engine() -> UncertaintyEngine:
    global _uncertainty_engine
    if _uncertainty_engine is None:
        _uncertainty_engine = UncertaintyEngine()
    return _uncertainty_engine
