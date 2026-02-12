"""
Batch File Processing System
Processes multiple files in parallel with proper error handling and progress tracking
"""

import asyncio
from typing import Dict, List, Optional, Any, Callable
from pathlib import Path
from dataclasses import dataclass
from enum import Enum
from utils.logger import get_logger

logger = get_logger("batch_processor")


class BatchStatus(Enum):
    """Status of batch operation"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class BatchResult:
    """Result of processing a single file"""
    file_path: str
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: float = 0.0


@dataclass
class BatchJob:
    """Batch processing job"""
    job_id: str
    operation_name: str
    file_paths: List[str]
    status: BatchStatus = BatchStatus.PENDING
    results: List[BatchResult] = None
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0

    def __post_init__(self):
        if self.results is None:
            self.results = []
        self.total_files = len(self.file_paths)

    def progress_percentage(self) -> float:
        """Get progress as percentage"""
        if self.total_files == 0:
            return 0.0
        return (self.completed_files / self.total_files) * 100

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "operation": self.operation_name,
            "status": self.status.value,
            "progress": self.progress_percentage(),
            "files": self.total_files,
            "completed": self.completed_files,
            "failed": self.failed_files,
            "results": [
                {
                    "file": r.file_path,
                    "success": r.success,
                    "error": r.error
                }
                for r in self.results
            ]
        }


class BatchProcessor:
    """Processes multiple files in parallel"""

    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
        self.jobs: Dict[str, BatchJob] = {}
        self.progress_callbacks: Dict[str, Callable] = {}

    async def process_batch(
        self,
        operation_name: str,
        file_paths: List[str],
        operation_func: Callable,
        job_id: Optional[str] = None,
        progress_callback: Optional[Callable] = None
    ) -> BatchJob:
        """Process multiple files with given operation"""
        import uuid

        job_id = job_id or str(uuid.uuid4())[:8]
        job = BatchJob(
            job_id=job_id,
            operation_name=operation_name,
            file_paths=file_paths
        )

        self.jobs[job_id] = job
        if progress_callback:
            self.progress_callbacks[job_id] = progress_callback

        job.status = BatchStatus.RUNNING

        try:
            # Process files with semaphore to limit concurrency
            semaphore = asyncio.Semaphore(self.max_workers)

            async def process_with_semaphore(file_path: str):
                async with semaphore:
                    return await self._process_single_file(job, file_path, operation_func)

            tasks = [process_with_semaphore(fp) for fp in file_paths]
            await asyncio.gather(*tasks, return_exceptions=True)

            job.status = BatchStatus.COMPLETED

        except asyncio.CancelledError:
            job.status = BatchStatus.CANCELLED
            logger.info(f"Batch job {job_id} cancelled")
        except Exception as e:
            job.status = BatchStatus.FAILED
            logger.error(f"Batch job {job_id} failed: {e}")

        logger.info(
            f"Batch job {job_id} completed: "
            f"{job.completed_files} succeeded, {job.failed_files} failed"
        )

        return job

    async def _process_single_file(
        self,
        job: BatchJob,
        file_path: str,
        operation_func: Callable
    ) -> BatchResult:
        """Process a single file"""
        import time

        start_time = time.time()

        try:
            # Validate file exists
            path = Path(file_path)
            if not path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Execute operation
            result = await operation_func(file_path)

            # Check result
            success = result.get("success", False) if isinstance(result, dict) else True

            batch_result = BatchResult(
                file_path=file_path,
                success=success,
                result=result,
                duration_ms=(time.time() - start_time) * 1000
            )

            if success:
                job.completed_files += 1
            else:
                job.failed_files += 1
                batch_result.error = result.get("error", "Unknown error") if isinstance(result, dict) else "Operation failed"

        except Exception as e:
            batch_result = BatchResult(
                file_path=file_path,
                success=False,
                error=str(e),
                duration_ms=(time.time() - start_time) * 1000
            )
            job.failed_files += 1

        job.results.append(batch_result)

        # Call progress callback
        if job.job_id in self.progress_callbacks:
            try:
                callback = self.progress_callbacks[job.job_id]
                if asyncio.iscoroutinefunction(callback):
                    await callback(job)
                else:
                    callback(job)
            except Exception as e:
                logger.debug(f"Progress callback failed: {e}")

        return batch_result

    def get_job(self, job_id: str) -> Optional[BatchJob]:
        """Get batch job by ID"""
        return self.jobs.get(job_id)

    def cancel_job(self, job_id: str) -> bool:
        """Cancel a batch job"""
        job = self.jobs.get(job_id)
        if job and job.status == BatchStatus.RUNNING:
            job.status = BatchStatus.CANCELLED
            return True
        return False

    def get_job_status(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get status of a batch job"""
        job = self.jobs.get(job_id)
        return job.to_dict() if job else None

    def cleanup_old_jobs(self, keep_count: int = 50):
        """Remove old completed jobs to save memory"""
        if len(self.jobs) <= keep_count:
            return

        # Keep only recent jobs
        job_ids = list(self.jobs.keys())
        for job_id in job_ids[:-keep_count]:
            del self.jobs[job_id]
            self.progress_callbacks.pop(job_id, None)

        logger.info(f"Cleaned up old batch jobs, kept {keep_count}")


# Global instance
_batch_processor: Optional[BatchProcessor] = None


def get_batch_processor() -> BatchProcessor:
    """Get or create batch processor"""
    global _batch_processor
    if _batch_processor is None:
        _batch_processor = BatchProcessor(max_workers=4)
    return _batch_processor
