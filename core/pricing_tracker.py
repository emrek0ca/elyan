"""Token usage and estimated pricing tracker for Elyan."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

from core.quota import quota_manager

logger = get_logger("pricing_tracker")

# USD per 1K tokens (rough defaults, editable from settings panel)
DEFAULT_PRICING_PER_1K = {
    "groq": {"input": 0.0005, "output": 0.0015},
    "gemini": {"input": 0.00035, "output": 0.00105},
    "openai": {"input": 0.0025, "output": 0.01},
    "ollama": {"input": 0.0, "output": 0.0},
}


class PricingTracker:
    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or self._default_path()
        self._data = self._default_data()
        self._load()

    def _default_path(self) -> Path:
        base = Path.home() / ".elyan"
        try:
            base.mkdir(parents=True, exist_ok=True)
            probe = base / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return base / "pricing_stats.json"
        except Exception:
            local = Path(__file__).parent.parent / ".elyan"
            local.mkdir(parents=True, exist_ok=True)
            return local / "pricing_stats.json"

    def _default_data(self) -> dict[str, Any]:
        return {
            "lifetime": {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "estimated_cost_usd": 0.0,
            },
            "by_provider": {},
            "updated_at": int(time.time()),
        }

    def _load(self):
        try:
            if self.db_path.exists():
                self._data = json.loads(self.db_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning(f"Pricing stats load failed: {exc}")
            self._data = self._default_data()

    def _save(self):
        self._data["updated_at"] = int(time.time())
        try:
            self.db_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.warning(f"Pricing stats save failed: {exc}")
            # Fallback to local writable path.
            local = Path(__file__).parent.parent / ".elyan" / "pricing_stats.json"
            local.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.db_path = local
                self.db_path.write_text(
                    json.dumps(self._data, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except Exception as inner_exc:
                logger.warning(f"Pricing stats local fallback save failed: {inner_exc}")

    def record_usage(
        self,
        *,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        user_id: str = "local",
        rates: dict[str, dict[str, float]] | None = None,
    ):
        provider_key = str(provider or "unknown").lower()
        rates = rates or DEFAULT_PRICING_PER_1K
        provider_rates = rates.get(provider_key, {"input": 0.0, "output": 0.0})
        input_cost = (max(prompt_tokens, 0) / 1000.0) * float(provider_rates.get("input", 0.0))
        output_cost = (max(completion_tokens, 0) / 1000.0) * float(provider_rates.get("output", 0.0))
        total_cost = input_cost + output_cost

        # Record in quota manager
        total_tokens = max(prompt_tokens, 0) + max(completion_tokens, 0)
        quota_manager.record_message(user_id, tokens=total_tokens)

        lifetime = self._data["lifetime"]
        lifetime["requests"] += 1
        lifetime["prompt_tokens"] += max(prompt_tokens, 0)
        lifetime["completion_tokens"] += max(completion_tokens, 0)
        lifetime["estimated_cost_usd"] = round(float(lifetime["estimated_cost_usd"]) + total_cost, 8)

        by_provider = self._data.setdefault("by_provider", {})
        p = by_provider.setdefault(
            provider_key,
            {
                "requests": 0,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "estimated_cost_usd": 0.0,
                "last_model": "",
            },
        )
        p["requests"] += 1
        p["prompt_tokens"] += max(prompt_tokens, 0)
        p["completion_tokens"] += max(completion_tokens, 0)
        p["estimated_cost_usd"] = round(float(p["estimated_cost_usd"]) + total_cost, 8)
        p["last_model"] = model

        self._save()

    def summary(self) -> dict[str, Any]:
        return self._data

    def reset(self):
        self._data = self._default_data()
        self._save()


_tracker: PricingTracker | None = None


def get_pricing_tracker() -> PricingTracker:
    global _tracker
    if _tracker is None:
        _tracker = PricingTracker()
    return _tracker
