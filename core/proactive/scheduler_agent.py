"""
core/proactive/scheduler_agent.py
───────────────────────────────────────────────────────────────────────────────
SchedulerAgent — cron-like task scheduling for Jarvis.

Supported cron expressions:
  "HH:MM"    — daily at that time (e.g. "09:00")
  "*/Nm"     — every N minutes (e.g. "*/30m")
"""
from __future__ import annotations
import asyncio, re, time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable
from utils.logger import get_logger

logger = get_logger("scheduler_agent")


@dataclass
class ScheduledTask:
    task_id: str
    name: str
    cron_expr: str
    action: Callable[[], Awaitable[Any]]
    enabled: bool = True
    last_run_ts: float = 0.0
    run_count: int = 0


def _is_due(task: ScheduledTask) -> bool:
    """Check if a scheduled task is due to run."""
    expr = task.cron_expr.strip()
    now = time.time()

    # Interval: */Nm
    m = re.match(r"^\*/(\d+)m$", expr)
    if m:
        interval_s = int(m.group(1)) * 60
        return (now - task.last_run_ts) >= interval_s

    # Daily time: HH:MM
    m = re.match(r"^(\d{1,2}):(\d{2})$", expr)
    if m:
        target_h, target_m = int(m.group(1)), int(m.group(2))
        dt = datetime.now()
        if dt.hour == target_h and dt.minute == target_m:
            # Don't re-run within the same minute
            return (now - task.last_run_ts) > 60
        return False

    return False


class SchedulerAgent:
    def __init__(self) -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None

    def register(self, task: ScheduledTask) -> None:
        self._tasks[task.task_id] = task
        logger.info(f"Scheduled: {task.name} [{task.cron_expr}]")

    def unregister(self, task_id: str) -> None:
        self._tasks.pop(task_id, None)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(self._loop())
        logger.info("SchedulerAgent started")

    async def stop(self) -> None:
        self._running = False
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()

    async def _loop(self) -> None:
        while self._running:
            for task in list(self._tasks.values()):
                if task.enabled and _is_due(task):
                    task.last_run_ts = time.time()
                    task.run_count += 1
                    logger.info(f"Running scheduled task: {task.name}")
                    try:
                        await task.action()
                    except Exception as exc:
                        logger.warning(f"Scheduled task {task.name} failed: {exc}")
            await asyncio.sleep(30)


_instance: SchedulerAgent | None = None

def get_scheduler_agent() -> SchedulerAgent:
    global _instance
    if _instance is None:
        _instance = SchedulerAgent()
    return _instance

__all__ = ["ScheduledTask", "SchedulerAgent", "get_scheduler_agent"]
