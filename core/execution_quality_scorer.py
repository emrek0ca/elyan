"""
core/execution_quality_scorer.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Execution Quality Scoring (~350 lines)
Score execution quality, calculate confidence, detect anomalies.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Any, Tuple
import time
import statistics
from utils.logger import get_logger

logger = get_logger("quality_scorer")


@dataclass
class ExecutionMetrics:
    """Metrics for execution quality."""
    task_id: str
    success: bool
    duration_ms: float
    resource_usage_mb: float = 0.0
    error_count: int = 0
    warning_count: int = 0
    retries: int = 0
    checkpoints_hit: int = 0
    fallbacks_used: int = 0


@dataclass
class QualityScore:
    """Quality score for execution."""
    task_id: str
    overall_score: float  # 0.0-1.0
    success_score: float
    performance_score: float
    reliability_score: float
    resource_score: float
    completeness_score: float
    confidence: float
    anomalies: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class PerformanceAnalyzer:
    """Analyze execution performance."""

    def __init__(self):
        self.baseline_duration_ms = 1000  # Baseline for comparison
        self.performance_thresholds = {
            "excellent": 0.5,  # 50% of baseline
            "good": 1.0,  # 100% of baseline
            "acceptable": 1.5,  # 150% of baseline
            "poor": 2.0,  # 200% of baseline
        }

    def score_performance(self, duration_ms: float, baseline: float = None) -> float:
        """Score execution performance based on duration."""
        baseline = baseline or self.baseline_duration_ms
        ratio = duration_ms / baseline

        if ratio <= self.performance_thresholds["excellent"]:
            return 1.0
        elif ratio <= self.performance_thresholds["good"]:
            return 0.8
        elif ratio <= self.performance_thresholds["acceptable"]:
            return 0.6
        elif ratio <= self.performance_thresholds["poor"]:
            return 0.4
        else:
            return 0.2

    def detect_performance_anomalies(
        self,
        current_duration: float,
        historical_durations: List[float]
    ) -> List[str]:
        """Detect performance anomalies using statistics."""
        anomalies = []

        if not historical_durations:
            return anomalies

        mean = statistics.mean(historical_durations)
        stdev = statistics.stdev(historical_durations) if len(historical_durations) > 1 else 0

        # Z-score analysis
        if stdev > 0:
            z_score = (current_duration - mean) / stdev
            if z_score > 2.5:
                anomalies.append(f"Execution significantly slower than baseline (z={z_score:.2f})")
            elif z_score < -2.5:
                anomalies.append(f"Execution significantly faster than baseline (z={z_score:.2f})")

        # Consistency check
        if current_duration > mean * 2:
            anomalies.append("Execution took 2x longer than average")

        return anomalies


class ReliabilityAnalyzer:
    """Analyze execution reliability."""

    def __init__(self):
        self.reliability_weights = {
            "success_rate": 0.5,
            "retry_count": 0.2,
            "checkpoint_effectiveness": 0.2,
            "error_recovery": 0.1,
        }

    def score_reliability(self, metrics: ExecutionMetrics, historical_success_rate: float = 1.0) -> float:
        """Score execution reliability."""
        scores = {}

        # Success
        scores["success_rate"] = 1.0 if metrics.success else 0.0

        # Retries (fewer is better)
        scores["retry_count"] = 1.0 - min(1.0, metrics.retries / 5.0)

        # Checkpoint effectiveness (more checkpoints = better reliability)
        scores["checkpoint_effectiveness"] = min(1.0, metrics.checkpoints_hit / 3.0)

        # Error recovery
        scores["error_recovery"] = 1.0 - min(1.0, metrics.error_count / 5.0)

        # Weighted average
        overall = sum(
            scores.get(key, 0.0) * weight
            for key, weight in self.reliability_weights.items()
        )

        return overall

    def detect_reliability_anomalies(self, metrics: ExecutionMetrics) -> List[str]:
        """Detect reliability issues."""
        anomalies = []

        if metrics.error_count > 3:
            anomalies.append(f"High error count: {metrics.error_count}")

        if metrics.retries > 2:
            anomalies.append(f"Multiple retries needed: {metrics.retries}")

        if metrics.warning_count > 5:
            anomalies.append(f"Many warnings: {metrics.warning_count}")

        if not metrics.success:
            anomalies.append("Task execution failed")

        return anomalies


class ResourceAnalyzer:
    """Analyze resource usage."""

    def __init__(self):
        self.resource_limits = {
            "memory_mb": 512,
            "time_seconds": 300,
            "retries": 3,
        }

    def score_resource_usage(self, metrics: ExecutionMetrics) -> float:
        """Score resource usage efficiency."""
        score = 1.0

        # Memory usage
        if metrics.resource_usage_mb > self.resource_limits["memory_mb"]:
            score -= min(0.4, (metrics.resource_usage_mb - self.resource_limits["memory_mb"]) / 100)

        # Time usage
        if metrics.duration_ms / 1000 > self.resource_limits["time_seconds"]:
            score -= min(0.3, (metrics.duration_ms / 1000 - self.resource_limits["time_seconds"]) / 100)

        # Retries
        if metrics.retries > self.resource_limits["retries"]:
            score -= min(0.2, (metrics.retries - self.resource_limits["retries"]) / 5)

        return max(0.0, score)

    def detect_resource_anomalies(self, metrics: ExecutionMetrics) -> List[str]:
        """Detect resource usage anomalies."""
        anomalies = []

        if metrics.resource_usage_mb > self.resource_limits["memory_mb"] * 1.5:
            anomalies.append(f"High memory usage: {metrics.resource_usage_mb:.1f}MB")

        if metrics.duration_ms / 1000 > self.resource_limits["time_seconds"]:
            anomalies.append(f"Execution timeout: {metrics.duration_ms/1000:.1f}s")

        if metrics.retries > self.resource_limits["retries"]:
            anomalies.append(f"Excessive retries: {metrics.retries}")

        return anomalies


class CompletenessAnalyzer:
    """Analyze result completeness."""

    def __init__(self):
        pass

    def score_completeness(self, result: Any, expected_fields: List[str]) -> float:
        """Score result completeness."""
        if result is None:
            return 0.0

        if isinstance(result, dict):
            provided_fields = set(result.keys())
            expected = set(expected_fields) if expected_fields else set()
            if not expected:
                return 1.0

            coverage = len(provided_fields & expected) / len(expected)
            return coverage
        else:
            # Non-dict results are considered complete if present
            return 1.0

    def detect_completeness_issues(self, result: Any, expected_fields: List[str]) -> List[str]:
        """Detect completeness issues."""
        issues = []

        if result is None:
            issues.append("Result is empty")
        elif isinstance(result, dict) and expected_fields:
            provided = set(result.keys())
            expected = set(expected_fields)
            missing = expected - provided

            if missing:
                issues.append(f"Missing fields: {missing}")

            for field in expected:
                if field in result and result[field] in (None, "", []):
                    issues.append(f"Field '{field}' is empty")

        return issues


class ExecutionQualityScorer:
    """Main quality scoring engine."""

    def __init__(self):
        self.performance_analyzer = PerformanceAnalyzer()
        self.reliability_analyzer = ReliabilityAnalyzer()
        self.resource_analyzer = ResourceAnalyzer()
        self.completeness_analyzer = CompletenessAnalyzer()
        self.history: Dict[str, List[QualityScore]] = {}

    def score_execution(
        self,
        metrics: ExecutionMetrics,
        result: Any = None,
        expected_fields: List[str] = None,
        historical_data: Dict[str, Any] = None,
    ) -> QualityScore:
        """Score overall execution quality."""
        historical_data = historical_data or {}

        # Get individual scores
        success_score = 1.0 if metrics.success else 0.0

        performance_score = self.performance_analyzer.score_performance(
            metrics.duration_ms,
            historical_data.get("baseline_duration_ms")
        )

        reliability_score = self.reliability_analyzer.score_reliability(
            metrics,
            historical_data.get("success_rate", 1.0)
        )

        resource_score = self.resource_analyzer.score_resource_usage(metrics)

        completeness_score = self.completeness_analyzer.score_completeness(
            result,
            expected_fields or []
        )

        # Detect anomalies
        anomalies = []
        anomalies.extend(self.performance_analyzer.detect_performance_anomalies(
            metrics.duration_ms,
            historical_data.get("historical_durations", [])
        ))
        anomalies.extend(self.reliability_analyzer.detect_reliability_anomalies(metrics))
        anomalies.extend(self.resource_analyzer.detect_resource_anomalies(metrics))
        anomalies.extend(self.completeness_analyzer.detect_completeness_issues(result, expected_fields or []))

        # Generate suggestions
        suggestions = self._generate_suggestions(
            success_score, performance_score, reliability_score, resource_score, completeness_score, anomalies
        )

        # Calculate overall score (weighted average)
        weights = {
            "success": 0.3,
            "performance": 0.2,
            "reliability": 0.2,
            "resource": 0.15,
            "completeness": 0.15,
        }

        overall_score = (
            success_score * weights["success"] +
            performance_score * weights["performance"] +
            reliability_score * weights["reliability"] +
            resource_score * weights["resource"] +
            completeness_score * weights["completeness"]
        )

        # Calculate confidence
        confidence = self._calculate_confidence(
            success_score, reliability_score, completeness_score
        )

        score = QualityScore(
            task_id=metrics.task_id,
            overall_score=overall_score,
            success_score=success_score,
            performance_score=performance_score,
            reliability_score=reliability_score,
            resource_score=resource_score,
            completeness_score=completeness_score,
            confidence=confidence,
            anomalies=anomalies,
            suggestions=suggestions,
        )

        # Store in history
        if metrics.task_id not in self.history:
            self.history[metrics.task_id] = []
        self.history[metrics.task_id].append(score)

        logger.info(f"Quality score for {metrics.task_id}: {overall_score:.2f} (confidence: {confidence:.2f})")

        return score

    def _generate_suggestions(
        self,
        success: float,
        performance: float,
        reliability: float,
        resource: float,
        completeness: float,
        anomalies: List[str]
    ) -> List[str]:
        """Generate improvement suggestions."""
        suggestions = []

        if success < 1.0:
            suggestions.append("Address execution failures to improve reliability")

        if performance < 0.6:
            suggestions.append("Optimize execution performance - consider parallel processing or caching")

        if reliability < 0.6:
            suggestions.append("Improve reliability - add better error handling and recovery")

        if resource > 0.5:
            suggestions.append("Reduce resource usage - optimize memory and CPU")

        if completeness < 0.8:
            suggestions.append("Ensure result completeness - verify all required fields are present")

        if anomalies:
            suggestions.append(f"Address {len(anomalies)} detected anomalies")

        return suggestions

    def _calculate_confidence(self, success: float, reliability: float, completeness: float) -> float:
        """Calculate overall confidence in the result."""
        # Confidence is high when success, reliability, and completeness are all high
        weights = {"success": 0.4, "reliability": 0.3, "completeness": 0.3}
        return (
            success * weights["success"] +
            reliability * weights["reliability"] +
            completeness * weights["completeness"]
        )

    def get_historical_metrics(self, task_id: str) -> Dict[str, float]:
        """Get historical metrics for a task."""
        if task_id not in self.history:
            return {}

        scores = self.history[task_id]
        if not scores:
            return {}

        return {
            "avg_overall_score": sum(s.overall_score for s in scores) / len(scores),
            "avg_success_rate": sum(s.success_score for s in scores) / len(scores),
            "avg_reliability": sum(s.reliability_score for s in scores) / len(scores),
            "avg_performance": sum(s.performance_score for s in scores) / len(scores),
            "execution_count": len(scores),
        }
