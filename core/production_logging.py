"""
Production Logging System for Wiqo Bot
=====================================
Structured logging, aggregation readiness, and performance profiling.

Features:
- JSON structured logging
- Log rotation
- Log aggregation ready (ELK, Datadog)
- Performance profiling
- Error categorization
- Context tracking
"""

import logging
import json
import time
import os
import sys
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler
import traceback
import hashlib


class ProductionLogFormatter(logging.Formatter):
    """Formats logs as structured JSON for production aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
            "thread": record.thread,
            "thread_name": record.threadName,
            "process": record.process
        }

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info)
            }

        # Add extra fields if present
        if hasattr(record, "extra_fields"):
            log_data.update(record.extra_fields)

        return json.dumps(log_data)


class ContextLogger:
    """Logger with context awareness."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context: Dict[str, Any] = {}

    def set_context(self, **kwargs) -> None:
        """Set context for subsequent log messages."""
        self.context.update(kwargs)

    def clear_context(self) -> None:
        """Clear context."""
        self.context.clear()

    def _log_with_context(self, level: int, message: str, *args, **kwargs) -> None:
        """Log with context."""
        extra = kwargs.pop("extra", {})
        if not isinstance(extra, dict):
            extra = {}

        extra["extra_fields"] = self.context.copy()
        extra["extra_fields"].update(kwargs)

        self.logger.log(level, message, *args, extra=extra)

    def debug(self, message: str, *args, **kwargs) -> None:
        """Log debug message."""
        self._log_with_context(logging.DEBUG, message, *args, **kwargs)

    def info(self, message: str, *args, **kwargs) -> None:
        """Log info message."""
        self._log_with_context(logging.INFO, message, *args, **kwargs)

    def warning(self, message: str, *args, **kwargs) -> None:
        """Log warning message."""
        self._log_with_context(logging.WARNING, message, *args, **kwargs)

    def error(self, message: str, *args, **kwargs) -> None:
        """Log error message."""
        self._log_with_context(logging.ERROR, message, *args, **kwargs)

    def critical(self, message: str, *args, **kwargs) -> None:
        """Log critical message."""
        self._log_with_context(logging.CRITICAL, message, *args, **kwargs)


class PerformanceLogger:
    """Logs performance metrics."""

    def __init__(self, logger: logging.Logger):
        self.logger = logger
        self.timers: Dict[str, float] = {}

    def start_timer(self, name: str) -> None:
        """Start a timer."""
        self.timers[name] = time.time()

    def end_timer(self, name: str, threshold_ms: Optional[float] = None) -> float:
        """End a timer and log duration."""
        if name not in self.timers:
            return 0.0

        duration_ms = (time.time() - self.timers[name]) * 1000
        del self.timers[name]

        # Only log if above threshold
        if threshold_ms is None or duration_ms > threshold_ms:
            extra = {"extra_fields": {"timer_name": name, "duration_ms": duration_ms}}
            self.logger.info(f"Timer {name} completed in {duration_ms:.2f}ms", extra=extra)

        return duration_ms

    def log_latency(self, operation: str, latency_ms: float, percentile: Optional[str] = None) -> None:
        """Log latency for an operation."""
        extra = {
            "extra_fields": {
                "operation": operation,
                "latency_ms": latency_ms,
                "percentile": percentile
            }
        }
        self.logger.info(f"Operation {operation}: {latency_ms:.2f}ms", extra=extra)

    def log_throughput(self, operation: str, count: int, duration_ms: float) -> None:
        """Log throughput."""
        throughput = (count / duration_ms) * 1000 if duration_ms > 0 else 0
        extra = {
            "extra_fields": {
                "operation": operation,
                "count": count,
                "duration_ms": duration_ms,
                "throughput": throughput
            }
        }
        self.logger.info(f"Throughput {operation}: {throughput:.2f} ops/sec", extra=extra)


class ErrorCategorizer:
    """Categorizes errors for analysis."""

    ERROR_CATEGORIES = {
        "database": ["sqlite", "database", "sql", "connection"],
        "llm": ["llm", "model", "api", "inference"],
        "network": ["network", "timeout", "connection", "socket"],
        "validation": ["validation", "schema", "invalid"],
        "permission": ["permission", "access", "unauthorized"],
        "resource": ["memory", "disk", "cpu", "limit"],
        "unknown": []
    }

    @staticmethod
    def categorize(error_type: str, error_message: str) -> str:
        """Categorize an error."""
        error_text = f"{error_type} {error_message}".lower()

        for category, keywords in ErrorCategorizer.ERROR_CATEGORIES.items():
            if category == "unknown":
                continue
            if any(keyword in error_text for keyword in keywords):
                return category

        return "unknown"

    @staticmethod
    def get_error_hash(error_type: str, error_message: str) -> str:
        """Get hash of error for deduplication."""
        error_text = f"{error_type}:{error_message}"
        return hashlib.sha256(error_text.encode()).hexdigest()[:16]


class ProductionLogger:
    """Main production logger with all features."""

    def __init__(self, name: str, log_dir: str = "~/.wiqo/logs"):
        self.name = name
        self.log_dir = Path(log_dir).expanduser()
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        self._setup_handlers()

        self.context_logger = ContextLogger(name)
        self.perf_logger = PerformanceLogger(self.logger)
        self.error_categorizer = ErrorCategorizer()

    def _setup_handlers(self) -> None:
        """Setup logging handlers."""
        # Main log file with rotation
        main_handler = RotatingFileHandler(
            self.log_dir / f"{self.name}.log",
            maxBytes=100 * 1024 * 1024,  # 100MB
            backupCount=10
        )
        main_handler.setLevel(logging.DEBUG)
        main_handler.setFormatter(ProductionLogFormatter())
        self.logger.addHandler(main_handler)

        # Error log file
        error_handler = RotatingFileHandler(
            self.log_dir / f"{self.name}_errors.log",
            maxBytes=50 * 1024 * 1024,  # 50MB
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(ProductionLogFormatter())
        self.logger.addHandler(error_handler)

        # Console handler (info and above)
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )
        self.logger.addHandler(console_handler)

    def log_request(
        self,
        request_id: str,
        method: str,
        endpoint: str,
        status_code: int,
        duration_ms: float,
        error: Optional[str] = None
    ) -> None:
        """Log HTTP request."""
        extra = {
            "extra_fields": {
                "request_id": request_id,
                "method": method,
                "endpoint": endpoint,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "error": error
            }
        }

        level = logging.ERROR if status_code >= 500 else logging.INFO
        self.logger.log(
            level,
            f"{method} {endpoint} - {status_code} in {duration_ms:.2f}ms",
            extra=extra
        )

    def log_task(
        self,
        task_id: str,
        status: str,
        duration_ms: float,
        error: Optional[str] = None
    ) -> None:
        """Log task execution."""
        extra = {
            "extra_fields": {
                "task_id": task_id,
                "status": status,
                "duration_ms": duration_ms,
                "error": error
            }
        }

        level = logging.ERROR if error else logging.INFO
        self.logger.log(
            level,
            f"Task {task_id} {status} in {duration_ms:.2f}ms",
            extra=extra
        )

    def log_llm_call(
        self,
        provider: str,
        model: str,
        tokens_in: int,
        tokens_out: int,
        duration_ms: float,
        cost: float,
        error: Optional[str] = None
    ) -> None:
        """Log LLM API call."""
        extra = {
            "extra_fields": {
                "provider": provider,
                "model": model,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "duration_ms": duration_ms,
                "cost": cost,
                "error": error
            }
        }

        level = logging.ERROR if error else logging.INFO
        self.logger.log(
            level,
            f"LLM {provider}/{model} - {tokens_in}→{tokens_out} tokens, "
            f"${cost:.4f}, {duration_ms:.2f}ms",
            extra=extra
        )

    def log_error(
        self,
        error_type: str,
        error_message: str,
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Log error with categorization."""
        category = self.error_categorizer.categorize(error_type, error_message)
        error_hash = self.error_categorizer.get_error_hash(error_type, error_message)

        extra = {
            "extra_fields": {
                "error_type": error_type,
                "error_message": error_message,
                "error_category": category,
                "error_hash": error_hash
            }
        }

        if context:
            extra["extra_fields"].update(context)

        self.logger.error(
            f"[{category}] {error_type}: {error_message}",
            extra=extra
        )

        return error_hash

    def log_metric(
        self,
        metric_name: str,
        value: float,
        unit: str = "",
        tags: Optional[Dict[str, str]] = None
    ) -> None:
        """Log a metric."""
        extra = {
            "extra_fields": {
                "metric_name": metric_name,
                "metric_value": value,
                "metric_unit": unit,
                "tags": tags or {}
            }
        }

        self.logger.info(
            f"Metric {metric_name}: {value}{unit}",
            extra=extra
        )

    def get_log_files(self) -> List[str]:
        """Get list of log files."""
        return [str(f) for f in self.log_dir.glob(f"{self.name}*.log*")]

    def cleanup_old_logs(self, days: int = 7) -> int:
        """Clean up logs older than N days."""
        import time as time_module
        cutoff_time = time_module.time() - (days * 86400)
        deleted = 0

        for log_file in self.log_dir.glob(f"{self.name}*.log*"):
            if os.path.getmtime(log_file) < cutoff_time:
                try:
                    os.remove(log_file)
                    deleted += 1
                except Exception as e:
                    self.logger.warning(f"Failed to delete {log_file}: {e}")

        return deleted
