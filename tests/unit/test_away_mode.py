from __future__ import annotations

import asyncio

import pytest

from core.away_mode import AwayTaskRegistry, BackgroundTaskRunner, CompletionNotifier


def test_away_task_registry_create_and_resume_candidates(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="bitcoin araştır",
        user_id="u1",
        channel="telegram",
        capability_domain="research",
        workflow_id="research_workflow",
    )
    assert record.task_id.startswith("away_")
    assert registry.get(record.task_id) is not None
    candidates = registry.list_resume_candidates()
    assert len(candidates) == 1
    assert candidates[0].task_id == record.task_id


def test_away_task_registry_cancel_and_requeue(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    record = registry.create(
        user_input="rapor hazırla",
        user_id="u1",
        channel="telegram",
    )
    cancelled = registry.cancel(record.task_id)
    assert cancelled is not None
    assert cancelled.state == "cancelled"

    requeued = registry.requeue(record.task_id)
    assert requeued is not None
    assert requeued.state == "queued"
    assert requeued.result_summary == ""


@pytest.mark.asyncio
async def test_background_task_runner_executes_and_notifies(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    seen = []
    notifier = CompletionNotifier()

    async def _on_done(record):
        seen.append((record.task_id, record.state))

    notifier.register(_on_done)
    runner = BackgroundTaskRunner(registry, notifier)

    async def _handler(record):
        return {"status": "success", "run_id": "run1", "summary": f"done:{record.user_input}"}

    record = await runner.submit(
        user_input="ekrana bak",
        user_id="u2",
        channel="cli",
        capability_domain="screen_operator",
        workflow_id="screen_operator_workflow",
        handler=_handler,
    )

    await runner._running[record.task_id]
    stored = registry.get(record.task_id)
    assert stored is not None
    assert stored.state == "completed"
    assert seen == [(record.task_id, "completed")]


@pytest.mark.asyncio
async def test_background_task_runner_resume_loop_picks_queued_task(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    notifier = CompletionNotifier()
    runner = BackgroundTaskRunner(registry, notifier)
    record = registry.create(
        user_input="rapor hazırla",
        user_id="u3",
        channel="telegram",
        capability_domain="research",
        workflow_id="research_workflow",
    )
    seen = []

    async def _handler(task_record):
        seen.append(task_record.task_id)
        return {"status": "success", "run_id": "run2", "summary": "done"}

    await runner.start_resume_loop(_handler, interval_s=0.01)
    try:
        await asyncio.sleep(0.05)
    finally:
        await runner.stop_resume_loop()

    stored = registry.get(record.task_id)
    assert seen == [record.task_id]
    assert stored is not None
    assert stored.state == "completed"


@pytest.mark.asyncio
async def test_background_task_runner_retry_requeues_and_runs(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    runner = BackgroundTaskRunner(registry, CompletionNotifier())
    record = registry.create(
        user_input="ekrana bak",
        user_id="u1",
        channel="cli",
    )
    registry.update(record.task_id, state="failed", error="boom")
    seen = []

    async def _handler(task_record):
        seen.append(task_record.task_id)
        return {"status": "success", "summary": "ok"}

    runner.set_resume_handler(_handler)
    retried = await runner.retry(record.task_id)
    assert retried is not None
    await runner._running[record.task_id]
    stored = registry.get(record.task_id)
    assert seen == [record.task_id]
    assert stored is not None
    assert stored.state == "completed"


@pytest.mark.asyncio
async def test_background_task_runner_auto_retries_partial_result(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    notifier = CompletionNotifier()
    runner = BackgroundTaskRunner(registry, notifier)
    seen = []
    completed = []

    async def _on_done(record):
        completed.append((record.task_id, record.state, record.retry_count))

    notifier.register(_on_done)
    attempts = {"count": 0}

    async def _handler(task_record):
        attempts["count"] += 1
        seen.append((task_record.task_id, task_record.retry_count))
        if attempts["count"] == 1:
            return {"status": "partial", "summary": "need another pass"}
        return {"status": "success", "summary": "done"}

    record = await runner.submit(
        user_input="rapor hazırla",
        user_id="u9",
        channel="telegram",
        capability_domain="research",
        workflow_id="research_workflow",
        handler=_handler,
        metadata={"auto_retry": True, "max_retries": 2},
    )

    await runner._running[record.task_id]
    mid = registry.get(record.task_id)
    assert mid is not None
    assert mid.state == "queued"
    assert mid.retry_count == 1
    assert completed == []

    registry.update(record.task_id, next_retry_at=0.0)
    runner.set_resume_handler(_handler)
    resumed = await runner.resume_pending()
    assert resumed == [record.task_id]
    await runner._running[record.task_id]

    stored = registry.get(record.task_id)
    assert stored is not None
    assert stored.state == "completed"
    assert attempts["count"] == 2
    assert completed == [(record.task_id, "completed", 1)]


@pytest.mark.asyncio
async def test_background_task_runner_auto_retry_exhaustion_notifies_failure(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    notifier = CompletionNotifier()
    runner = BackgroundTaskRunner(registry, notifier)
    completed = []

    async def _on_done(record):
        completed.append((record.task_id, record.state, record.retry_count))

    notifier.register(_on_done)

    async def _handler(task_record):
        raise RuntimeError(f"boom:{task_record.retry_count}")

    record = await runner.submit(
        user_input="kod üret",
        user_id="u8",
        channel="cli",
        capability_domain="coding",
        workflow_id="coding_workflow",
        handler=_handler,
        metadata={"auto_retry": True, "max_retries": 1},
    )

    await runner._running[record.task_id]
    stored = registry.get(record.task_id)
    assert stored is not None
    assert stored.state == "queued"
    assert stored.retry_count == 1
    assert completed == []

    registry.update(record.task_id, next_retry_at=0.0)
    runner.set_resume_handler(_handler)
    resumed = await runner.resume_pending()
    assert resumed == [record.task_id]
    await runner._running[record.task_id]

    failed = registry.get(record.task_id)
    assert failed is not None
    assert failed.state == "failed"
    assert completed == [(record.task_id, "failed", 1)]


@pytest.mark.asyncio
async def test_background_task_runner_respects_retry_on_partial_flag(tmp_path):
    registry = AwayTaskRegistry(storage_path=tmp_path / "away_tasks.json")
    notifier = CompletionNotifier()
    runner = BackgroundTaskRunner(registry, notifier)
    completed = []

    async def _on_done(record):
        completed.append((record.task_id, record.state))

    notifier.register(_on_done)

    async def _handler(task_record):
        return {"status": "partial", "summary": "screen partially read"}

    record = await runner.submit(
        user_input="ekrana bak",
        user_id="u10",
        channel="telegram",
        capability_domain="screen_operator",
        workflow_id="screen_operator_workflow",
        handler=_handler,
        metadata={"auto_retry": True, "max_retries": 2, "retry_on_partial": False, "retry_on_failure": True},
    )

    await runner._running[record.task_id]
    stored = registry.get(record.task_id)
    assert stored is not None
    assert stored.state == "partial"
    assert completed == [(record.task_id, "partial")]
