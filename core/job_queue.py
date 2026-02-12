"""
Message Queue & Job System
Async job processing, priority queues, retry logic, worker pools
"""

import asyncio
import time
import uuid
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from enum import Enum
from collections import deque
import heapq

from utils.logger import get_logger

logger = get_logger("job_queue")


class JobStatus(Enum):
    """Job status"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"


class JobPriority(Enum):
    """Job priority levels"""
    LOW = 0
    NORMAL = 1
    HIGH = 2
    CRITICAL = 3


@dataclass
class Job:
    """Represents a job"""
    job_id: str
    task: Callable
    args: tuple = field(default_factory=tuple)
    kwargs: Dict[str, Any] = field(default_factory=dict)
    priority: JobPriority = JobPriority.NORMAL
    status: JobStatus = JobStatus.PENDING
    max_retries: int = 3
    retry_count: int = 0
    retry_delay: float = 1.0  # seconds
    timeout: Optional[float] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    queue_name: str = "default"

    def __lt__(self, other):
        """For priority queue ordering"""
        return self.priority.value > other.priority.value


class JobQueue:
    """
    Message Queue & Job System
    - Priority-based job queues
    - Worker pools
    - Retry logic with exponential backoff
    - Job scheduling (delayed jobs)
    - Job dependencies
    - Worker health monitoring
    """

    def __init__(self, max_workers: int = 4):
        self.queues: Dict[str, List[Job]] = {}  # queue_name -> priority heap
        self.workers: List[asyncio.Task] = []
        self.max_workers = max_workers
        self.running_jobs: Dict[str, Job] = {}
        self.completed_jobs: deque = deque(maxlen=1000)
        self.failed_jobs: deque = deque(maxlen=100)
        self.job_index: Dict[str, Job] = {}
        self.worker_stats: Dict[int, Dict[str, Any]] = {}
        self.running = False

        # Create default queue
        self.queues["default"] = []

        logger.info(f"Job Queue initialized with {max_workers} workers")

    def enqueue(
        self,
        task: Callable,
        *args,
        priority: JobPriority = JobPriority.NORMAL,
        max_retries: int = 3,
        timeout: Optional[float] = None,
        queue_name: str = "default",
        delay: float = 0,
        **kwargs
    ) -> str:
        """Enqueue a job"""
        job_id = str(uuid.uuid4())[:8]

        job = Job(
            job_id=job_id,
            task=task,
            args=args,
            kwargs=kwargs,
            priority=priority,
            max_retries=max_retries,
            timeout=timeout,
            queue_name=queue_name
        )

        self.job_index[job_id] = job

        if delay > 0:
            # Schedule job
            asyncio.create_task(self._delayed_enqueue(job, delay))
        else:
            # Add to queue immediately
            self._add_to_queue(job)

        logger.debug(f"Job enqueued: {job_id} (priority: {priority.value}, queue: {queue_name})")

        return job_id

    async def _delayed_enqueue(self, job: Job, delay: float):
        """Enqueue job after delay"""
        await asyncio.sleep(delay)
        self._add_to_queue(job)

    def _add_to_queue(self, job: Job):
        """Add job to priority queue"""
        if job.queue_name not in self.queues:
            self.queues[job.queue_name] = []

        job.status = JobStatus.QUEUED
        heapq.heappush(self.queues[job.queue_name], job)

    async def start_workers(self):
        """Start worker pool"""
        self.running = True

        for i in range(self.max_workers):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
            self.worker_stats[i] = {
                "jobs_completed": 0,
                "jobs_failed": 0,
                "total_time": 0
            }

        logger.info(f"Started {self.max_workers} workers")

    async def stop_workers(self):
        """Stop worker pool"""
        self.running = False

        # Wait for workers to finish
        await asyncio.gather(*self.workers, return_exceptions=True)

        self.workers.clear()
        logger.info("Workers stopped")

    async def _worker(self, worker_id: int):
        """Worker task that processes jobs"""
        logger.info(f"Worker {worker_id} started")

        while self.running:
            try:
                # Get next job from any queue (priority order)
                job = await self._get_next_job()

                if job is None:
                    # No jobs available, wait a bit
                    await asyncio.sleep(0.1)
                    continue

                # Process job
                await self._process_job(job, worker_id)

            except Exception as e:
                logger.error(f"Worker {worker_id} error: {e}")

        logger.info(f"Worker {worker_id} stopped")

    async def _get_next_job(self) -> Optional[Job]:
        """Get next job from queues"""
        # Check all queues, prioritize by job priority
        all_jobs = []

        for queue_name, queue in self.queues.items():
            if queue:
                all_jobs.append((queue[0], queue_name))

        if not all_jobs:
            return None

        # Get highest priority job
        job, queue_name = max(all_jobs, key=lambda x: x[0].priority.value)

        # Remove from queue
        heapq.heappop(self.queues[queue_name])

        return job

    async def _process_job(self, job: Job, worker_id: int):
        """Process a single job"""
        job.status = JobStatus.RUNNING
        job.started_at = time.time()
        self.running_jobs[job.job_id] = job

        logger.info(f"Worker {worker_id} processing job: {job.job_id}")

        try:
            # Execute task with timeout
            if asyncio.iscoroutinefunction(job.task):
                if job.timeout:
                    result = await asyncio.wait_for(
                        job.task(*job.args, **job.kwargs),
                        timeout=job.timeout
                    )
                else:
                    result = await job.task(*job.args, **job.kwargs)
            else:
                result = job.task(*job.args, **job.kwargs)

            # Job completed successfully
            job.result = result
            job.status = JobStatus.COMPLETED
            job.completed_at = time.time()

            self.completed_jobs.append(job)
            self.worker_stats[worker_id]["jobs_completed"] += 1

            logger.info(f"Job completed: {job.job_id}")

        except asyncio.TimeoutError:
            logger.warning(f"Job timeout: {job.job_id}")
            await self._handle_job_failure(job, "Timeout", worker_id)

        except Exception as e:
            logger.error(f"Job failed: {job.job_id} - {e}")
            await self._handle_job_failure(job, str(e), worker_id)

        finally:
            # Update stats
            if job.started_at and job.completed_at:
                duration = job.completed_at - job.started_at
                self.worker_stats[worker_id]["total_time"] += duration

            # Remove from running
            if job.job_id in self.running_jobs:
                del self.running_jobs[job.job_id]

    async def _handle_job_failure(self, job: Job, error: str, worker_id: int):
        """Handle job failure with retry logic"""
        job.error = error
        job.retry_count += 1

        if job.retry_count < job.max_retries:
            # Retry with exponential backoff
            job.status = JobStatus.RETRYING
            retry_delay = job.retry_delay * (2 ** (job.retry_count - 1))

            logger.info(f"Retrying job {job.job_id} in {retry_delay}s (attempt {job.retry_count}/{job.max_retries})")

            # Re-enqueue after delay
            await asyncio.sleep(retry_delay)
            self._add_to_queue(job)

        else:
            # Max retries reached
            job.status = JobStatus.FAILED
            job.completed_at = time.time()
            self.failed_jobs.append(job)
            self.worker_stats[worker_id]["jobs_failed"] += 1

            logger.error(f"Job failed permanently: {job.job_id} after {job.retry_count} retries")

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a job"""
        if job_id not in self.job_index:
            return False

        job = self.job_index[job_id]

        if job.status in [JobStatus.PENDING, JobStatus.QUEUED]:
            job.status = JobStatus.CANCELLED
            # Remove from queue
            if job.queue_name in self.queues:
                self.queues[job.queue_name] = [
                    j for j in self.queues[job.queue_name]
                    if j.job_id != job_id
                ]
                heapq.heapify(self.queues[job.queue_name])

            logger.info(f"Job cancelled: {job_id}")
            return True

        return False

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get job status"""
        if job_id not in self.job_index:
            return None

        job = self.job_index[job_id]

        return {
            "job_id": job.job_id,
            "status": job.status.value,
            "priority": job.priority.value,
            "retry_count": job.retry_count,
            "max_retries": job.max_retries,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "duration": (job.completed_at - job.started_at) if job.completed_at and job.started_at else None,
            "result": job.result,
            "error": job.error
        }

    def get_queue_stats(self) -> Dict[str, Any]:
        """Get queue statistics"""
        total_queued = sum(len(q) for q in self.queues.values())

        return {
            "queues": {
                name: len(queue)
                for name, queue in self.queues.items()
            },
            "total_queued": total_queued,
            "running": len(self.running_jobs),
            "completed": len(self.completed_jobs),
            "failed": len(self.failed_jobs),
            "workers": len(self.workers),
            "worker_stats": self.worker_stats
        }

    def get_worker_health(self) -> List[Dict[str, Any]]:
        """Get worker health status"""
        health = []

        for worker_id, stats in self.worker_stats.items():
            total_jobs = stats["jobs_completed"] + stats["jobs_failed"]
            success_rate = (stats["jobs_completed"] / total_jobs * 100) if total_jobs > 0 else 0

            health.append({
                "worker_id": worker_id,
                "jobs_completed": stats["jobs_completed"],
                "jobs_failed": stats["jobs_failed"],
                "success_rate": f"{success_rate:.1f}%",
                "total_time": f"{stats['total_time']:.2f}s"
            })

        return health


# Global instance
_job_queue: Optional[JobQueue] = None


def get_job_queue() -> JobQueue:
    """Get or create global job queue instance"""
    global _job_queue
    if _job_queue is None:
        _job_queue = JobQueue()
    return _job_queue
