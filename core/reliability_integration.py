"""
Reliability Integration - Integration layer for reliability foundation

Provides utility functions and adapters for integrating RELIABILITY FOUNDATION
modules with existing agent.py and task_engine.py code.

Part of RELIABILITY FOUNDATION (Hafta 1-2)
"""

from typing import Any, Dict, Optional, Tuple, Callable
from dataclasses import dataclass
import functools
import sys
import traceback

from core.execution_model import (
    ExecutionStatus,
    ExecutionError,
    ExecutionMetrics,
    ToolExecutionResult,
    ErrorSeverity,
    ErrorCategory,
)
from core.validators import (
    ComprehensiveValidator,
    ValidationContext,
    ValidationLevel,
    RiskAssessment,
)
from core.json_repair import JSONRepair
from core.execution_report import (
    ExecutionReport,
    ExecutionReportBuilder,
)
from core.tool_schemas import get_schema_registry
from utils.logger import get_logger

logger = get_logger("reliability_integration")


class ExecutionGuard:
    """Decorator for protected tool execution"""

    @staticmethod
    def with_error_handling(
        tool_name: str,
        action: str = "execute",
        context: Optional[ValidationContext] = None,
    ):
        """
        Decorator for tool execution with error handling

        Usage:
            @ExecutionGuard.with_error_handling("tool_name", context=ctx)
            def my_tool_func(params):
                return result

        Returns:
            (success, result, error)
        """

        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs) -> Tuple[bool, Any, Optional[ExecutionError]]:
                metrics = ExecutionMetrics()

                try:
                    # Pre-validation
                    params = kwargs.get("params", {})
                    if params:
                        validation_result = ComprehensiveValidator.validate_execution(
                            tool_name, action, params, context
                        )

                        if not validation_result.is_valid:
                            error = ExecutionError(
                                message="; ".join(validation_result.errors),
                                category=ErrorCategory.VALIDATION_ERROR,
                                severity=ErrorSeverity.ERROR,
                                code="VALIDATION_FAILED",
                                tool=tool_name,
                                action=action,
                                params=params,
                                suggestions=validation_result.suggestions,
                                recoverable=False,
                            )
                            return False, None, error

                    # Execute tool
                    result = func(*args, **kwargs)
                    metrics.finalize()
                    return True, result, None

                except Exception as e:
                    metrics.finalize()
                    error = ExecutionError(
                        message=str(e),
                        category=ErrorCategory.TOOL_ERROR,
                        severity=ErrorSeverity.ERROR,
                        code="TOOL_EXECUTION_ERROR",
                        tool=tool_name,
                        action=action,
                        traceback=traceback.format_exc(),
                        recoverable=True,
                        retry_available=True,
                    )
                    logger.error(f"Araç hata: {tool_name}: {e}")
                    return False, None, error

            return wrapper

        return decorator


class JSONRepairIntegration:
    """Integration for JSON repair with LLM responses"""

    @staticmethod
    def repair_llm_response(response: str) -> Tuple[bool, Any]:
        """
        Repair and parse LLM JSON response

        Returns:
            (success, parsed_data_or_error_message)
        """
        success, result, error = JSONRepair.repair_and_parse(response)
        return success, result if success else error

    @staticmethod
    def safe_parse_tool_output(output: Any) -> Dict[str, Any]:
        """
        Safely parse tool output, handling various formats

        Returns:
            Parsed output as dictionary
        """
        if isinstance(output, dict):
            return output

        if isinstance(output, str):
            success, result, _ = JSONRepair.repair_and_parse(output)
            if success and isinstance(result, dict):
                return result

        # Fallback to wrapped output
        return {"raw_output": output}


class ExecutionTracker:
    """Tracks tool executions for reporting and debugging"""

    def __init__(self):
        self.current_report: Optional[ExecutionReport] = None
        self.active_execution_id: Optional[str] = None

    def start_execution(self, execution_id: str, task_id: str, user_id: Optional[str] = None) -> ExecutionReport:
        """Start execution tracking"""
        self.active_execution_id = execution_id
        builder = ExecutionReportBuilder(execution_id, task_id)
        if user_id:
            builder.set_user(user_id)

        self.current_report = builder.build()
        logger.info(f"Yürütme başladı: {execution_id}")
        return self.current_report

    def record_tool_execution(
        self,
        tool_name: str,
        action: str,
        status: ExecutionStatus,
        output: Any = None,
        error: Optional[ExecutionError] = None,
    ) -> None:
        """Record individual tool execution"""
        if not self.current_report:
            return

        result = ToolExecutionResult(
            tool_name=tool_name,
            action=action,
            status=status,
            output=output,
            error=error,
        )

        self.current_report.add_tool_result(result)
        logger.info(f"Araç yürütme kaydedildi: {tool_name}/{action} = {status.value}")

    def end_execution(self, final_status: ExecutionStatus) -> ExecutionReport:
        """End execution tracking and return report"""
        if not self.current_report:
            return None

        self.current_report.status = final_status
        self.current_report.finalize()

        logger.info(f"Yürütme tamamlandı: {self.active_execution_id} = {final_status.value}")
        return self.current_report

    def get_current_report(self) -> Optional[ExecutionReport]:
        """Get current execution report"""
        return self.current_report


# Global execution tracker
_execution_tracker = ExecutionTracker()


def get_execution_tracker() -> ExecutionTracker:
    """Get global execution tracker"""
    return _execution_tracker


def create_execution_context(
    user_id: Optional[str] = None,
    allowed_tools: Optional[list] = None,
    blocked_tools: Optional[list] = None,
) -> ValidationContext:
    """Create validation context for execution"""
    return ValidationContext(
        user_id=user_id,
        allowed_tools=allowed_tools,
        blocked_tools=blocked_tools,
        permission_level=5,  # Default to moderate permission level
    )


def validate_before_execution(
    tool_name: str,
    action: str,
    params: Dict[str, Any],
    context: Optional[ValidationContext] = None,
) -> Tuple[bool, Optional[ExecutionError]]:
    """
    Comprehensive validation before tool execution

    Returns:
        (is_valid, error_if_any)
    """
    if context is None:
        context = create_execution_context()

    result = ComprehensiveValidator.validate_execution(
        tool_name, action, params, context, ValidationLevel.NORMAL
    )

    if not result.is_valid:
        error = ExecutionError(
            message="; ".join(result.errors),
            category=ErrorCategory.VALIDATION_ERROR,
            severity=ErrorSeverity.ERROR,
            code="PRE_EXECUTION_VALIDATION_FAILED",
            tool=tool_name,
            action=action,
            params=params,
            suggestions=result.suggestions,
            context={
                "validation_errors": result.errors,
                "warnings": result.warnings,
                "risk_level": result.risk_level.value,
            },
            recoverable=False,
        )
        return False, error

    return True, None


def sanitize_and_validate_params(
    tool_name: str,
    params: Dict[str, Any],
) -> Tuple[bool, Dict[str, Any], Optional[ExecutionError]]:
    """
    Sanitize and validate tool parameters using schema

    Returns:
        (is_valid, sanitized_params, error_if_any)
    """
    registry = get_schema_registry()
    schema = registry.get(tool_name)

    if not schema:
        return True, params, None

    # Validate
    is_valid, errors = schema.validate_params(params)
    if not is_valid:
        error = ExecutionError(
            message="; ".join(errors),
            category=ErrorCategory.PARAMETER_ERROR,
            severity=ErrorSeverity.ERROR,
            code="PARAMETER_VALIDATION_FAILED",
            tool=tool_name,
            params=params,
            recoverable=False,
        )
        return False, params, error

    # Sanitize
    sanitized = schema.sanitize_params(params)
    return True, sanitized, None


def assess_operation_risk(
    tool_name: str, action: str, params: Dict[str, Any]
) -> Tuple[str, bool]:
    """
    Assess risk of operation

    Returns:
        (risk_level, requires_approval)
    """
    risk_level = RiskAssessment.assess_risk(tool_name, action, params)
    requires_approval = RiskAssessment.requires_approval(risk_level)
    return risk_level.value, requires_approval


def safe_json_loads_for_tool(output: Any) -> Dict[str, Any]:
    """
    Safely load JSON from tool output

    Returns:
        Parsed JSON or wrapped output
    """
    return JSONRepairIntegration.safe_parse_tool_output(output)


# Convenience functions for common patterns
def record_tool_success(
    tracker: ExecutionTracker,
    tool_name: str,
    action: str,
    output: Any,
) -> None:
    """Record successful tool execution"""
    tracker.record_tool_execution(tool_name, action, ExecutionStatus.SUCCESS, output=output)


def record_tool_failure(
    tracker: ExecutionTracker,
    tool_name: str,
    action: str,
    error: ExecutionError,
) -> None:
    """Record failed tool execution"""
    tracker.record_tool_execution(tool_name, action, ExecutionStatus.FAILED, error=error)


def create_tool_error(
    message: str,
    tool_name: str,
    action: str,
    category: ErrorCategory = ErrorCategory.TOOL_ERROR,
    suggestions: Optional[list] = None,
    recoverable: bool = True,
) -> ExecutionError:
    """Create a structured tool error"""
    return ExecutionError(
        message=message,
        category=category,
        severity=ErrorSeverity.ERROR,
        code="TOOL_ERROR",
        tool=tool_name,
        action=action,
        suggestions=suggestions or [],
        recoverable=recoverable,
        retry_available=recoverable,
    )
