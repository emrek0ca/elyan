"""
Proactive Scheduler - Unified scheduling system using APScheduler

Provides task automation capabilities:
- Daily scheduled tasks (cron)
- Interval-based tasks
- One-time scheduled tasks
- Persistent job storage (SQLite)
"""

import asyncio
from datetime import datetime, time as dt_time
from typing import Callable, Optional, Any
from pathlib import Path
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from utils.logger import get_logger

logger = get_logger("proactive_scheduler")


class ProactiveScheduler:
    """
    Unified scheduler for all proactive Elyan features.
    
    Uses APScheduler with SQLite persistence to survive restarts.
    """
    
    def __init__(self):
        # Ensure wiqo data directory exists
        wiqo_dir = Path.home() / ".wiqo"
        wiqo_dir.mkdir(exist_ok=True)
        
        # Configure job store (SQLite for persistence)
        jobstores = {
            'default': SQLAlchemyJobStore(url=f'sqlite:///{wiqo_dir}/scheduler.db')
        }
        
        # Configure executor
        executors = {
            'default': AsyncIOExecutor()
        }
        
        # Job defaults
        job_defaults = {
            'coalesce': True,  # Combine missed runs
            'max_instances': 1,  # Prevent overlapping executions
            'misfire_grace_time': 300  # 5 min grace period
        }
        
        self.scheduler = AsyncIOScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone='Europe/Istanbul'
        )
        
        self._started = False
        logger.info("ProactiveScheduler initialized")
    
    async def start(self):
        """Start the scheduler"""
        if not self._started:
            self.scheduler.start()
            self._started = True
            logger.info(" Scheduler started")
    
    async def shutdown(self):
        """Gracefully shutdown scheduler"""
        if self._started:
            self.scheduler.shutdown(wait=True)
            self._started = False
            logger.info("Scheduler shutdown")
    
    def schedule_daily(
        self,
        func: Callable,
        hour: int,
        minute: int = 0,
        job_id: Optional[str] = None,
        **kwargs
    ):
        """
        Schedule a daily task at specific time.
        
        Args:
            func: Async or sync function to execute
            hour: Hour of day (0-23)
            minute: Minute of hour (0-59)
            job_id: Optional unique identifier
            **kwargs: Additional arguments to pass to func
        
        Returns:
            APScheduler Job object
        """
        trigger = CronTrigger(hour=hour, minute=minute, timezone='Europe/Istanbul')
        
        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs=kwargs
        )
        
        logger.info(f"📅 Scheduled daily job '{job_id or func.__name__}' at {hour:02d}:{minute:02d}")
        return job
    
    def schedule_interval(
        self,
        func: Callable,
        minutes: int,
        job_id: Optional[str] = None,
        **kwargs
    ):
        """
        Schedule a repeating task at fixed intervals.
        
        Args:
            func: Async or sync function to execute
            minutes: Interval in minutes
            job_id: Optional unique identifier
            **kwargs: Additional arguments to pass to func
        
        Returns:
            APScheduler Job object
        """
        trigger = IntervalTrigger(minutes=minutes)
        
        job = self.scheduler.add_job(
            func,
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            kwargs=kwargs
        )
        
        logger.info(f"🔁 Scheduled interval job '{job_id or func.__name__}' every {minutes} min")
        return job
    
    def schedule_once(
        self,
        func: Callable,
        run_time: datetime,
        job_id: Optional[str] = None,
        **kwargs
    ):
        """
        Schedule a one-time task.
        
        Args:
            func: Async or sync function to execute
            run_time: When to execute
            job_id: Optional unique identifier
            **kwargs: Additional arguments to pass to func
        
        Returns:
            APScheduler Job object
        """
        job = self.scheduler.add_job(
            func,
            trigger='date',
            run_date=run_time,
            id=job_id,
            replace_existing=True,
            kwargs=kwargs
        )
        
        logger.info(f" Scheduled one-time job '{job_id or func.__name__}' at {run_time}")
        return job
    
    def remove_job(self, job_id: str):
        """Remove a scheduled job"""
        try:
            self.scheduler.remove_job(job_id)
            logger.info(f"Removed job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to remove job {job_id}: {e}")
            return False
    
    def get_jobs(self):
        """Get list of all scheduled jobs"""
        jobs = self.scheduler.get_jobs()
        return [
            {
                'id': job.id,
                'name': job.name,
                'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
                'trigger': str(job.trigger)
            }
            for job in jobs
        ]
    
    def pause_job(self, job_id: str):
        """Pause a job without removing it"""
        try:
            self.scheduler.pause_job(job_id)
            logger.info(f"Paused job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to pause job {job_id}: {e}")
            return False
    
    def resume_job(self, job_id: str):
        """Resume a paused job"""
        try:
            self.scheduler.resume_job(job_id)
            logger.info(f"Resumed job: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to resume job {job_id}: {e}")
            return False


# Global singleton instance
_scheduler: Optional[ProactiveScheduler] = None


def get_scheduler() -> ProactiveScheduler:
    """Get singleton scheduler instance"""
    global _scheduler
    if _scheduler is None:
        _scheduler = ProactiveScheduler()
    return _scheduler


def schedule_job(
    func: Callable,
    schedule_type: str,
    job_id: Optional[str] = None,
    **params
):
    """
    Convenience function to schedule a job.
    
    Args:
        func: Function to execute
        schedule_type: 'daily', 'interval', or 'once'
        job_id: Optional job identifier
        **params: Schedule-specific parameters
            - For 'daily': hour, minute
            - For 'interval': minutes
            - For 'once': run_time
    
    Example:
        schedule_job(my_func, 'daily', hour=8, minute=0, job_id='morning_task')
        schedule_job(my_func, 'interval', minutes=30, job_id='check_task')
    """
    scheduler = get_scheduler()
    
    if schedule_type == 'daily':
        return scheduler.schedule_daily(func, job_id=job_id, **params)
    elif schedule_type == 'interval':
        return scheduler.schedule_interval(func, job_id=job_id, **params)
    elif schedule_type == 'once':
        return scheduler.schedule_once(func, job_id=job_id, **params)
    else:
        raise ValueError(f"Unknown schedule_type: {schedule_type}")
