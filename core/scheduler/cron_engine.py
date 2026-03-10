"""
Cron Engine — scheduled task management with persistence.

Capabilities:
- Jobs persisted to ~/.elyan/cron_jobs.json
- Jobs survive restart (loaded from disk on start)
- Prompt jobs and multi-step routine jobs
- Run history for diagnostics and reports
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from config.elyan_config import elyan_config
from core.storage_paths import resolve_elyan_data_dir
from core.scheduler.routine_engine import routine_engine
from utils.logger import get_logger

logger = get_logger("cron_engine")

def _default_cron_persist_path() -> Path:
    return resolve_elyan_data_dir() / "cron_jobs.json"


CRON_PERSIST_PATH = _default_cron_persist_path()

JobReportCallback = Callable[[Dict[str, Any], bool, str], Awaitable[None]]


def _now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class CronEngine:
    """Handles scheduled tasks using cron expressions — with disk persistence."""

    def __init__(self, agent):
        self.agent = agent
        self.scheduler = AsyncIOScheduler()
        self._is_running = False
        self._jobs: Dict[str, Dict[str, Any]] = {}
        self._report_callback: Optional[JobReportCallback] = None

    @property
    def running(self) -> bool:
        return self._is_running

    def set_report_callback(self, callback: Optional[JobReportCallback]) -> None:
        self._report_callback = callback

    async def start(self):
        """Load jobs from config + persisted jobs, then start scheduler."""
        if self._is_running:
            return

        self._jobs.clear()

        config_jobs = elyan_config.get("cron", [])
        if isinstance(config_jobs, list):
            for job_data in config_jobs:
                if not isinstance(job_data, dict):
                    continue
                normalized = self._normalize_job(job_data, source="config")
                self._jobs[normalized["id"]] = normalized

        persisted = self._load_persisted()
        for jid, job_data in persisted.items():
            if jid not in self._jobs:  # config takes precedence
                self._jobs[jid] = self._normalize_job(job_data, source=job_data.get("source", "runtime"))

        for job_data in self._jobs.values():
            if job_data.get("enabled", True):
                self._schedule_job(job_data)

        self.scheduler.start()
        self._is_running = True
        logger.info(f"Cron engine started with {len(self._jobs)} jobs.")

    async def stop(self):
        """Stop the scheduler."""
        if self._is_running:
            self.scheduler.shutdown(wait=False)
            self._is_running = False
        logger.info("Cron engine stopped.")

    def _normalize_job(self, job_data: Dict[str, Any], source: str = "runtime") -> Dict[str, Any]:
        normalized = dict(job_data)
        normalized["id"] = str(normalized.get("id") or str(uuid.uuid4())[:10])
        normalized["expression"] = str(normalized.get("expression") or "").strip()
        normalized["enabled"] = bool(normalized.get("enabled", True))
        normalized["source"] = normalized.get("source", source)
        normalized["job_type"] = str(normalized.get("job_type", "prompt")).strip().lower() or "prompt"
        normalized["prompt"] = str(normalized.get("prompt", "") or "")
        normalized["channel"] = str(normalized.get("channel", "telegram") or "telegram")
        normalized["channel_id"] = str(normalized.get("channel_id", "") or "")
        normalized["created_at"] = str(normalized.get("created_at", "") or _now_iso())
        normalized["updated_at"] = _now_iso()
        if "history" not in normalized or not isinstance(normalized.get("history"), list):
            normalized["history"] = []
        return normalized

    def add_job(self, job_data: Dict[str, Any]) -> str:
        """Add or update a runtime job and persist it. Returns job ID."""
        normalized = self._normalize_job(job_data, source=job_data.get("source", "runtime"))
        jid = normalized["id"]
        self._jobs[jid] = normalized

        if self._is_running:
            if normalized.get("enabled", True):
                self._schedule_job(normalized)
            else:
                try:
                    self.scheduler.remove_job(jid)
                except Exception:
                    pass

        self._persist()
        logger.info(f"Added cron job: {jid} -> '{normalized.get('expression')}'")
        return jid

    def sync_job(self, job_data: Dict[str, Any]) -> str:
        """Alias for add_job used by higher-level managers."""
        return self.add_job(job_data)

    def remove_job(self, job_id: str) -> bool:
        job_id = str(job_id or "").strip()
        if job_id not in self._jobs:
            return False

        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass

        del self._jobs[job_id]
        self._persist()
        logger.info(f"Removed cron job: {job_id}")
        return True

    def enable_job(self, job_id: str) -> bool:
        job_id = str(job_id or "").strip()
        if job_id not in self._jobs:
            return False
        self._jobs[job_id]["enabled"] = True
        self._jobs[job_id]["updated_at"] = _now_iso()
        if self._is_running:
            self._schedule_job(self._jobs[job_id])
        self._persist()
        return True

    def disable_job(self, job_id: str) -> bool:
        job_id = str(job_id or "").strip()
        if job_id not in self._jobs:
            return False
        self._jobs[job_id]["enabled"] = False
        self._jobs[job_id]["updated_at"] = _now_iso()
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass
        self._persist()
        return True

    def list_jobs(self) -> List[Dict[str, Any]]:
        """Return all jobs with next run time."""
        result: List[Dict[str, Any]] = []
        for jid, job_data in self._jobs.items():
            entry = dict(job_data)
            try:
                apsjob = self.scheduler.get_job(jid)
                entry["next_run"] = apsjob.next_run_time.isoformat() if apsjob and apsjob.next_run_time else None
            except Exception:
                entry["next_run"] = None
            result.append(entry)
        result.sort(key=lambda x: (not bool(x.get("enabled", True)), x.get("id", "")))
        return result

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self._jobs.get(str(job_id or "").strip())

    def get_history(self, job_id: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        lim = max(1, int(limit or 20))
        if job_id:
            job = self.get_job(job_id)
            if not job:
                return []
            hist = list(job.get("history", []))
            hist.reverse()
            return hist[:lim]

        merged: List[Dict[str, Any]] = []
        for jid, job in self._jobs.items():
            for item in job.get("history", []):
                merged.append({"job_id": jid, **item})
        merged.sort(key=lambda x: x.get("ts", ""), reverse=True)
        return merged[:lim]

    async def run_job(self, job_id: str) -> Dict[str, Any]:
        """Run a job immediately and return execution result."""
        job = self.get_job(job_id)
        if not job:
            return {"success": False, "error": "job not found", "job_id": job_id}

        logger.info(f"Executing scheduled job: {job_id}")
        started_at = datetime.now().isoformat()
        started_ts = datetime.now().timestamp()
        success = False
        report = ""

        try:
            report = await self._execute_job(job)
            success = True
        except Exception as e:
            report = f"Cron job error: {e}"
            logger.error(f"Error in cron task {job_id}: {e}")

        duration_s = round(max(0.0, datetime.now().timestamp() - started_ts), 2)
        history_item = {
            "ts": _now_iso(),
            "started_at": started_at,
            "success": success,
            "duration_s": duration_s,
            "summary": str(report or "")[:1500],
        }
        history = list(job.get("history", []))
        history.append(history_item)
        if len(history) > 50:
            history = history[-50:]
        job["history"] = history
        job["last_run"] = _now_iso()
        job["updated_at"] = _now_iso()
        self._persist()

        if self._report_callback:
            try:
                await self._report_callback(job, success, report)
            except Exception as cb_err:
                logger.warning(f"Cron report callback failed for {job_id}: {cb_err}")

        return {
            "success": success,
            "job_id": job_id,
            "job_type": job.get("job_type", "prompt"),
            "duration_s": duration_s,
            "report": report,
        }

    async def _execute_job(self, job: Dict[str, Any]) -> str:
        job_type = str(job.get("job_type", "prompt") or "prompt").lower()
        if job_type == "routine":
            routine_id = str(job.get("routine_id", "")).strip()
            if not routine_id:
                raise ValueError("routine_id missing")
            res = await routine_engine.run_routine(routine_id, self.agent)
            if not res.get("success", False):
                raise ValueError(res.get("error") or "routine execution failed")
            return str(res.get("report", "") or "")

        prompt = str(job.get("prompt", "") or "").strip()
        if not prompt:
            raise ValueError("prompt missing")
        response = await self.agent.process(prompt)
        return str(response or "")

    def _schedule_job(self, job_data: Dict[str, Any]) -> None:
        job_id = str(job_data.get("id") or "").strip()
        expression = str(job_data.get("expression") or "").strip()
        if not job_id or not expression:
            logger.warning(f"Job has missing id/expression: {job_data}")
            return
        try:
            trigger = CronTrigger.from_crontab(expression)
            self.scheduler.add_job(
                self._run_task,
                trigger,
                args=[job_id],
                id=job_id,
                replace_existing=True,
            )
            logger.info(f"Scheduled job: {job_id} -> '{expression}'")
        except Exception as e:
            logger.error(f"Failed to schedule job {job_id}: {e}")

    async def _run_task(self, job_id: str):
        await self.run_job(job_id)

    def _persist(self) -> None:
        """Save runtime jobs to disk (config jobs come from elyan.json)."""
        try:
            CRON_PERSIST_PATH.parent.mkdir(parents=True, exist_ok=True)
            runtime_jobs = {
                jid: job
                for jid, job in self._jobs.items()
                if str(job.get("source", "runtime")) == "runtime"
            }
            with open(CRON_PERSIST_PATH, "w", encoding="utf-8") as f:
                json.dump(runtime_jobs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to persist cron jobs: {e}")

    def _load_persisted(self) -> Dict[str, Dict[str, Any]]:
        if not CRON_PERSIST_PATH.exists():
            return {}
        try:
            with open(CRON_PERSIST_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {}
            logger.info(f"Loaded {len(data)} persisted cron jobs from {CRON_PERSIST_PATH}")
            return data
        except Exception as e:
            logger.error(f"Failed to load persisted cron jobs: {e}")
            return {}
