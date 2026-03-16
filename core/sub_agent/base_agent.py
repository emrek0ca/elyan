"""
core/sub_agent/base_agent.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: SubAgent Base Class (~300 lines)
Base class for all specialized sub-agents with lifecycle management.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, Optional, List, Callable
from enum import Enum
from abc import ABC, abstractmethod
import uuid
from utils.logger import get_logger

logger = get_logger("sub_agent")


class AgentState(Enum):
    """Agent lifecycle states."""
    IDLE = "idle"
    INITIALIZING = "initializing"
    READY = "ready"
    EXECUTING = "executing"
    ERROR = "error"
    RECOVERING = "recovering"
    SHUTDOWN = "shutdown"


class ExecutionStatus(Enum):
    """Task execution status."""
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass
class AgentConfig:
    """Configuration for a sub-agent."""
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = "SubAgent"
    description: str = ""
    max_retries: int = 3
    retry_delay_seconds: float = 1.0
    timeout_seconds: float = 300.0
    enable_logging: bool = True
    enable_error_recovery: bool = True
    auto_cleanup: bool = True
    max_concurrent_tasks: int = 1
    memory_limit_mb: int = 512

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ExecutionResult:
    """Result of task execution."""
    task_id: str
    status: ExecutionStatus
    output: Optional[Any] = None
    error: Optional[str] = None
    error_type: Optional[str] = None
    execution_time_ms: float = 0.0
    retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status.name,
            "output": self.output,
            "error": self.error,
            "error_type": self.error_type,
            "execution_time_ms": self.execution_time_ms,
            "retries": self.retries,
            "metadata": self.metadata,
            "timestamp": self.timestamp,
        }

    @property
    def is_success(self) -> bool:
        """Check if execution was successful."""
        return self.status == ExecutionStatus.SUCCESS

    @property
    def is_failure(self) -> bool:
        """Check if execution failed."""
        return self.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT)


class SubAgent(ABC):
    """Base class for all specialized sub-agents."""

    def __init__(self, config: Optional[AgentConfig] = None):
        """Initialize sub-agent."""
        self.config = config or AgentConfig()
        self.state = AgentState.IDLE
        self.current_task_id: Optional[str] = None
        self.execution_history: List[ExecutionResult] = []
        self.error_handlers: Dict[str, Callable] = {}
        self.state_callbacks: Dict[AgentState, List[Callable]] = {}
        self._lock = asyncio.Lock()
        self._metrics = {
            "total_tasks": 0,
            "successful_tasks": 0,
            "failed_tasks": 0,
            "total_time_ms": 0.0,
            "total_retries": 0,
            "start_time": time.time(),
        }

        logger.info(f"Initialized {self.config.name} (ID: {self.config.agent_id})")

    async def initialize(self) -> bool:
        """Initialize agent resources."""
        try:
            async with self._lock:
                self._set_state(AgentState.INITIALIZING)
                success = await self._on_initialize()
                if success:
                    self._set_state(AgentState.READY)
                    logger.info(f"Agent {self.config.name} initialized successfully")
                    return True
                else:
                    self._set_state(AgentState.ERROR)
                    return False
        except Exception as e:
            logger.error(f"Initialization error: {e}")
            self._set_state(AgentState.ERROR)
            return False

    async def execute(self, task_id: str, task_input: Dict[str, Any], timeout: Optional[float] = None) -> ExecutionResult:
        """Execute a task."""
        start_time = time.time()
        timeout = timeout or self.config.timeout_seconds
        self.current_task_id = task_id
        retry_count = 0

        try:
            async with self._lock:
                if self.state != AgentState.READY:
                    return ExecutionResult(
                        task_id=task_id,
                        status=ExecutionStatus.FAILED,
                        error="Agent not ready",
                        error_type="AgentNotReady",
                    )

                self._set_state(AgentState.EXECUTING)

            # Execute with timeout
            try:
                output = await asyncio.wait_for(
                    self._execute_task(task_id, task_input),
                    timeout=timeout
                )
                result = ExecutionResult(
                    task_id=task_id,
                    status=ExecutionStatus.SUCCESS,
                    output=output,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )
            except asyncio.TimeoutError:
                result = ExecutionResult(
                    task_id=task_id,
                    status=ExecutionStatus.TIMEOUT,
                    error=f"Task exceeded {timeout}s timeout",
                    error_type="TimeoutError",
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

        except Exception as e:
            error_type = type(e).__name__
            error_msg = str(e)

            # Try error recovery if enabled
            if self.config.enable_error_recovery:
                recovered = await self._handle_error(error_type, error_msg, task_input)
                if recovered:
                    result = ExecutionResult(
                        task_id=task_id,
                        status=ExecutionStatus.SUCCESS,
                        output=recovered,
                        execution_time_ms=(time.time() - start_time) * 1000,
                        metadata={"recovered": True},
                    )
                else:
                    result = ExecutionResult(
                        task_id=task_id,
                        status=ExecutionStatus.FAILED,
                        error=error_msg,
                        error_type=error_type,
                        execution_time_ms=(time.time() - start_time) * 1000,
                    )
            else:
                result = ExecutionResult(
                    task_id=task_id,
                    status=ExecutionStatus.FAILED,
                    error=error_msg,
                    error_type=error_type,
                    execution_time_ms=(time.time() - start_time) * 1000,
                )

        finally:
            async with self._lock:
                self._set_state(AgentState.READY)
                self.current_task_id = None

        # Record result
        self.execution_history.append(result)
        self._update_metrics(result)

        logger.info(f"Task {task_id} completed: {result.status.name}")

        return result

    async def shutdown(self) -> None:
        """Shutdown agent and cleanup resources."""
        try:
            async with self._lock:
                self._set_state(AgentState.SHUTDOWN)
                await self._on_cleanup()
                logger.info(f"Agent {self.config.name} shut down successfully")
        except Exception as e:
            logger.error(f"Shutdown error: {e}")

    def register_error_handler(self, error_type: str, handler: Callable[[str, Dict[str, Any]], Any]) -> None:
        """Register custom error handler."""
        self.error_handlers[error_type] = handler

    def on_state_change(self, state: AgentState, callback: Callable[[], None]) -> None:
        """Register callback for state changes."""
        if state not in self.state_callbacks:
            self.state_callbacks[state] = []
        self.state_callbacks[state].append(callback)

    def get_metrics(self) -> Dict[str, Any]:
        """Get agent performance metrics."""
        uptime = time.time() - self._metrics["start_time"]
        return {
            **self._metrics,
            "uptime_seconds": uptime,
            "success_rate": (
                self._metrics["successful_tasks"] / max(1, self._metrics["total_tasks"])
                if self._metrics["total_tasks"] > 0 else 0.0
            ),
            "avg_execution_time_ms": (
                self._metrics["total_time_ms"] / max(1, self._metrics["total_tasks"])
                if self._metrics["total_tasks"] > 0 else 0.0
            ),
            "state": self.state.name,
        }

    # ─── Abstract methods (to be implemented by subclasses) ───

    @abstractmethod
    async def _on_initialize(self) -> bool:
        """Initialize agent-specific resources."""
        pass

    @abstractmethod
    async def _execute_task(self, task_id: str, task_input: Dict[str, Any]) -> Any:
        """Execute the actual task."""
        pass

    @abstractmethod
    async def _on_cleanup(self) -> None:
        """Cleanup agent resources."""
        pass

    # ─── Error handling ───

    async def _handle_error(self, error_type: str, error_msg: str, task_input: Dict[str, Any]) -> Optional[Any]:
        """Handle execution errors with recovery."""
        logger.warning(f"Error in {self.config.name}: {error_type}: {error_msg}")

        # Check for custom handler
        if error_type in self.error_handlers:
            try:
                return await self.error_handlers[error_type](error_msg, task_input)
            except Exception as e:
                logger.error(f"Custom error handler failed: {e}")

        # Default error handling
        return await self._default_error_recovery(error_type, task_input)

    async def _default_error_recovery(self, error_type: str, task_input: Dict[str, Any]) -> Optional[Any]:
        """Default error recovery logic."""
        self._set_state(AgentState.RECOVERING)

        # Implement retry with backoff
        for attempt in range(self.config.max_retries):
            try:
                delay = self.config.retry_delay_seconds * (2 ** attempt)  # exponential backoff
                await asyncio.sleep(delay)
                return await self._execute_task(self.current_task_id or "retry", task_input)
            except Exception:
                if attempt == self.config.max_retries - 1:
                    return None
                continue

        return None

    # ─── State management ───

    def _set_state(self, new_state: AgentState) -> None:
        """Set agent state and trigger callbacks."""
        old_state = self.state
        self.state = new_state

        if self.config.enable_logging:
            logger.debug(f"{self.config.name} state: {old_state.name} -> {new_state.name}")

        # Trigger callbacks
        if new_state in self.state_callbacks:
            for callback in self.state_callbacks[new_state]:
                try:
                    result = callback()
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception as e:
                    logger.error(f"State callback error: {e}")

    def _update_metrics(self, result: ExecutionResult) -> None:
        """Update performance metrics."""
        self._metrics["total_tasks"] += 1
        if result.is_success:
            self._metrics["successful_tasks"] += 1
        else:
            self._metrics["failed_tasks"] += 1

        self._metrics["total_time_ms"] += result.execution_time_ms
        self._metrics["total_retries"] += result.retries

    # ─── Validation helpers ───

    def validate_input(self, task_input: Dict[str, Any], required_fields: List[str]) -> bool:
        """Validate task input has required fields."""
        return all(field in task_input for field in required_fields)

    def validate_output(self, output: Any, output_type: type) -> bool:
        """Validate task output is of expected type."""
        return isinstance(output, output_type)

    # ─── Logging helpers ───

    def log_debug(self, message: str) -> None:
        """Log debug message."""
        logger.debug(f"[{self.config.name}] {message}")

    def log_info(self, message: str) -> None:
        """Log info message."""
        logger.info(f"[{self.config.name}] {message}")

    def log_error(self, message: str) -> None:
        """Log error message."""
        logger.error(f"[{self.config.name}] {message}")
