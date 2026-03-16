"""
ExecutionModel - Core data structures for execution tracking and error handling

Provides unified structures for tracking tool execution, partial failures,
error recovery, and execution reports with complete Turkish/English support.

Part of RELIABILITY FOUNDATION (Hafta 1-2)
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Optional, Dict, List, Tuple
from datetime import datetime
from enum import Enum
import json


class ExecutionStatus(Enum):
    """Execution status codes"""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ErrorSeverity(Enum):
    """Error severity levels"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for classification and recovery"""
    VALIDATION_ERROR = "validation_error"
    SCHEMA_ERROR = "schema_error"
    TOOL_NOT_FOUND = "tool_not_found"
    TOOL_ERROR = "tool_error"
    PARAMETER_ERROR = "parameter_error"
    PERMISSION_ERROR = "permission_error"
    RESOURCE_ERROR = "resource_error"
    TIMEOUT_ERROR = "timeout_error"
    NETWORK_ERROR = "network_error"
    PARSER_ERROR = "parser_error"
    JSON_ERROR = "json_error"
    STATE_ERROR = "state_error"
    DEPENDENCY_ERROR = "dependency_error"
    ENVIRONMENT_ERROR = "environment_error"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class ExecutionError:
    """
    Structured execution error with full context for recovery and debugging

    Attributes:
        message (str): Human-readable error message (Turkish/English)
        category (ErrorCategory): Error classification
        severity (ErrorSeverity): Error severity level
        code (str): Machine-readable error code
        tool (Optional[str]): Tool that failed
        action (Optional[str]): Action being performed
        params (Dict[str, Any]): Parameters used when error occurred
        timestamp (datetime): When error occurred
        traceback (Optional[str]): Python traceback
        context (Dict[str, Any]): Additional context for debugging
        suggestions (List[str]): Recovery suggestions
        retry_available (bool): Whether operation can be retried
        recoverable (bool): Whether error is recoverable
        partial_result (Optional[Dict[str, Any]]): Any partial results before error
    """
    message: str
    category: ErrorCategory
    severity: ErrorSeverity
    code: str
    tool: Optional[str] = None
    action: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    traceback: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)
    suggestions: List[str] = field(default_factory=list)
    retry_available: bool = False
    recoverable: bool = False
    partial_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary (with datetime serialization)"""
        data = asdict(self)
        data["timestamp"] = self.timestamp.isoformat()
        data["category"] = self.category.value
        data["severity"] = self.severity.value
        return data

    def to_json(self) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionError":
        """Create from dictionary"""
        if isinstance(data.get("timestamp"), str):
            data["timestamp"] = datetime.fromisoformat(data["timestamp"])
        if isinstance(data.get("category"), str):
            data["category"] = ErrorCategory(data["category"])
        if isinstance(data.get("severity"), str):
            data["severity"] = ErrorSeverity(data["severity"])
        return cls(**data)

    def is_retryable(self) -> bool:
        """Check if error is retryable"""
        return self.retry_available and self.recoverable

    def get_recovery_suggestion(self) -> Optional[str]:
        """Get first/best recovery suggestion"""
        return self.suggestions[0] if self.suggestions else None


@dataclass
class ExecutionMetrics:
    """
    Metrics from execution for performance tracking

    Attributes:
        start_time (datetime): When execution started
        end_time (Optional[datetime]): When execution ended
        duration_ms (float): Total execution time in milliseconds
        retry_count (int): Number of retries
        tool_calls (int): Number of tool calls made
        api_calls (int): Number of API calls made
        tokens_used (int): Tokens used (for LLM calls)
        memory_peak_mb (float): Peak memory usage
        cache_hits (int): Number of cache hits
        cache_misses (int): Number of cache misses
    """
    start_time: datetime = field(default_factory=datetime.now)
    end_time: Optional[datetime] = None
    duration_ms: float = 0.0
    retry_count: int = 0
    tool_calls: int = 0
    api_calls: int = 0
    tokens_used: int = 0
    memory_peak_mb: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0

    def finalize(self) -> None:
        """Calculate final metrics"""
        if self.end_time is None:
            self.end_time = datetime.now()
        self.duration_ms = (self.end_time - self.start_time).total_seconds() * 1000

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "duration_ms": self.duration_ms,
            "retry_count": self.retry_count,
            "tool_calls": self.tool_calls,
            "api_calls": self.api_calls,
            "tokens_used": self.tokens_used,
            "memory_peak_mb": self.memory_peak_mb,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
        }


@dataclass
class TaskExecutionState:
    """
    Current state of a task execution

    Attributes:
        task_id (str): Unique task identifier
        status (ExecutionStatus): Current status
        subtasks (Dict[str, ExecutionStatus]): Status of each subtask
        completed_subtasks (List[str]): Completed subtask IDs
        failed_subtasks (List[str]): Failed subtask IDs
        skipped_subtasks (List[str]): Skipped subtask IDs
        current_step (Optional[str]): Current execution step
        progress_percent (int): Completion percentage (0-100)
    """
    task_id: str
    status: ExecutionStatus = ExecutionStatus.PENDING
    subtasks: Dict[str, ExecutionStatus] = field(default_factory=dict)
    completed_subtasks: List[str] = field(default_factory=list)
    failed_subtasks: List[str] = field(default_factory=list)
    skipped_subtasks: List[str] = field(default_factory=list)
    current_step: Optional[str] = None
    progress_percent: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "task_id": self.task_id,
            "status": self.status.value,
            "subtasks": {k: v.value for k, v in self.subtasks.items()},
            "completed_subtasks": self.completed_subtasks,
            "failed_subtasks": self.failed_subtasks,
            "skipped_subtasks": self.skipped_subtasks,
            "current_step": self.current_step,
            "progress_percent": self.progress_percent,
        }


@dataclass
class ToolExecutionResult:
    """
    Result from single tool execution

    Attributes:
        tool_name (str): Tool that was executed
        action (str): Action performed
        status (ExecutionStatus): Execution status
        output (Any): Tool output
        error (Optional[ExecutionError]): Error if any
        metrics (ExecutionMetrics): Execution metrics
        timestamp (datetime): When execution completed
    """
    tool_name: str
    action: str
    status: ExecutionStatus
    output: Any = None
    error: Optional[ExecutionError] = None
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    timestamp: datetime = field(default_factory=datetime.now)

    def is_successful(self) -> bool:
        """Check if execution was successful"""
        return self.status == ExecutionStatus.SUCCESS

    def is_partial_success(self) -> bool:
        """Check if execution had partial success"""
        return self.status == ExecutionStatus.PARTIAL_SUCCESS

    def has_error(self) -> bool:
        """Check if execution had error"""
        return self.error is not None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "tool_name": self.tool_name,
            "action": self.action,
            "status": self.status.value,
            "output": self.output,
            "error": self.error.to_dict() if self.error else None,
            "metrics": self.metrics.to_dict(),
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass
class PartialFailureInfo:
    """
    Information about partial failure scenarios

    Attributes:
        succeeded_items (List[str]): Items that succeeded
        failed_items (List[str]): Items that failed
        skipped_items (List[str]): Items that were skipped
        item_errors (Dict[str, ExecutionError]): Errors per item
        overall_success_rate (float): Success percentage
        is_acceptable (bool): Whether partial success meets requirements
        recovery_possible (bool): Whether recovery is possible
        recommendations (List[str]): Recommended next steps
    """
    succeeded_items: List[str] = field(default_factory=list)
    failed_items: List[str] = field(default_factory=list)
    skipped_items: List[str] = field(default_factory=list)
    item_errors: Dict[str, ExecutionError] = field(default_factory=dict)
    overall_success_rate: float = 0.0
    is_acceptable: bool = False
    recovery_possible: bool = False
    recommendations: List[str] = field(default_factory=list)

    def calculate_success_rate(self) -> float:
        """Calculate success rate"""
        total = len(self.succeeded_items) + len(self.failed_items)
        if total == 0:
            return 0.0
        return (len(self.succeeded_items) / total) * 100

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "succeeded_items": self.succeeded_items,
            "failed_items": self.failed_items,
            "skipped_items": self.skipped_items,
            "item_errors": {k: v.to_dict() for k, v in self.item_errors.items()},
            "overall_success_rate": self.overall_success_rate,
            "is_acceptable": self.is_acceptable,
            "recovery_possible": self.recovery_possible,
            "recommendations": self.recommendations,
        }


# Convenience type aliases
ExecutionResult = Tuple[ExecutionStatus, Any, Optional[ExecutionError]]
ValidationResult = Tuple[bool, List[str]]
