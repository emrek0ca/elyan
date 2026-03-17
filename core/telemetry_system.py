"""
ELYAN Telemetry & Logging System - Phase 6
Structured logging, distributed tracing, session analytics.
"""

import json
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventCategory(Enum):
    REQUEST = "request"
    RESPONSE = "response"
    ERROR = "error"
    AUTH = "auth"
    TASK = "task"
    AGENT = "agent"
    LLM = "llm"
    TOOL = "tool"
    LEARNING = "learning"
    SYSTEM = "system"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class TraceSpan:
    trace_id: str
    span_id: str
    parent_span_id: Optional[str]
    operation: str
    service: str
    start_time: float
    end_time: float = 0.0
    duration_ms: float = 0.0
    status: str = "ok"
    tags: Dict[str, str] = field(default_factory=dict)
    logs: List[Dict[str, Any]] = field(default_factory=list)

    def finish(self, status: str = "ok"):
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status


@dataclass
class TelemetryEvent:
    event_id: str
    category: EventCategory
    level: LogLevel
    message: str
    timestamp: float
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    trace_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionInfo:
    session_id: str
    user_id: str
    start_time: float
    end_time: float = 0.0
    request_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    events: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def avg_latency_ms(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.total_latency_ms / self.request_count

    @property
    def error_rate(self) -> float:
        if self.request_count == 0:
            return 0.0
        return self.error_count / self.request_count


class DistributedTracer:
    """Lightweight distributed tracing system."""

    def __init__(self):
        self._traces: Dict[str, List[TraceSpan]] = defaultdict(list)
        self._active_spans: Dict[str, TraceSpan] = {}

    def start_trace(self, operation: str, service: str = "elyan") -> TraceSpan:
        trace_id = uuid.uuid4().hex[:16]
        span_id = uuid.uuid4().hex[:8]
        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=None,
            operation=operation,
            service=service,
            start_time=time.time(),
        )
        self._active_spans[span_id] = span
        self._traces[trace_id].append(span)
        return span

    def start_span(
        self,
        trace_id: str,
        operation: str,
        parent_span_id: Optional[str] = None,
        service: str = "elyan",
    ) -> TraceSpan:
        span_id = uuid.uuid4().hex[:8]
        span = TraceSpan(
            trace_id=trace_id,
            span_id=span_id,
            parent_span_id=parent_span_id,
            operation=operation,
            service=service,
            start_time=time.time(),
        )
        self._active_spans[span_id] = span
        self._traces[trace_id].append(span)
        return span

    def finish_span(self, span_id: str, status: str = "ok"):
        span = self._active_spans.pop(span_id, None)
        if span:
            span.finish(status)

    def get_trace(self, trace_id: str) -> List[TraceSpan]:
        return self._traces.get(trace_id, [])

    def get_trace_summary(self, trace_id: str) -> Dict[str, Any]:
        spans = self._traces.get(trace_id, [])
        if not spans:
            return {}
        total_duration = sum(s.duration_ms for s in spans if s.duration_ms > 0)
        errors = [s for s in spans if s.status == "error"]
        return {
            "trace_id": trace_id,
            "span_count": len(spans),
            "total_duration_ms": round(total_duration, 2),
            "error_count": len(errors),
            "services": list({s.service for s in spans}),
            "operations": [s.operation for s in spans],
        }


class SessionTracker:
    """Track user sessions and compute analytics."""

    def __init__(self):
        self._sessions: Dict[str, SessionInfo] = {}
        self._user_sessions: Dict[str, List[str]] = defaultdict(list)

    def start_session(self, user_id: str) -> SessionInfo:
        session_id = f"sess_{uuid.uuid4().hex[:12]}"
        session = SessionInfo(
            session_id=session_id,
            user_id=user_id,
            start_time=time.time(),
        )
        self._sessions[session_id] = session
        self._user_sessions[user_id].append(session_id)
        return session

    def record_request(self, session_id: str, latency_ms: float, is_error: bool = False):
        session = self._sessions.get(session_id)
        if session:
            session.request_count += 1
            session.total_latency_ms += latency_ms
            if is_error:
                session.error_count += 1

    def end_session(self, session_id: str):
        session = self._sessions.get(session_id)
        if session:
            session.end_time = time.time()

    def get_session(self, session_id: str) -> Optional[SessionInfo]:
        return self._sessions.get(session_id)

    def get_user_sessions(self, user_id: str) -> List[SessionInfo]:
        session_ids = self._user_sessions.get(user_id, [])
        return [self._sessions[sid] for sid in session_ids if sid in self._sessions]

    def get_analytics(self) -> Dict[str, Any]:
        all_sessions = list(self._sessions.values())
        if not all_sessions:
            return {"total_sessions": 0}
        active = [s for s in all_sessions if s.end_time == 0.0]
        completed = [s for s in all_sessions if s.end_time > 0.0]
        total_requests = sum(s.request_count for s in all_sessions)
        total_errors = sum(s.error_count for s in all_sessions)
        avg_latencies = [s.avg_latency_ms for s in all_sessions if s.request_count > 0]
        return {
            "total_sessions": len(all_sessions),
            "active_sessions": len(active),
            "completed_sessions": len(completed),
            "unique_users": len(self._user_sessions),
            "total_requests": total_requests,
            "total_errors": total_errors,
            "overall_error_rate": total_errors / max(1, total_requests),
            "avg_latency_ms": round(sum(avg_latencies) / max(1, len(avg_latencies)), 2),
        }


class StructuredLogger:
    """JSON structured logging for cloud environments."""

    def __init__(self, service: str = "elyan", environment: str = "production"):
        self.service = service
        self.environment = environment
        self._events: List[TelemetryEvent] = []
        self._max_events = 10000
        self._logger = logging.getLogger("elyan.telemetry")

    def log(
        self,
        category: EventCategory,
        level: LogLevel,
        message: str,
        user_id: Optional[str] = None,
        session_id: Optional[str] = None,
        trace_id: Optional[str] = None,
        **metadata,
    ) -> TelemetryEvent:
        event = TelemetryEvent(
            event_id=uuid.uuid4().hex[:12],
            category=category,
            level=level,
            message=message,
            timestamp=time.time(),
            user_id=user_id,
            session_id=session_id,
            trace_id=trace_id,
            metadata=metadata,
        )
        self._events.append(event)
        if len(self._events) > self._max_events:
            self._events = self._events[-self._max_events:]
        return event

    def info(self, message: str, category: EventCategory = EventCategory.SYSTEM, **kwargs):
        return self.log(category, LogLevel.INFO, message, **kwargs)

    def error(self, message: str, category: EventCategory = EventCategory.ERROR, **kwargs):
        return self.log(category, LogLevel.ERROR, message, **kwargs)

    def warning(self, message: str, category: EventCategory = EventCategory.SYSTEM, **kwargs):
        return self.log(category, LogLevel.WARNING, message, **kwargs)

    def query(
        self,
        category: Optional[EventCategory] = None,
        level: Optional[LogLevel] = None,
        user_id: Optional[str] = None,
        since: Optional[float] = None,
        limit: int = 100,
    ) -> List[TelemetryEvent]:
        results = self._events
        if category:
            results = [e for e in results if e.category == category]
        if level:
            results = [e for e in results if e.level == level]
        if user_id:
            results = [e for e in results if e.user_id == user_id]
        if since:
            results = [e for e in results if e.timestamp >= since]
        return results[-limit:]

    def get_error_summary(self, hours: int = 24) -> Dict[str, Any]:
        since = time.time() - (hours * 3600)
        errors = self.query(level=LogLevel.ERROR, since=since)
        criticals = self.query(level=LogLevel.CRITICAL, since=since)
        by_category: Dict[str, int] = defaultdict(int)
        for e in errors + criticals:
            by_category[e.category.value] += 1
        return {
            "total_errors": len(errors),
            "total_criticals": len(criticals),
            "by_category": dict(by_category),
            "period_hours": hours,
        }

    def export_json(self, limit: int = 100) -> str:
        events = self._events[-limit:]
        return json.dumps(
            [
                {
                    "event_id": e.event_id,
                    "category": e.category.value,
                    "level": e.level.value,
                    "message": e.message,
                    "timestamp": e.timestamp,
                    "user_id": e.user_id,
                    "session_id": e.session_id,
                    "trace_id": e.trace_id,
                    "metadata": e.metadata,
                    "service": self.service,
                    "environment": self.environment,
                }
                for e in events
            ],
            indent=2,
        )


class TelemetrySystem:
    """Unified telemetry coordinator."""

    def __init__(self, service: str = "elyan", environment: str = "production"):
        self.logger = StructuredLogger(service, environment)
        self.tracer = DistributedTracer()
        self.session_tracker = SessionTracker()

    def start_request(
        self,
        user_id: str,
        operation: str,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        span = self.tracer.start_trace(operation)
        self.logger.info(
            f"Request started: {operation}",
            category=EventCategory.REQUEST,
            user_id=user_id,
            trace_id=span.trace_id,
            session_id=session_id,
        )
        return {
            "trace_id": span.trace_id,
            "span_id": span.span_id,
            "session_id": session_id,
        }

    def end_request(
        self,
        trace_id: str,
        span_id: str,
        status: str = "ok",
        session_id: Optional[str] = None,
        latency_ms: float = 0.0,
    ):
        self.tracer.finish_span(span_id, status)
        if session_id:
            self.session_tracker.record_request(
                session_id, latency_ms, is_error=(status == "error")
            )
        level = LogLevel.INFO if status == "ok" else LogLevel.ERROR
        self.logger.log(
            EventCategory.RESPONSE,
            level,
            f"Request completed: {status} ({latency_ms:.1f}ms)",
            trace_id=trace_id,
            session_id=session_id,
            latency_ms=latency_ms,
        )

    def get_system_health(self) -> Dict[str, Any]:
        analytics = self.session_tracker.get_analytics()
        errors = self.logger.get_error_summary(hours=1)
        return {
            "sessions": analytics,
            "errors_last_hour": errors,
            "active_traces": len(self.tracer._active_spans),
        }
