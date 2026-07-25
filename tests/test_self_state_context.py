"""Kendi durumunun farkındalığı sözleşmesi.

Model "şu an bir görev yürüyor" ve "son görev başarısız oldu" bilgisini
durumsal bağlamdan alır → kaçamak cevap yerine dürüst durum cümlesi kurabilir.
Değişmez: BAYAT sonuç taşınmaz — 60 dakikadan eski son-görev sonucu gürültüdür
ve bağlama hiç girmez.
"""

from __future__ import annotations

import datetime as dt

from runtime.situational_context import gather_situation


def _state(executor: dict) -> dict:
    return {"runtime": {"executor": executor}}


def test_running_task_surfaces_in_self_state() -> None:
    situation = gather_situation(_state({"activeExecutionCount": 2}))
    assert situation.active_task_count == 2
    assert situation.is_empty is False
    payload = situation.to_prompt_context()
    assert payload["selfState"] == {"taskRunning": True, "taskCount": 2}


def test_recent_failed_task_surfaces_with_detail() -> None:
    last_at = (dt.datetime.now() - dt.timedelta(minutes=10)).isoformat(timespec="seconds")
    situation = gather_situation(
        _state(
            {
                "activeExecutionCount": 0,
                "lastExecutionAt": last_at,
                "lastExecutionOk": False,
                "lastExecutionDetail": "izin reddedildi",
            }
        )
    )
    payload = situation.to_prompt_context()
    last_task = payload["selfState"]["lastTask"]
    assert last_task["ok"] is False
    assert last_task["detail"] == "izin reddedildi"
    assert 9 <= last_task["minutesAgo"] <= 11


def test_stale_last_task_is_not_surfaced() -> None:
    last_at = (dt.datetime.now() - dt.timedelta(hours=3)).isoformat(timespec="seconds")
    situation = gather_situation(
        _state({"lastExecutionAt": last_at, "lastExecutionOk": False})
    )
    assert situation.last_task_ok is None
    assert "selfState" not in situation.to_prompt_context()


def test_no_executor_info_produces_no_self_state() -> None:
    situation = gather_situation({"runtime": {}})
    assert "selfState" not in situation.to_prompt_context()
    assert situation.is_empty is True
