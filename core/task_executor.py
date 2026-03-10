import asyncio
import inspect
from typing import Any, Callable
from config.settings import TASK_TIMEOUT, CIRCUIT_BREAKER_THRESHOLD
from utils.logger import get_logger
from datetime import datetime, timedelta
from core.compat.legacy_tool_wrappers import normalize_legacy_tool_payload

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

    @staticmethod
    def _normalize_executor_result(
        tool_name: str,
        raw_result: Any,
        *,
        elapsed_s: float = 0.0,
        error_code: str = "",
    ) -> dict[str, Any]:
        normalized = normalize_legacy_tool_payload(raw_result, tool=tool_name, source="task_executor")
        metrics = dict(normalized.get("metrics") or {})
        metrics["executor_duration_ms"] = max(0, int(round(float(elapsed_s or 0.0) * 1000.0)))
        metrics.setdefault("tool_name", str(tool_name or ""))
        normalized["metrics"] = metrics

        data = dict(normalized.get("data") or {})
        if error_code and not str(data.get("error_code") or "").strip():
            data["error_code"] = str(error_code)
        normalized["data"] = data

        if error_code and not str(normalized.get("error_code") or "").strip():
            normalized["error_code"] = str(error_code)
        if not normalized.get("message") and normalized.get("error"):
            normalized["message"] = str(normalized.get("error") or "")
        return normalized

    async def execute(self, tool_func: Callable, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = tool_func.__name__

        # Check per-tool circuit breaker
        tool_breaker = self._get_tool_breaker(tool_name)
        if not tool_breaker.can_execute():
            return self._normalize_executor_result(
                tool_name,
                {
                    "success": False,
                    "status": "blocked",
                    "error": f"{tool_name} aracı çok fazla hata verdi. Lütfen birkaç saniye bekleyin.",
                    "errors": ["CIRCUIT_BREAKER_OPEN"],
                    "data": {"error_code": "CIRCUIT_BREAKER_OPEN", "blocker": "tool_circuit_breaker"},
                },
                error_code="CIRCUIT_BREAKER_OPEN",
            )

        # Global circuit breaker check (for total system protection)
        if not self.circuit_breaker.can_execute():
            return self._normalize_executor_result(
                tool_name,
                {
                    "success": False,
                    "status": "blocked",
                    "error": "Sistem çok fazla hata verdi. Koruma modunda. Lütfen birkaç saniye bekleyin.",
                    "errors": ["CIRCUIT_BREAKER_OPEN"],
                    "data": {"error_code": "CIRCUIT_BREAKER_OPEN", "blocker": "global_circuit_breaker"},
                },
                error_code="CIRCUIT_BREAKER_OPEN",
            )

        # Parallelism Enabled (v15.0) - Removed is_busy blocking
        # self.is_busy = True # No longer using simple flag
        
        task_start = datetime.now()
        logger.info(f"Executing {tool_name} with params: {params}")

        try:
            pending = tool_func(**params)
            if inspect.isawaitable(pending):
                result = await asyncio.wait_for(
                    pending,
                    timeout=TASK_TIMEOUT
                )
            else:
                result = pending

            task_end = datetime.now()
            elapsed = (task_end - task_start).total_seconds()
            logger.info(f"Task {tool_name} completed in {elapsed:.2f}s")
            result = self._normalize_executor_result(tool_name, result, elapsed_s=elapsed)

            # Record in task history
            success = bool(result.get("success", False))
            failure_detail = ""
            if not success:
                failure_detail = str(result.get("error") or result.get("message") or "")
            self._record_task(tool_name, success, elapsed, failure_detail or None)

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
            return self._normalize_executor_result(
                tool_name,
                {
                    "success": False,
                    "status": "failed",
                    "error": f"Görev zaman aşımına uğradı ({TASK_TIMEOUT}s)",
                    "errors": ["TIMEOUT"],
                    "data": {"error_code": "TIMEOUT"},
                },
                elapsed_s=elapsed,
                error_code="TIMEOUT",
            )

        except Exception as e:
            tool_breaker.record_failure()
            self.circuit_breaker.record_failure()
            elapsed = (datetime.now() - task_start).total_seconds()
            logger.error(f"Task {tool_name} execution error: {str(e)}")
            self._record_task(tool_name, False, elapsed, str(e))
            return self._normalize_executor_result(
                tool_name,
                {
                    "success": False,
                    "status": "failed",
                    "error": f"Görev hatası: {str(e)[:100]}",
                    "errors": ["EXECUTION_EXCEPTION"],
                    "data": {"error_code": "EXECUTION_EXCEPTION", "exception_type": type(e).__name__},
                },
                elapsed_s=elapsed,
                error_code="EXECUTION_EXCEPTION",
            )

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
