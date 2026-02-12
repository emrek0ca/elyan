"""
Self-Healing System
Otomatik hata yakalama, intelligent recovery, system optimization
"""

import asyncio
import time
import psutil
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass
from enum import Enum
from collections import Counter, deque

from utils.logger import get_logger

logger = get_logger("self_healing")


class HealthIssue(Enum):
    """System health issues"""
    HIGH_MEMORY = "high_memory"
    HIGH_CPU = "high_cpu"
    DISK_FULL = "disk_full"
    REPEATED_ERRORS = "repeated_errors"
    SLOW_RESPONSE = "slow_response"
    HUNG_PROCESS = "hung_process"
    FAILED_TOOL = "failed_tool"
    CONNECTION_LOST = "connection_lost"


@dataclass
class HealthCheck:
    """Health check result"""
    issue_type: HealthIssue
    severity: str  # low, medium, high, critical
    description: str
    auto_fixable: bool
    fix_action: Optional[str] = None
    detected_at: float = 0.0

    def __post_init__(self):
        if self.detected_at == 0.0:
            self.detected_at = time.time()


class SelfHealing:
    """
    Self-Healing System
    - Monitors system health
    - Detects problems automatically
    - Attempts intelligent recovery
    - Optimizes performance
    """

    def __init__(self):
        self.health_checks: List[HealthCheck] = []
        self.error_history: deque = deque(maxlen=100)  # Last 100 errors
        self.fix_history: List[Dict[str, Any]] = []
        self.monitoring_active = False

        # Thresholds
        self.memory_threshold = 85  # Percent
        self.cpu_threshold = 90  # Percent
        self.disk_threshold = 95  # Percent
        self.slow_response_threshold = 10000  # ms

        # Error patterns for auto-fix
        self.known_fixes = {
            "ECONNREFUSED": self._fix_connection_refused,
            "ETIMEDOUT": self._fix_timeout,
            "MemoryError": self._fix_memory_error,
            "Tool not found": self._fix_missing_tool,
            "Permission denied": self._fix_permission_denied,
        }

        logger.info("Self-Healing system initialized")

    async def start_monitoring(self):
        """Start continuous health monitoring"""
        self.monitoring_active = True
        logger.info("Self-healing monitoring started")

        while self.monitoring_active:
            try:
                await self._perform_health_check()
                await self._auto_optimize()
                await asyncio.sleep(30)  # Check every 30 seconds
            except Exception as e:
                logger.error(f"Health check error: {e}")
                await asyncio.sleep(30)

    def stop_monitoring(self):
        """Stop health monitoring"""
        self.monitoring_active = False
        logger.info("Self-healing monitoring stopped")

    async def _perform_health_check(self):
        """Perform comprehensive health check"""
        issues = []

        # Check memory usage
        memory = psutil.virtual_memory()
        if memory.percent > self.memory_threshold:
            issues.append(HealthCheck(
                issue_type=HealthIssue.HIGH_MEMORY,
                severity="high",
                description=f"Memory usage: {memory.percent:.1f}%",
                auto_fixable=True,
                fix_action="clear_cache"
            ))

        # Check CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > self.cpu_threshold:
            issues.append(HealthCheck(
                issue_type=HealthIssue.HIGH_CPU,
                severity="high",
                description=f"CPU usage: {cpu_percent:.1f}%",
                auto_fixable=False
            ))

        # Check disk usage
        disk = psutil.disk_usage('/')
        if disk.percent > self.disk_threshold:
            issues.append(HealthCheck(
                issue_type=HealthIssue.DISK_FULL,
                severity="critical",
                description=f"Disk usage: {disk.percent:.1f}%",
                auto_fixable=True,
                fix_action="cleanup_temp"
            ))

        # Check for repeated errors
        if len(self.error_history) > 10:
            error_types = Counter([e["type"] for e in self.error_history])
            for error_type, count in error_types.items():
                if count > 5:  # Same error 5+ times
                    issues.append(HealthCheck(
                        issue_type=HealthIssue.REPEATED_ERRORS,
                        severity="medium",
                        description=f"Repeated error: {error_type} ({count} times)",
                        auto_fixable=True,
                        fix_action=f"fix_{error_type}"
                    ))

        # Auto-fix critical issues
        for issue in issues:
            if issue.auto_fixable and issue.severity in ["high", "critical"]:
                logger.warning(f"Auto-fixing issue: {issue.description}")
                await self._auto_fix(issue)

        self.health_checks.extend(issues)

        # Keep only last 50 health checks
        if len(self.health_checks) > 50:
            self.health_checks = self.health_checks[-50:]

    async def _auto_fix(self, issue: HealthCheck):
        """Attempt to automatically fix an issue"""
        fix_result = {"issue": issue.issue_type.value, "success": False, "action": None}

        try:
            if issue.fix_action == "clear_cache":
                # Clear internal caches
                from .smart_cache import get_smart_cache
                cache = get_smart_cache()
                cache.clear()
                fix_result["success"] = True
                fix_result["action"] = "Cleared cache"
                logger.info("Auto-fix: Cache cleared")

            elif issue.fix_action == "cleanup_temp":
                # Cleanup temp files
                import tempfile
                import shutil
                temp_dir = tempfile.gettempdir()
                cleaned = 0
                for item in os.listdir(temp_dir):
                    try:
                        path = os.path.join(temp_dir, item)
                        if os.path.isfile(path):
                            os.unlink(path)
                            cleaned += 1
                    except:
                        pass
                fix_result["success"] = True
                fix_result["action"] = f"Cleaned {cleaned} temp files"
                logger.info(f"Auto-fix: Cleaned {cleaned} temp files")

            elif issue.fix_action.startswith("fix_"):
                # Try known fixes
                error_type = issue.fix_action.replace("fix_", "")
                if error_type in self.known_fixes:
                    await self.known_fixes[error_type]()
                    fix_result["success"] = True
                    fix_result["action"] = f"Applied fix for {error_type}"

        except Exception as e:
            logger.error(f"Auto-fix failed: {e}")
            fix_result["error"] = str(e)

        fix_result["timestamp"] = time.time()
        self.fix_history.append(fix_result)

        # Keep only last 50 fixes
        if len(self.fix_history) > 50:
            self.fix_history = self.fix_history[-50:]

    async def _fix_connection_refused(self):
        """Fix connection refused errors"""
        logger.info("Attempting to fix connection issues...")
        # Could restart services, check network, etc.
        await asyncio.sleep(1)

    async def _fix_timeout(self):
        """Fix timeout errors"""
        logger.info("Attempting to fix timeout issues...")
        # Could increase timeouts, retry with exponential backoff
        await asyncio.sleep(1)

    async def _fix_memory_error(self):
        """Fix memory errors"""
        logger.info("Attempting to fix memory issues...")
        # Clear caches, garbage collect
        import gc
        gc.collect()

    async def _fix_missing_tool(self):
        """Fix missing tool errors"""
        logger.info("Attempting to fix missing tool issues...")
        # Could reload tools, check tool health
        await asyncio.sleep(1)

    async def _fix_permission_denied(self):
        """Fix permission denied errors"""
        logger.info("Attempting to fix permission issues...")
        # Could adjust permissions, check user access
        await asyncio.sleep(1)

    async def _auto_optimize(self):
        """Automatically optimize system performance"""
        try:
            # Garbage collection if memory is high
            memory = psutil.virtual_memory()
            if memory.percent > 70:
                import gc
                gc.collect()
                logger.debug("Auto-optimization: Garbage collection performed")

            # Clear old error history
            if len(self.error_history) > 50:
                self.error_history = deque(list(self.error_history)[-50:], maxlen=100)

        except Exception as e:
            logger.error(f"Auto-optimization error: {e}")

    def record_error(
        self,
        error_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ):
        """Record an error for pattern detection"""
        self.error_history.append({
            "type": error_type,
            "message": error_message,
            "context": context or {},
            "timestamp": time.time()
        })

        # Try to auto-fix if known error
        for known_error, fix_func in self.known_fixes.items():
            if known_error in error_message or known_error in error_type:
                logger.info(f"Known error detected: {known_error}, attempting auto-fix...")
                asyncio.create_task(fix_func())
                break

    def get_health_report(self) -> Dict[str, Any]:
        """Get comprehensive health report"""
        memory = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=0.1)
        disk = psutil.disk_usage('/')

        # Recent issues (last 10)
        recent_issues = self.health_checks[-10:] if self.health_checks else []

        # Success rate of auto-fixes
        total_fixes = len(self.fix_history)
        successful_fixes = sum(1 for f in self.fix_history if f.get("success"))
        fix_success_rate = (successful_fixes / total_fixes * 100) if total_fixes > 0 else 0

        return {
            "system_health": {
                "memory_percent": memory.percent,
                "cpu_percent": cpu,
                "disk_percent": disk.percent,
                "status": "healthy" if memory.percent < 80 and cpu < 80 else "degraded"
            },
            "recent_issues": [
                {
                    "type": issue.issue_type.value,
                    "severity": issue.severity,
                    "description": issue.description,
                    "auto_fixable": issue.auto_fixable
                }
                for issue in recent_issues
            ],
            "auto_fix_stats": {
                "total_fixes": total_fixes,
                "successful_fixes": successful_fixes,
                "success_rate": f"{fix_success_rate:.1f}%"
            },
            "error_patterns": dict(Counter([e["type"] for e in self.error_history]).most_common(5)),
            "monitoring_active": self.monitoring_active
        }


# Global instance
_self_healing: Optional[SelfHealing] = None


def get_self_healing() -> SelfHealing:
    """Get or create global self-healing instance"""
    global _self_healing
    if _self_healing is None:
        _self_healing = SelfHealing()
    return _self_healing
