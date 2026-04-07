"""
core/proactive/context_tracker.py
───────────────────────────────────────────────────────────────────────────────
ContextTracker — tracks what user is currently doing on their Mac.
"""
from __future__ import annotations
import asyncio, time
from dataclasses import dataclass, field
from utils.logger import get_logger
from core.computer.macos_controller import get_macos_controller  # noqa: F401 — patchable

logger = get_logger("context_tracker")


@dataclass(slots=True)
class UserContext:
    current_app: str = ""
    focus_duration_s: float = 0.0
    recent_apps: list[str] = field(default_factory=list)
    last_updated: float = field(default_factory=time.time)


class ContextTracker:
    def __init__(self) -> None:
        self._ctx = UserContext()
        self._app_start_ts: float = 0.0
        self._running = False
        self._task: asyncio.Task | None = None

    async def update(self) -> UserContext:
        try:
            app = await get_macos_controller().get_frontmost_app()
        except Exception:
            app = ""

        now = time.time()
        if app and app != self._ctx.current_app:
            # App switched
            if self._ctx.current_app:
                recent = [self._ctx.current_app] + [
                    a for a in self._ctx.recent_apps if a != self._ctx.current_app
                ]
                self._ctx.recent_apps = recent[:10]
            self._ctx.current_app = app
            self._app_start_ts = now
            self._ctx.focus_duration_s = 0.0
        elif app:
            self._ctx.focus_duration_s = now - self._app_start_ts

        self._ctx.last_updated = now
        return self._ctx

    def get_context(self) -> UserContext:
        return self._ctx

    async def start(self, interval_s: float = 5.0) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._loop(interval_s))

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()

    async def _loop(self, interval_s: float) -> None:
        while self._running:
            try:
                await self.update()
            except Exception as exc:
                logger.debug(f"context update error: {exc}")
            await asyncio.sleep(interval_s)


_instance: ContextTracker | None = None

def get_context_tracker() -> ContextTracker:
    global _instance
    if _instance is None:
        _instance = ContextTracker()
    return _instance

__all__ = ["UserContext", "ContextTracker", "get_context_tracker"]
