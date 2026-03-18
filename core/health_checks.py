"""
Health Check System for elyan Bot Production
=============================================
Monitors system health and provides diagnostic information.

Features:
- Database connectivity checks
- LLM provider availability
- Disk space monitoring
- Memory usage monitoring
- Learning system health
- Real-time status endpoint
"""

import logging
import sqlite3
import psutil
import time
from typing import Dict, List, Any, Optional, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    check_name: str
    status: str  # healthy, degraded, unhealthy
    duration_ms: float
    message: str
    details: Dict[str, Any] = None
    timestamp: float = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = time.time()
        if self.details is None:
            self.details = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "check_name": self.check_name,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "message": self.message,
            "details": self.details,
            "timestamp": self.timestamp
        }


class HealthCheck:
    """Base class for health checks."""

    def __init__(self, name: str, timeout: float = 5.0):
        self.name = name
        self.timeout = timeout
        self.last_result: Optional[HealthCheckResult] = None

    async def execute(self) -> HealthCheckResult:
        """Execute the health check."""
        start = time.time()
        try:
            result = await asyncio.wait_for(self._check(), timeout=self.timeout)
            duration_ms = (time.time() - start) * 1000
            result.duration_ms = duration_ms
            self.last_result = result
            return result
        except asyncio.TimeoutError:
            duration_ms = (time.time() - start) * 1000
            result = HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.UNHEALTHY.value,
                duration_ms=duration_ms,
                message=f"Health check timed out after {self.timeout}s"
            )
            self.last_result = result
            return result

    async def _check(self) -> HealthCheckResult:
        """Subclasses implement the actual check."""
        raise NotImplementedError


class DatabaseHealthCheck(HealthCheck):
    """Check database connectivity."""

    def __init__(self, db_path: str, timeout: float = 5.0):
        super().__init__("database", timeout)
        self.db_path = db_path

    async def _check(self) -> HealthCheckResult:
        """Check database connectivity."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=2.0)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            conn.close()

            return HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.HEALTHY.value,
                duration_ms=0,
                message="Database connection successful",
                details={"database": self.db_path}
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.UNHEALTHY.value,
                duration_ms=0,
                message=f"Database connection failed: {e}",
                details={"error": str(e), "database": self.db_path}
            )


class DiskSpaceHealthCheck(HealthCheck):
    """Check available disk space."""

    def __init__(self, path: str = "/", min_mb: float = 1000.0, timeout: float = 5.0):
        super().__init__("disk_space", timeout)
        self.path = path
        self.min_mb = min_mb

    async def _check(self) -> HealthCheckResult:
        """Check disk space."""
        try:
            usage = psutil.disk_usage(self.path)
            available_mb = usage.free / (1024 * 1024)

            if available_mb < self.min_mb:
                status = HealthStatus.DEGRADED.value
                message = f"Low disk space: {available_mb:.1f}MB available"
            else:
                status = HealthStatus.HEALTHY.value
                message = "Disk space available"

            return HealthCheckResult(
                check_name=self.name,
                status=status,
                duration_ms=0,
                message=message,
                details={
                    "available_mb": available_mb,
                    "total_mb": usage.total / (1024 * 1024),
                    "percent_used": usage.percent
                }
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.UNKNOWN.value,
                duration_ms=0,
                message=f"Failed to check disk space: {e}",
                details={"error": str(e)}
            )


class MemoryHealthCheck(HealthCheck):
    """Check memory usage."""

    def __init__(self, max_percent: float = 85.0, timeout: float = 5.0):
        super().__init__("memory", timeout)
        self.max_percent = max_percent

    async def _check(self) -> HealthCheckResult:
        """Check memory usage."""
        try:
            memory = psutil.virtual_memory()

            if memory.percent > self.max_percent:
                status = HealthStatus.DEGRADED.value
                message = f"High memory usage: {memory.percent:.1f}%"
            else:
                status = HealthStatus.HEALTHY.value
                message = "Memory usage normal"

            return HealthCheckResult(
                check_name=self.name,
                status=status,
                duration_ms=0,
                message=message,
                details={
                    "used_mb": memory.used / (1024 * 1024),
                    "available_mb": memory.available / (1024 * 1024),
                    "percent": memory.percent
                }
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.UNKNOWN.value,
                duration_ms=0,
                message=f"Failed to check memory: {e}",
                details={"error": str(e)}
            )


class LLMProviderHealthCheck(HealthCheck):
    """Check LLM provider availability."""

    def __init__(self, provider_name: str, check_func: Callable[[], bool], timeout: float = 10.0):
        super().__init__(f"llm_{provider_name}", timeout)
        self.provider_name = provider_name
        self.check_func = check_func

    async def _check(self) -> HealthCheckResult:
        """Check LLM provider."""
        try:
            # Run check function in thread pool
            loop = asyncio.get_event_loop()
            available = await loop.run_in_executor(None, self.check_func)

            if available:
                status = HealthStatus.HEALTHY.value
                message = f"LLM provider {self.provider_name} is available"
            else:
                status = HealthStatus.UNHEALTHY.value
                message = f"LLM provider {self.provider_name} is unavailable"

            return HealthCheckResult(
                check_name=self.name,
                status=status,
                duration_ms=0,
                message=message,
                details={"provider": self.provider_name}
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.UNHEALTHY.value,
                duration_ms=0,
                message=f"Failed to check LLM provider: {e}",
                details={"error": str(e), "provider": self.provider_name}
            )


class LearningSystemHealthCheck(HealthCheck):
    """Check learning system health."""

    def __init__(self, db_path: str, timeout: float = 5.0):
        super().__init__("learning_system", timeout)
        self.db_path = db_path

    async def _check(self) -> HealthCheckResult:
        """Check learning system."""
        try:
            conn = sqlite3.connect(self.db_path, timeout=2.0)
            cursor = conn.cursor()

            # Check if learning tables exist
            cursor.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name LIKE '%learning%'
            """)
            tables = cursor.fetchall()

            if not tables:
                status = HealthStatus.DEGRADED.value
                message = "Learning system tables not found"
            else:
                # Check recent learning data
                cursor.execute("""
                    SELECT COUNT(*) FROM sqlite_master
                    WHERE type='table' AND name='learning_feedback'
                """)
                has_feedback = cursor.fetchone()[0] > 0

                status = HealthStatus.HEALTHY.value if has_feedback else HealthStatus.DEGRADED.value
                message = "Learning system is functional"

            conn.close()

            return HealthCheckResult(
                check_name=self.name,
                status=status,
                duration_ms=0,
                message=message,
                details={"has_tables": len(tables) > 0}
            )
        except Exception as e:
            return HealthCheckResult(
                check_name=self.name,
                status=HealthStatus.UNHEALTHY.value,
                duration_ms=0,
                message=f"Failed to check learning system: {e}",
                details={"error": str(e)}
            )


class HealthCheckSuite:
    """Manages collection of health checks."""

    def __init__(self):
        self.checks: Dict[str, HealthCheck] = {}
        self.results: List[HealthCheckResult] = []
        self.last_run: Optional[float] = None

    def add_check(self, check: HealthCheck) -> None:
        """Add a health check."""
        self.checks[check.name] = check

    def remove_check(self, name: str) -> None:
        """Remove a health check."""
        if name in self.checks:
            del self.checks[name]

    async def run_all(self) -> Dict[str, Any]:
        """Run all health checks."""
        logger.info(f"Running {len(self.checks)} health checks...")

        self.results = []
        tasks = [check.execute() for check in self.checks.values()]

        results = await asyncio.gather(*tasks, return_exceptions=False)

        self.results = results
        self.last_run = time.time()

        return self._summarize_results()

    def _summarize_results(self) -> Dict[str, Any]:
        """Summarize health check results."""
        status_counts = {
            HealthStatus.HEALTHY.value: 0,
            HealthStatus.DEGRADED.value: 0,
            HealthStatus.UNHEALTHY.value: 0,
            HealthStatus.UNKNOWN.value: 0
        }

        for result in self.results:
            status_counts[result.status] += 1

        # Overall status
        if status_counts[HealthStatus.UNHEALTHY.value] > 0:
            overall_status = HealthStatus.UNHEALTHY.value
        elif status_counts[HealthStatus.DEGRADED.value] > 0:
            overall_status = HealthStatus.DEGRADED.value
        else:
            overall_status = HealthStatus.HEALTHY.value

        return {
            "overall_status": overall_status,
            "timestamp": datetime.now().isoformat(),
            "checks_run": len(self.results),
            "status_breakdown": status_counts,
            "details": [r.to_dict() for r in self.results]
        }

    def get_status(self) -> Dict[str, Any]:
        """Get current health status."""
        if not self.results:
            return {
                "overall_status": HealthStatus.UNKNOWN.value,
                "message": "No health checks have been run",
                "checks_run": 0
            }

        return self._summarize_results()

    def is_healthy(self) -> bool:
        """Check if system is healthy."""
        if not self.results:
            return False

        unhealthy = any(r.status == HealthStatus.UNHEALTHY.value for r in self.results)
        return not unhealthy

    def is_degraded(self) -> bool:
        """Check if system is degraded."""
        if not self.results:
            return False

        return any(r.status == HealthStatus.DEGRADED.value for r in self.results)


def create_default_health_checks(db_path: str) -> HealthCheckSuite:
    """Create default health check suite."""
    suite = HealthCheckSuite()

    # Database check
    suite.add_check(DatabaseHealthCheck(db_path))

    # Disk space check
    suite.add_check(DiskSpaceHealthCheck(min_mb=1000.0))

    # Memory check
    suite.add_check(MemoryHealthCheck(max_percent=85.0))

    # Learning system check
    suite.add_check(LearningSystemHealthCheck(db_path))

    return suite
