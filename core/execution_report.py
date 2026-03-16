"""
Execution Report - Comprehensive execution logging and reporting

Tracks complete execution lifecycle with detailed metrics, error tracking,
and recovery information. Supports partial failure scenarios.

Part of RELIABILITY FOUNDATION (Hafta 1-2)
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Callable
from datetime import datetime
from enum import Enum
import json
import hashlib
from pathlib import Path

from core.execution_model import (
    ExecutionStatus,
    ExecutionError,
    ExecutionMetrics,
    TaskExecutionState,
    ToolExecutionResult,
    PartialFailureInfo,
    ErrorSeverity,
    ErrorCategory,
)
from utils.logger import get_logger

logger = get_logger("execution_report")


class ReportFormat(Enum):
    """Report output formats"""
    JSON = "json"
    MARKDOWN = "markdown"
    TEXT = "text"
    HTML = "html"


@dataclass
class ExecutionReport:
    """
    Complete execution report with all context

    Attributes:
        report_id (str): Unique report identifier
        timestamp (datetime): When report was created
        execution_id (str): ID of execution being reported
        user_id (Optional[str]): User who initiated execution
        task_id (str): Task ID being executed
        status (ExecutionStatus): Final status
        metrics (ExecutionMetrics): Execution metrics
        state (TaskExecutionState): Task execution state
        tool_results (List[ToolExecutionResult]): Results from each tool
        errors (List[ExecutionError]): All errors encountered
        warnings (List[str]): All warnings
        partial_failure_info (Optional[PartialFailureInfo]): Partial failure details
        recovery_taken (List[str]): Recovery actions taken
        environment_info (Dict[str, Any]): System/environment information
        user_feedback (Optional[str]): User feedback on execution
    """

    report_id: str = field(default_factory=lambda: hashlib.md5(str(datetime.now()).encode()).hexdigest()[:16])
    timestamp: datetime = field(default_factory=datetime.now)
    execution_id: str = ""
    user_id: Optional[str] = None
    task_id: str = ""
    status: ExecutionStatus = ExecutionStatus.PENDING
    metrics: ExecutionMetrics = field(default_factory=ExecutionMetrics)
    state: TaskExecutionState = field(default_factory=lambda: TaskExecutionState(task_id=""))
    tool_results: List[ToolExecutionResult] = field(default_factory=list)
    errors: List[ExecutionError] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    partial_failure_info: Optional[PartialFailureInfo] = None
    recovery_taken: List[str] = field(default_factory=list)
    environment_info: Dict[str, Any] = field(default_factory=dict)
    user_feedback: Optional[str] = None

    def add_tool_result(self, result: ToolExecutionResult) -> None:
        """Add tool execution result"""
        self.tool_results.append(result)
        if result.error:
            self.add_error(result.error)

    def add_error(self, error: ExecutionError) -> None:
        """Add error to report"""
        self.errors.append(error)
        logger.error(f"Hata eklendi: {error.code} - {error.message}")

    def add_warning(self, message: str) -> None:
        """Add warning to report"""
        self.warnings.append(message)
        logger.warning(f"Uyarı: {message}")

    def record_recovery(self, action: str) -> None:
        """Record recovery action taken"""
        self.recovery_taken.append(f"{datetime.now().isoformat()}: {action}")
        logger.info(f"Kurtarma kaydedildi: {action}")

    def finalize(self) -> None:
        """Finalize report and calculate metrics"""
        self.metrics.finalize()

        # Calculate summary stats
        if self.tool_results:
            successful = len([r for r in self.tool_results if r.is_successful()])
            total = len(self.tool_results)
            self.metrics.tool_calls = total

        # Update status based on errors and results
        if not self.errors:
            if not self.tool_results or all(r.is_successful() for r in self.tool_results):
                self.status = ExecutionStatus.SUCCESS
        elif self.partial_failure_info and self.partial_failure_info.is_acceptable:
            self.status = ExecutionStatus.PARTIAL_SUCCESS
        else:
            self.status = ExecutionStatus.FAILED

    def get_summary(self) -> Dict[str, Any]:
        """Get summary of execution"""
        return {
            "report_id": self.report_id,
            "execution_id": self.execution_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "timestamp": self.timestamp.isoformat(),
            "duration_ms": self.metrics.duration_ms,
            "tool_calls": len(self.tool_results),
            "errors": len(self.errors),
            "warnings": len(self.warnings),
            "success_rate": self._calculate_success_rate(),
        }

    def _calculate_success_rate(self) -> float:
        """Calculate success rate percentage"""
        if not self.tool_results:
            return 0.0
        successful = len([r for r in self.tool_results if r.is_successful()])
        return (successful / len(self.tool_results)) * 100

    def get_critical_errors(self) -> List[ExecutionError]:
        """Get critical-level errors"""
        return [e for e in self.errors if e.severity == ErrorSeverity.CRITICAL]

    def get_recommendations(self) -> List[str]:
        """Get recommendations for user"""
        recommendations = []

        # Add partial failure recommendations
        if self.partial_failure_info:
            recommendations.extend(self.partial_failure_info.recommendations)

        # Add recovery suggestions from errors
        for error in self.errors:
            if error.get_recovery_suggestion():
                recommendations.append(error.get_recovery_suggestion())

        # Add timeout recommendations
        if self.metrics.duration_ms > 30000:
            recommendations.append(
                "İşlem çok uzun sürdü. Daha basit bir görev denemeyi veya sistem yükünü kontrol etmeyi düşünün. "
                "(Execution took very long. Consider trying a simpler task or checking system load.)"
            )

        return recommendations

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "report_id": self.report_id,
            "timestamp": self.timestamp.isoformat(),
            "execution_id": self.execution_id,
            "user_id": self.user_id,
            "task_id": self.task_id,
            "status": self.status.value,
            "summary": self.get_summary(),
            "metrics": self.metrics.to_dict(),
            "state": self.state.to_dict(),
            "tool_results": [r.to_dict() for r in self.tool_results],
            "errors": [e.to_dict() for e in self.errors],
            "warnings": self.warnings,
            "partial_failure_info": self.partial_failure_info.to_dict() if self.partial_failure_info else None,
            "recovery_taken": self.recovery_taken,
            "environment_info": self.environment_info,
            "recommendations": self.get_recommendations(),
            "user_feedback": self.user_feedback,
        }

    def to_json(self, indent: int = 2) -> str:
        """Convert to JSON string"""
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def to_markdown(self) -> str:
        """Convert to Markdown format"""
        lines = []

        lines.append(f"# Yürütme Raporu / Execution Report")
        lines.append(f"**Rapor ID:** {self.report_id}")
        lines.append(f"**Zaman:** {self.timestamp.isoformat()}")
        lines.append("")

        lines.append("## Özet / Summary")
        summary = self.get_summary()
        lines.append(f"- **Durum:** {summary['status']}")
        lines.append(f"- **Süre:** {summary['duration_ms']:.0f} ms")
        lines.append(f"- **Araç Çağrıları:** {summary['tool_calls']}")
        lines.append(f"- **Başarı Oranı:** {summary['success_rate']:.1f}%")
        lines.append("")

        if self.tool_results:
            lines.append("## Araç Sonuçları / Tool Results")
            for result in self.tool_results:
                lines.append(f"### {result.tool_name}")
                lines.append(f"- **Durum:** {result.status.value}")
                lines.append(f"- **Süre:** {result.metrics.duration_ms:.0f} ms")
                if result.error:
                    lines.append(f"- **Hata:** {result.error.message}")
                lines.append("")

        if self.errors:
            lines.append("## Hatalar / Errors")
            for error in self.errors:
                lines.append(f"### {error.code}")
                lines.append(f"- **Mesaj:** {error.message}")
                lines.append(f"- **Kategori:** {error.category.value}")
                lines.append(f"- **Önem:** {error.severity.value}")
                if error.suggestions:
                    lines.append(f"- **Öneriler:** {', '.join(error.suggestions)}")
                lines.append("")

        if self.warnings:
            lines.append("## Uyarılar / Warnings")
            for warning in self.warnings:
                lines.append(f"- {warning}")
            lines.append("")

        recommendations = self.get_recommendations()
        if recommendations:
            lines.append("## Öneriler / Recommendations")
            for rec in recommendations:
                lines.append(f"- {rec}")
            lines.append("")

        return "\n".join(lines)

    def save_to_file(self, filepath: Path, format: ReportFormat = ReportFormat.JSON) -> bool:
        """Save report to file"""
        try:
            if format == ReportFormat.JSON:
                content = self.to_json()
            elif format == ReportFormat.MARKDOWN:
                content = self.to_markdown()
            else:
                content = str(self.to_dict())

            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
            logger.info(f"Rapor kaydedildi: {filepath}")
            return True
        except Exception as e:
            logger.error(f"Rapor kaydedilemedi: {e}")
            return False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExecutionReport":
        """Create from dictionary"""
        report = cls()
        report.report_id = data.get("report_id", report.report_id)
        report.timestamp = datetime.fromisoformat(data.get("timestamp", report.timestamp.isoformat()))
        report.execution_id = data.get("execution_id", "")
        report.user_id = data.get("user_id")
        report.task_id = data.get("task_id", "")
        report.status = ExecutionStatus(data.get("status", "pending"))

        # Note: Full reconstruction would be more complex
        # This is a simplified version
        return report


class ExecutionReportBuilder:
    """Builder pattern for ExecutionReport creation"""

    def __init__(self, execution_id: str, task_id: str):
        self.report = ExecutionReport(execution_id=execution_id, task_id=task_id)

    def set_user(self, user_id: str) -> "ExecutionReportBuilder":
        """Set user ID"""
        self.report.user_id = user_id
        return self

    def add_environment_info(self, info: Dict[str, Any]) -> "ExecutionReportBuilder":
        """Add environment information"""
        self.report.environment_info.update(info)
        return self

    def add_tool_result(self, result: ToolExecutionResult) -> "ExecutionReportBuilder":
        """Add tool result"""
        self.report.add_tool_result(result)
        return self

    def add_error(self, error: ExecutionError) -> "ExecutionReportBuilder":
        """Add error"""
        self.report.add_error(error)
        return self

    def add_warning(self, message: str) -> "ExecutionReportBuilder":
        """Add warning"""
        self.report.add_warning(message)
        return self

    def set_partial_failure(self, info: PartialFailureInfo) -> "ExecutionReportBuilder":
        """Set partial failure info"""
        self.report.partial_failure_info = info
        return self

    def record_recovery(self, action: str) -> "ExecutionReportBuilder":
        """Record recovery action"""
        self.report.record_recovery(action)
        return self

    def set_status(self, status: ExecutionStatus) -> "ExecutionReportBuilder":
        """Set final status"""
        self.report.status = status
        return self

    def build(self) -> ExecutionReport:
        """Build final report"""
        self.report.finalize()
        return self.report
