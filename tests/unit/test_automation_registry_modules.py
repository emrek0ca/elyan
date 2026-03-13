from __future__ import annotations

import time
from pathlib import Path

import pytest

from core import automation_registry as ar_mod


def test_register_module_persists_module_metadata(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    task_id = registry.register_module(
        "context_recovery",
        interval_seconds=1800,
        timeout_seconds=75,
        max_retries=2,
        retry_backoff_seconds=11,
        circuit_breaker_threshold=4,
        circuit_breaker_cooldown_seconds=500,
        params={"workspace": str(tmp_path)},
    )

    row = registry.automations.get(task_id, {})
    assert row["id"] == task_id
    assert row["module_id"] == "context_recovery"
    assert int(row["interval_seconds"]) == 1800
    assert int(row["timeout_seconds"]) == 75
    assert int(row["max_retries"]) == 2
    assert int(row["retry_backoff_seconds"]) == 11
    assert int(row["circuit_breaker_threshold"]) == 4
    assert int(row["circuit_breaker_cooldown_seconds"]) == 500
    assert Path(registry.db_path).exists()


@pytest.mark.asyncio
async def test_execute_automation_prefers_agent_module_runner(monkeypatch, tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    task_id = registry.register_module("context_recovery", params={"workspace": str(tmp_path)})

    called = {}

    async def _fake_run(module_id: str, payload: dict):
        called["module_id"] = module_id
        called["payload"] = dict(payload)
        return {"success": True, "module_id": module_id, "summary": "ok"}

    monkeypatch.setattr(ar_mod, "run_agent_module", _fake_run)
    result = await registry._execute_automation(task_id, registry.automations[task_id], agent=None)

    assert result["success"] is True
    assert called["module_id"] == "context_recovery"
    assert called["payload"]["task_id"] == task_id


def test_registry_exposes_agent_module_list(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    modules = registry.list_modules()
    ids = {row.get("module_id") for row in modules}
    assert "context_recovery" in ids


def test_register_module_upserts_same_scope_and_params(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    first_id = registry.register_module(
        "context_recovery",
        channel="automation",
        user_id="system",
        params={"workspace": str(tmp_path)},
        interval_seconds=3600,
    )
    second_id = registry.register_module(
        "context_recovery",
        channel="automation",
        user_id="system",
        params={"workspace": str(tmp_path)},
        interval_seconds=7200,
        timeout_seconds=50,
    )

    assert first_id == second_id
    reloaded = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    assert len(reloaded.automations) == 1
    row = reloaded.automations[first_id]
    assert int(row.get("interval_seconds") or 0) == 7200
    assert int(row.get("timeout_seconds") or 0) == 50


def test_unregister_returns_false_when_missing(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    assert registry.unregister("__missing__") is False


def test_registry_multi_instance_register_preserves_rows(tmp_path: Path):
    db_path = tmp_path / "automations.json"
    reg_a = ar_mod.AutomationRegistry(db_path=db_path)
    reg_b = ar_mod.AutomationRegistry(db_path=db_path)

    first_id = reg_a.register(
        "first",
        {
            "task": "first task",
            "status": "active",
            "interval_seconds": 120,
        },
    )
    second_id = reg_b.register(
        "second",
        {
            "task": "second task",
            "status": "active",
            "interval_seconds": 120,
        },
    )

    reloaded = ar_mod.AutomationRegistry(db_path=db_path)
    assert first_id in reloaded.automations
    assert second_id in reloaded.automations


def test_registry_multi_instance_update_last_run_keeps_other_rows(tmp_path: Path):
    db_path = tmp_path / "automations.json"
    reg_a = ar_mod.AutomationRegistry(db_path=db_path)
    reg_b = ar_mod.AutomationRegistry(db_path=db_path)

    first_id = reg_a.register("first", {"task": "first", "status": "active"})
    second_id = reg_b.register("second", {"task": "second", "status": "active"})

    reg_a.update_last_run(first_id, last_status="ok", last_result={"success": True})
    reloaded = ar_mod.AutomationRegistry(db_path=db_path)
    assert first_id in reloaded.automations
    assert second_id in reloaded.automations
    assert reloaded.automations[first_id].get("last_status") == "ok"


def test_registry_get_active_refreshes_external_changes(tmp_path: Path):
    db_path = tmp_path / "automations.json"
    reg_a = ar_mod.AutomationRegistry(db_path=db_path)
    reg_b = ar_mod.AutomationRegistry(db_path=db_path)

    task_id = reg_b.register("external", {"task": "from another process", "status": "active"})
    active_ids = {str(row.get("id") or "") for row in reg_a.get_active()}

    assert task_id in active_ids


def test_registry_stale_instance_can_update_external_task(tmp_path: Path):
    db_path = tmp_path / "automations.json"
    reg_a = ar_mod.AutomationRegistry(db_path=db_path)
    reg_b = ar_mod.AutomationRegistry(db_path=db_path)

    task_id = reg_b.register("external", {"task": "from another process", "status": "active"})
    reg_a.update_last_run(task_id, last_status="ok", last_result={"success": True})

    reloaded = ar_mod.AutomationRegistry(db_path=db_path)
    assert reloaded.automations[task_id].get("last_status") == "ok"


@pytest.mark.asyncio
async def test_execute_with_policy_retries_then_succeeds(monkeypatch, tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")

    calls = {"count": 0}

    async def _fake_execute(task_id: str, task: dict, agent):
        _ = (task_id, task, agent)
        calls["count"] += 1
        if calls["count"] < 3:
            return {"success": False, "error": "temporary"}
        return {"success": True, "status": "ok"}

    async def _fast_sleep(seconds: float):
        _ = seconds
        return None

    monkeypatch.setattr(registry, "_execute_automation", _fake_execute)
    monkeypatch.setattr(ar_mod.asyncio, "sleep", _fast_sleep)

    outcome = await registry._execute_with_policy(
        "task_x",
        {
            "max_retries": 2,
            "retry_backoff_seconds": 1,
            "timeout_seconds": 30,
            "interval_seconds": 3600,
            "fail_streak": 0,
            "circuit_breaker_threshold": 3,
            "circuit_breaker_cooldown_seconds": 300,
        },
        agent=None,
    )

    assert outcome["ok"] is True
    assert outcome["status"] == "ok"
    assert outcome["attempts"] == 3
    assert calls["count"] == 3
    assert int(outcome["fail_streak"]) == 0


@pytest.mark.asyncio
async def test_execute_with_policy_opens_circuit_on_threshold(monkeypatch, tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")

    async def _fake_execute(task_id: str, task: dict, agent):
        _ = (task_id, task, agent)
        return {"success": False, "error": "hard_fail"}

    monkeypatch.setattr(registry, "_execute_automation", _fake_execute)

    outcome = await registry._execute_with_policy(
        "task_y",
        {
            "max_retries": 0,
            "retry_backoff_seconds": 1,
            "timeout_seconds": 30,
            "interval_seconds": 3600,
            "fail_streak": 2,
            "circuit_breaker_threshold": 3,
            "circuit_breaker_cooldown_seconds": 120,
        },
        agent=None,
    )

    assert outcome["ok"] is False
    assert outcome["status"] == "circuit_open"
    assert int(outcome["fail_streak"]) >= 3
    assert float(outcome["circuit_open_until"]) > time.time()


def test_get_module_health_snapshot(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    ok_id = registry.register_module("context_recovery")
    bad_id = registry.register_module("deep_work_protector")

    registry.update_last_run(
        ok_id,
        last_status="ok",
        runtime_patch={"fail_streak": 0, "circuit_open_until": 0.0},
    )
    registry.update_last_run(
        bad_id,
        last_status="failed",
        last_error="boom",
        runtime_patch={"fail_streak": 2, "circuit_open_until": time.time() + 60},
    )

    snap = registry.get_module_health(limit=10)
    summary = snap.get("summary") or {}
    rows = snap.get("modules") or []
    assert int(summary.get("active_modules") or 0) >= 2
    assert int(summary.get("healthy") or 0) >= 1
    assert int(summary.get("circuit_open") or 0) >= 1
    assert any(str(row.get("module_id")) == "context_recovery" for row in rows)


def test_list_module_tasks_includes_inactive_and_health(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    active_id = registry.register_module("context_recovery")
    paused_id = registry.register_module("deep_work_protector")
    assert registry.set_status(paused_id, "paused") is True

    registry.update_last_run(active_id, last_status="ok")
    registry.update_last_run(paused_id, last_status="failed", runtime_patch={"fail_streak": 1})

    rows = registry.list_module_tasks(include_inactive=True, limit=20)
    ids = {str(row.get("task_id")) for row in rows}
    assert active_id in ids
    assert paused_id in ids
    paused_row = next(row for row in rows if str(row.get("task_id")) == paused_id)
    assert paused_row["status"] == "paused"
    assert paused_row["health"] == "paused"


@pytest.mark.asyncio
async def test_run_task_now_executes_and_persists(monkeypatch, tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    task_id = registry.register_module("context_recovery", params={"workspace": str(tmp_path)})

    async def _fake_execute_with_policy(task_id_arg: str, task: dict, agent):
        _ = (task, agent)
        return {
            "ok": True,
            "status": "ok",
            "result": {"success": True, "module_id": "context_recovery"},
            "error": "",
            "attempts": 1,
            "duration_ms": 12,
            "fail_streak": 0,
            "next_retry_at": 0.0,
            "circuit_open_until": 0.0,
            "timeout_seconds": 120,
        }

    monkeypatch.setattr(registry, "_execute_with_policy", _fake_execute_with_policy)
    out = await registry.run_task_now(task_id, agent=None)
    assert out["success"] is True
    assert out["task_id"] == task_id

    reloaded = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    assert reloaded.automations[task_id].get("last_status") == "ok"


def test_update_module_task_updates_policy_and_params(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    task_id = registry.register_module("context_recovery", params={"workspace": str(tmp_path)})
    updated = registry.update_module_task(
        task_id,
        interval_seconds=1500,
        timeout_seconds=40,
        max_retries=4,
        retry_backoff_seconds=9,
        circuit_breaker_threshold=5,
        circuit_breaker_cooldown_seconds=240,
        params={"workspace": str(tmp_path / "nested"), "focus": "daily"},
        status="paused",
    )

    assert updated is not None
    assert int(updated.get("interval_seconds") or 0) == 1500
    assert int(updated.get("timeout_seconds") or 0) == 40
    assert int(updated.get("max_retries") or 0) == 4
    assert str(updated.get("status") or "") == "paused"
    params = updated.get("params") if isinstance(updated.get("params"), dict) else {}
    assert params.get("focus") == "daily"
    assert str(params.get("workspace") or "").endswith("/nested")


def test_reconcile_module_tasks_removes_duplicate_groups(tmp_path: Path):
    registry = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    registry.register(
        "dup1",
        {
            "id": "dup1",
            "module_id": "context_recovery",
            "user_id": "system",
            "channel": "automation",
            "params": {"workspace": str(tmp_path)},
            "status": "active",
            "created_at": 10.0,
            "last_run": 20.0,
        },
    )
    registry.register(
        "dup2",
        {
            "id": "dup2",
            "module_id": "context_recovery",
            "user_id": "system",
            "channel": "automation",
            "params": {"workspace": str(tmp_path)},
            "status": "active",
            "created_at": 11.0,
            "last_run": 21.0,
        },
    )
    registry.register(
        "other",
        {
            "id": "other",
            "module_id": "deep_work_protector",
            "user_id": "system",
            "channel": "automation",
            "params": {},
            "status": "active",
        },
    )

    result = registry.reconcile_module_tasks()
    assert int(result.get("removed_count") or 0) >= 1

    reloaded = ar_mod.AutomationRegistry(db_path=tmp_path / "automations.json")
    tasks = reloaded.list_module_tasks(include_inactive=True, limit=20)
    ctx_rows = [row for row in tasks if str(row.get("module_id")) == "context_recovery"]
    assert len(ctx_rows) == 1
