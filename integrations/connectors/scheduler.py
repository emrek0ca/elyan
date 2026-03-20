from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any

from core.proactive.scheduler import get_scheduler

from ..base import BaseConnector, ConnectorResult, ConnectorSnapshot, ConnectorState


async def _fallback_job_runner(**kwargs: Any) -> dict[str, Any]:
    return {
        "success": True,
        "kwargs": kwargs,
    }


class SchedulerConnector(BaseConnector):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._scheduler = get_scheduler()
        self._last_jobs: list[dict[str, Any]] = []

    async def connect(self, app_name_or_url: str, **kwargs: Any) -> ConnectorResult:
        started = time.perf_counter()
        try:
            await self._scheduler.start()
        except Exception:
            pass
        snapshot = await self.snapshot()
        return self._result(
            success=True,
            status="ready",
            message="scheduler_ready",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            snapshot=snapshot,
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
        )

    async def execute(self, action: dict[str, Any]) -> ConnectorResult:
        started = time.perf_counter()
        payload = dict(action or {})
        kind = str(payload.get("kind") or payload.get("action") or "").strip().lower()
        scheduler = self._scheduler
        try:
            await scheduler.start()
        except Exception:
            pass

        if kind in {"list_jobs", "jobs", "snapshot"}:
            jobs = scheduler.get_jobs()
            self._last_jobs = list(jobs)
            snapshot = await self.snapshot()
            return self._result(
                success=True,
                status="success",
                message="jobs_listed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                result={"jobs": jobs},
                evidence=[{"kind": "scheduler_state", "jobs": len(jobs)}],
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
            )

        if kind in {"remove_job", "delete_job"}:
            ok = bool(scheduler.remove_job(str(payload.get("job_id") or payload.get("id") or "")))
            snapshot = await self.snapshot()
            return self._result(
                success=ok,
                status="success" if ok else "failed",
                message="job_removed" if ok else "job_remove_failed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                result={"removed": ok},
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
            )

        if kind in {"pause_job", "pause"}:
            ok = bool(scheduler.pause_job(str(payload.get("job_id") or payload.get("id") or "")))
            snapshot = await self.snapshot()
            return self._result(
                success=ok,
                status="success" if ok else "failed",
                message="job_paused" if ok else "job_pause_failed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                result={"paused": ok},
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
            )

        if kind in {"resume_job", "resume"}:
            ok = bool(scheduler.resume_job(str(payload.get("job_id") or payload.get("id") or "")))
            snapshot = await self.snapshot()
            return self._result(
                success=ok,
                status="success" if ok else "failed",
                message="job_resumed" if ok else "job_resume_failed",
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                result={"resumed": ok},
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
            )

        if kind in {"run_job", "trigger", "execute"} and payload.get("job_id"):
            try:
                data = await scheduler.run_job(str(payload.get("job_id") or ""))
                ok = bool(data.get("success"))
            except Exception as exc:
                data = {"success": False, "error": str(exc)}
                ok = False
            snapshot = await self.snapshot()
            return self._result(
                success=ok,
                status="success" if ok else "failed",
                message="job_executed" if ok else "job_execute_failed",
                error=str(data.get("error") or ""),
                latency_ms=(time.perf_counter() - started) * 1000.0,
                snapshot=snapshot,
                result=data,
                evidence=[{"kind": "scheduler_run", "job_id": str(payload.get("job_id") or "")}],
                auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
            )

        schedule_type = str(payload.get("schedule_type") or payload.get("type") or "").strip().lower()
        callback = payload.get("callback")
        job_id = str(payload.get("job_id") or payload.get("id") or payload.get("name") or f"job_{int(time.time())}").strip()
        run_time = payload.get("run_time") or payload.get("run_at")
        minutes = payload.get("minutes") or payload.get("interval_minutes")
        hour = payload.get("hour")
        minute = payload.get("minute", 0)

        job_callable = callback if callable(callback) else _fallback_job_runner
        created = None
        if schedule_type in {"once", "date"} and run_time:
            if isinstance(run_time, str):
                try:
                    run_dt = datetime.fromisoformat(run_time)
                except Exception:
                    run_dt = datetime.now() + timedelta(minutes=1)
            elif isinstance(run_time, datetime):
                run_dt = run_time
            else:
                run_dt = datetime.now() + timedelta(minutes=1)
            created = scheduler.schedule_once(job_callable, run_dt, job_id=job_id, **{k: v for k, v in payload.items() if k not in {"callback"}})
        elif schedule_type in {"daily", "cron"} and hour is not None:
            created = scheduler.schedule_daily(job_callable, int(hour), int(minute or 0), job_id=job_id, **{k: v for k, v in payload.items() if k not in {"callback"}})
        else:
            interval_minutes = int(minutes or 15)
            created = scheduler.schedule_interval(job_callable, interval_minutes, job_id=job_id, **{k: v for k, v in payload.items() if k not in {"callback"}})
        jobs = scheduler.get_jobs()
        self._last_jobs = list(jobs)
        snapshot = await self.snapshot()
        return self._result(
            success=True,
            status="success",
            message="job_scheduled",
            latency_ms=(time.perf_counter() - started) * 1000.0,
            snapshot=snapshot,
            result={"job_id": job_id, "scheduled": True, "job": str(created)},
            evidence=[{"kind": "scheduler_job", "job_id": job_id}],
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
        )

    async def snapshot(self) -> ConnectorSnapshot:
        try:
            jobs = self._scheduler.get_jobs()
        except Exception:
            jobs = []
        self._last_jobs = list(jobs)
        return self._snapshot(
            state="ready",
            metadata={
                "jobs": jobs,
                "started": getattr(self._scheduler, "_started", False),
            },
            auth_state=self.auth_account.status if self.auth_account else ConnectorState.READY,
        )
