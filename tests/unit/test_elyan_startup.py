from __future__ import annotations

import pytest

from core.elyan import elyan_startup


@pytest.mark.asyncio
async def test_start_services_skips_wake_word_by_default(monkeypatch):
    calls = {"wake": 0}

    async def _noop(*args, **kwargs):
        return None

    async def _wake(*args, **kwargs):
        calls["wake"] += 1

    monkeypatch.delenv("ELYAN_ENABLE_WAKE_WORD", raising=False)
    monkeypatch.setattr(elyan_startup, "_start_ollama_discovery", _noop)
    monkeypatch.setattr(elyan_startup, "_start_system_monitor", _noop)
    monkeypatch.setattr(elyan_startup, "_start_scheduler", _noop)
    monkeypatch.setattr(elyan_startup, "_start_context_tracker", _noop)
    monkeypatch.setattr(elyan_startup, "_start_morning_brief", _noop)
    monkeypatch.setattr(elyan_startup, "_start_wake_word", _wake)

    await elyan_startup.start_elyan_services(broadcast=None)

    assert calls["wake"] == 0
