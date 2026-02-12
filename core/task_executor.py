import asyncio
from typing import Any, Callable
from config.settings import TASK_TIMEOUT, CIRCUIT_BREAKER_THRESHOLD
from utils.logger import get_logger
from datetime import datetime, timedelta

logger = get_logger("task_executor")

class CircuitBreaker:
    def __init__(self, threshold: int = CIRCUIT_BREAKER_THRESHOLD):
        self.threshold = threshold
        self.failure_count = 0
        self.is_open = False
        self.opened_at = None
        self.recovery_timeout = 30  # Recovery timeout in seconds

    def record_success(self):
        self.failure_count = 0
        if self.is_open:
            logger.info("Circuit breaker recovered")
        self.is_open = False
        self.opened_at = None

    def record_failure(self):
        self.failure_count += 1
        if self.failure_count >= self.threshold:
            self.is_open = True
            self.opened_at = datetime.now()
            logger.warning(f"Circuit breaker opened after {self.failure_count} failures. Recovery in {self.recovery_timeout}s")

    def can_execute(self) -> bool:
        if not self.is_open:
            return True
        
        # Otomatik recovery kontrolü
        if self.opened_at and (datetime.now() - self.opened_at).total_seconds() > self.recovery_timeout:
            logger.info("Circuit breaker attempting recovery...")
            self.is_open = False
            self.failure_count = 0
            self.opened_at = None
            return True
        
        return False

    def reset(self):
        self.failure_count = 0
        self.is_open = False
        self.opened_at = None

class TaskExecutor:
    def __init__(self):
        self.circuit_breaker = CircuitBreaker()  # Global breaker for compatibility
        self.tool_circuit_breakers = {}  # Per-tool circuit breakers
        self.is_busy = False
        self.current_task = None
        self.task_history = []  # Son görevleri takip et

    def _get_tool_breaker(self, tool_name: str) -> CircuitBreaker:
        """Get or create circuit breaker for a tool"""
        if tool_name not in self.tool_circuit_breakers:
            self.tool_circuit_breakers[tool_name] = CircuitBreaker()
        return self.tool_circuit_breakers[tool_name]

    async def execute(self, tool_func: Callable, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = tool_func.__name__

        # Check per-tool circuit breaker
        tool_breaker = self._get_tool_breaker(tool_name)
        if not tool_breaker.can_execute():
            return {
                "success": False,
                "error": f"{tool_name} aracı çok fazla hata verdi. Lütfen birkaç saniye bekleyin."
            }

        # Global circuit breaker check (for total system protection)
        if not self.circuit_breaker.can_execute():
            return {
                "success": False,
                "error": "Sistem çok fazla hata verdi. Koruma modunda. Lütfen birkaç saniye bekleyin."
            }

        # Parallelism Enabled (v15.0) - Removed is_busy blocking
        # self.is_busy = True # No longer using simple flag
        
        task_start = datetime.now()
        logger.info(f"Executing {tool_name} with params: {params}")

        try:
            result = await asyncio.wait_for(
                tool_func(**params),
                timeout=TASK_TIMEOUT
            )

            task_end = datetime.now()
            elapsed = (task_end - task_start).total_seconds()
            logger.info(f"Task {tool_name} completed in {elapsed:.2f}s")

            # Record in task history
            self._record_task(tool_name, result.get("success", False), elapsed)

            success = result.get("success", False)
            if success:
                tool_breaker.record_success()
                self.circuit_breaker.record_success()
            else:
                tool_breaker.record_failure()
                self.circuit_breaker.record_failure()

            return result

        except asyncio.TimeoutError:
            tool_breaker.record_failure()
            self.circuit_breaker.record_failure()
            elapsed = (datetime.now() - task_start).total_seconds()
            logger.error(f"Task {tool_name} timed out after {TASK_TIMEOUT}s")
            self._record_task(tool_name, False, elapsed, "timeout")
            return {
                "success": False,
                "error": f"Görev zaman aşımına uğradı ({TASK_TIMEOUT}s)"
            }

        except Exception as e:
            tool_breaker.record_failure()
            self.circuit_breaker.record_failure()
            elapsed = (datetime.now() - task_start).total_seconds()
            logger.error(f"Task {tool_name} execution error: {str(e)}")
            self._record_task(tool_name, False, elapsed, str(e))
            return {
                "success": False,
                "error": f"Görev hatası: {str(e)[:100]}"
            }

        finally:
            # self.is_busy = False # No longer needed
            pass

    def _record_task(self, tool_name: str, success: bool, elapsed: float, error: str = None):
        """Görev geçmişine kaydet"""
        self.task_history.append({
            "tool": tool_name,
            "success": success,
            "elapsed": elapsed,
            "error": error,
            "timestamp": datetime.now()
        })
        # Son 50 görevi tut
        if len(self.task_history) > 50:
            self.task_history = self.task_history[-50:]

    def get_stats(self) -> dict[str, Any]:
        """İstatistikleri döner"""
        if not self.task_history:
            return {"total": 0, "success": 0, "failed": 0, "success_rate": 0}
        
        total = len(self.task_history)
        success = sum(1 for t in self.task_history if t["success"])
        failed = total - success
        success_rate = (success / total * 100) if total > 0 else 0
        avg_time = sum(t["elapsed"] for t in self.task_history) / total if total > 0 else 0
        
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "success_rate": f"{success_rate:.1f}%",
            "avg_time": f"{avg_time:.2f}s",
            "circuit_breaker_open": self.circuit_breaker.is_open,
            "failure_count": self.circuit_breaker.failure_count
        }

    def reset_circuit_breaker(self):
        """Reset global and all per-tool circuit breakers"""
        self.circuit_breaker.reset()
        for breaker in self.tool_circuit_breakers.values():
            breaker.reset()
        logger.info("All circuit breakers reset")
