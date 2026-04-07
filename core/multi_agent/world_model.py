from __future__ import annotations

import asyncio
import fnmatch
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from core.observability.logger import get_structured_logger

slog = get_structured_logger("world_model")


@dataclass(slots=True)
class WorldFact:
    fact_id: str
    content: Any
    confidence: float
    source_agent: str
    timestamp: float
    version: int = 1


class SharedWorldModel:
    def __init__(self):
        self._lock = asyncio.Lock()
        self._facts: Dict[str, WorldFact] = {}
        self._subscribers: list[tuple[str, Callable[[WorldFact], Awaitable[None] | None]]] = []

    async def assert_fact(self, fact_id: str, content: Any, confidence: float, source: str) -> bool:
        async with self._lock:
            current = self._facts.get(fact_id)
            accepted = current is None or confidence >= current.confidence
            if accepted:
                self._facts[fact_id] = WorldFact(
                    fact_id=fact_id,
                    content=content,
                    confidence=float(confidence),
                    source_agent=source,
                    timestamp=time.time(),
                    version=(current.version + 1) if current else 1,
                )
                fact = self._facts[fact_id]
                callbacks = [cb for pattern, cb in self._subscribers if fnmatch.fnmatch(fact_id, pattern)]
            else:
                callbacks = []
                fact = current
        if accepted and fact is not None:
            for callback in callbacks:
                try:
                    result = callback(fact)
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as exc:
                    slog.log_event("world_model_subscriber_error", {"error": str(exc), "fact_id": fact_id}, level="warning")
        return accepted

    async def query(self, pattern: str) -> List[WorldFact]:
        async with self._lock:
            return [fact for fact_id, fact in self._facts.items() if fnmatch.fnmatch(fact_id, pattern)]

    def subscribe(self, fact_pattern: str, async_callback: Callable[[WorldFact], Awaitable[None] | None]) -> None:
        self._subscribers.append((fact_pattern, async_callback))

    def get_snapshot(self, prefix: str = "") -> Dict[str, Any]:
        return {
            fact_id: asdict(fact)
            for fact_id, fact in self._facts.items()
            if not prefix or fact_id.startswith(prefix)
        }

    def cleanup_run(self, run_id: str) -> None:
        prefix = f"run.{run_id}."
        for fact_id in list(self._facts):
            if fact_id.startswith(prefix):
                self._facts.pop(fact_id, None)


_world_model: Optional[SharedWorldModel] = None


def get_world_model() -> SharedWorldModel:
    global _world_model
    if _world_model is None:
        _world_model = SharedWorldModel()
    return _world_model
