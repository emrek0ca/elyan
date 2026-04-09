from __future__ import annotations

import json
import threading
import time
import uuid
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core.feature_flags import get_feature_flag_registry
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _normalize_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


@dataclass(slots=True)
class Pattern:
    id: str
    description: str
    frequency: int
    confidence: float
    trigger_conditions: dict[str, Any]


class PatternEngine:
    def __init__(
        self,
        *,
        storage_path: str | Path | None = None,
        runtime_policy: dict[str, Any] | None = None,
    ) -> None:
        default_path = resolve_elyan_data_dir() / "ambient" / "activity_log.jsonl"
        self.storage_path = Path(storage_path or default_path).expanduser().resolve()
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.runtime_policy = dict(runtime_policy or {})
        self._lock = threading.Lock()
        self._feature_flags = get_feature_flag_registry()

    def record_activity(self, event: dict[str, Any]) -> None:
        payload = {
            "event_id": str(event.get("event_id") or f"activity_{uuid.uuid4().hex[:12]}"),
            "workspace_id": str(event.get("workspace_id") or "local-workspace").strip() or "local-workspace",
            "actor_id": str(event.get("actor_id") or "local-user").strip() or "local-user",
            "action": _normalize_text(event.get("action") or event.get("name") or "unknown"),
            "target": _normalize_text(event.get("target") or event.get("resource") or ""),
            "channel": _normalize_text(event.get("channel") or ""),
            "metadata": dict(event.get("metadata") or {}),
            "timestamp": float(event.get("timestamp") or _now()),
        }
        with self._lock:
            with self.storage_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")

    def detect_patterns(self, window_days: int = 30) -> list[Pattern]:
        cutoff = _now() - (max(1, int(window_days or 30)) * 86400)
        events = [event for event in self._load_events() if float(event.get("timestamp") or 0.0) >= cutoff]
        signatures: Counter[tuple[str, str, str]] = Counter()
        sample_events: dict[tuple[str, str, str], dict[str, Any]] = {}
        for event in events:
            signature = (
                str(event.get("action") or "unknown"),
                str(event.get("target") or ""),
                str(event.get("channel") or ""),
            )
            signatures[signature] += 1
            sample_events.setdefault(signature, event)
        patterns: list[Pattern] = []
        for signature, frequency in signatures.items():
            if frequency < 2:
                continue
            action, target, channel = signature
            sample = sample_events.get(signature, {})
            confidence = min(0.95, 0.45 + (0.12 * frequency))
            description = f"Recurring activity: {action}"
            if target:
                description = f"{description} -> {target}"
            trigger_conditions = {
                "action": action,
                "target": target,
                "channel": channel,
                "workspace_id": str(sample.get("workspace_id") or "local-workspace"),
                "actor_id": str(sample.get("actor_id") or "local-user"),
            }
            patterns.append(
                Pattern(
                    id=f"pattern_{uuid.uuid5(uuid.NAMESPACE_URL, '|'.join(signature)).hex[:12]}",
                    description=description,
                    frequency=frequency,
                    confidence=round(confidence, 2),
                    trigger_conditions=trigger_conditions,
                )
            )
        patterns.sort(key=lambda item: (item.confidence, item.frequency, item.description), reverse=True)
        return patterns

    def suggest_automation(self, pattern: Pattern) -> dict[str, Any] | None:
        if float(pattern.confidence or 0.0) < 0.8:
            return None
        if not self._feature_flags.is_enabled("ambient_pattern_engine", runtime_policy=self.runtime_policy):
            return None
        return {
            "pattern_id": pattern.id,
            "title": pattern.description,
            "action": str(pattern.trigger_conditions.get("action") or ""),
            "target": str(pattern.trigger_conditions.get("target") or ""),
            "confidence": float(pattern.confidence or 0.0),
            "frequency": int(pattern.frequency or 0),
            "trigger_conditions": dict(pattern.trigger_conditions or {}),
        }

    def _load_events(self) -> list[dict[str, Any]]:
        if not self.storage_path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with self._lock:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    content = str(line or "").strip()
                    if not content:
                        continue
                    try:
                        payload = json.loads(content)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(payload, dict):
                        rows.append(payload)
        return rows
