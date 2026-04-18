from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any


class ContextLogger:
    """Lightweight logger wrapper that carries structured context."""

    def __init__(self, name: str, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger(str(name or "production"))
        self.context: dict[str, Any] = {}

    def set_context(self, **kwargs: Any) -> None:
        for key, value in kwargs.items():
            if key:
                self.context[str(key)] = value

    def clear_context(self) -> None:
        self.context.clear()


class PerformanceLogger:
    """Measure operation durations in milliseconds."""

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self.logger = logger or logging.getLogger("production.performance")
        self._timers: dict[str, float] = {}

    def start_timer(self, name: str) -> None:
        key = str(name or "").strip()
        if not key:
            return
        self._timers[key] = time.perf_counter()

    def end_timer(self, name: str) -> float:
        key = str(name or "").strip()
        started_at = self._timers.pop(key, None)
        if started_at is None:
            return 0.0
        duration_ms = (time.perf_counter() - started_at) * 1000.0
        self.logger.debug("timer_finished", extra={"timer": key, "duration_ms": duration_ms})
        return duration_ms


class ErrorCategorizer:
    """Map error text to coarse production categories."""

    _CATEGORY_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("database", ("database", "sqlite", "sql", "db")),
        ("network", ("network", "timeout", "http", "request", "connection")),
        ("auth", ("auth", "unauthorized", "forbidden", "permission")),
        ("filesystem", ("file", "disk", "path", "io", "storage")),
    )

    @classmethod
    def categorize(cls, error_type: str, error_message: str) -> str:
        haystack = f"{error_type or ''} {error_message or ''}".lower()
        for category, needles in cls._CATEGORY_RULES:
            if any(needle in haystack for needle in needles):
                return category
        return "unknown"

    @staticmethod
    def get_error_hash(error_type: str, error_message: str) -> str:
        payload = f"{error_type or ''}\n{error_message or ''}".encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


class ProductionLogger:
    """File-backed structured logger for production telemetry."""

    def __init__(self, bot_name: str, log_dir: str | Path) -> None:
        self.bot_name = str(bot_name or "elyan").strip() or "elyan"
        self.log_dir = Path(log_dir).expanduser().resolve()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_file = self.log_dir / f"{self.bot_name}.log"

        logger_name = f"production.{self.bot_name}.{self.log_dir.as_posix().replace('/', '_')}"
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)
        self.logger.propagate = False
        self._reset_handlers()

    def _reset_handlers(self) -> None:
        for handler in list(self.logger.handlers):
            self.logger.removeHandler(handler)
            try:
                handler.close()
            except Exception:
                pass

        handler = logging.FileHandler(self.log_file, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(message)s"))
        self.logger.addHandler(handler)

    @staticmethod
    def _compact_payload(event_type: str, payload: dict[str, Any]) -> str:
        return json.dumps({"event": event_type, **payload}, ensure_ascii=False, separators=(",", ":"))

    def _write_event(self, event_type: str, **payload: Any) -> None:
        self.logger.info(self._compact_payload(event_type, payload))
        for handler in self.logger.handlers:
            try:
                handler.flush()
            except Exception:
                pass

    def get_log_files(self) -> list[Path]:
        return sorted(p for p in self.log_dir.glob("*.log") if p.is_file())

    def log_request(
        self,
        *,
        request_id: str,
        method: str,
        endpoint: str,
        status_code: int,
        duration_ms: float,
    ) -> None:
        self._write_event(
            "request",
            request_id=str(request_id or ""),
            method=str(method or "").upper(),
            endpoint=str(endpoint or ""),
            status_code=int(status_code or 0),
            duration_ms=float(duration_ms or 0.0),
        )

    def log_task(self, *, task_id: str, status: str, duration_ms: float) -> None:
        self._write_event(
            "task",
            task_id=str(task_id or ""),
            status=str(status or ""),
            duration_ms=float(duration_ms or 0.0),
        )

    def log_error(self, *, error_type: str, error_message: str) -> str:
        error_hash = ErrorCategorizer.get_error_hash(error_type, error_message)
        self._write_event(
            "error",
            error_type=str(error_type or ""),
            error_message=str(error_message or ""),
            error_hash=error_hash,
            category=ErrorCategorizer.categorize(error_type, error_message),
        )
        return error_hash


__all__ = [
    "ContextLogger",
    "ErrorCategorizer",
    "PerformanceLogger",
    "ProductionLogger",
]
