from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import automation_registry as ar_mod
from core import personal_context_engine as pce_mod
from core.runtime.scheduler import MissionScheduler


@pytest.mark.asyncio
async def test_personal_context_engine_stop_cancels_poll_task(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(pce_mod, "_PERSIST_PATH", tmp_path / "personal_context.json")
    engine = pce_mod.PersonalContextEngine()

    engine.start_background_polling("local")
    await asyncio.sleep(0)

    assert engine._poll_task is not None
    assert engine._polling is True

    await engine.stop_background_polling()

    assert engine._poll_task is None
    assert engine._polling is False


@pytest.mark.asyncio
async def test_automation_registry_stop_scheduler_clears_task(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")

    await registry.start_scheduler(agent=None)
    await asyncio.sleep(0)

    assert registry._scheduler_task is not None
    assert registry._running is True

    await registry.stop_scheduler()

    assert registry._scheduler_task is None
    assert registry._running is False


@pytest.mark.asyncio
async def test_mission_scheduler_stop_clears_loop_task():
    scheduler = MissionScheduler(SimpleNamespace(execute_run=lambda *args, **kwargs: None))

    await scheduler.start()
    await asyncio.sleep(0)

    assert scheduler._task is not None
    assert scheduler._running is True

    await scheduler.stop()

    assert scheduler._task is None
    assert scheduler._running is False
