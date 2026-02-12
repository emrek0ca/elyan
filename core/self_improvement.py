"""
Self-Learning & Continuous Improvement Engine
Automatic optimization, feedback integration, adaptive learning
"""

import time
import json
import statistics
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from enum import Enum

from utils.logger import get_logger
from config.settings import HOME_DIR

logger = get_logger("self_improvement")


class ImprovementArea(Enum):
    """Areas that can be improved"""
    PATTERN_RECOGNITION = "pattern_recognition"
    TOOL_SELECTION = "tool_selection"
    PARAMETER_OPTIMIZATION = "parameter_optimization"
    ERROR_HANDLING = "error_handling"
    RESPONSE_QUALITY = "response_quality"
    PERFORMANCE = "performance"


@dataclass
class FeedbackEntry:
    """User feedback on system performance"""
    timestamp: float
    user_id: str
    interaction_id: str
    rating: int  # 1-5
    feedback_text: Optional[str]
    improvement_areas: List[str]


@dataclass
class OptimizationRule:
    """Learned optimization rule"""
    rule_id: str
    area: ImprovementArea
    condition: str
    action: str
    confidence: float
    success_count: int
    failure_count: int
    created_at: float
    last_applied: Optional[float] = None


class SelfImprovement:
    """
    Self-Learning & Continuous Improvement Engine
    - Learns from successes and failures
    - Optimizes patterns automatically
    - Integrates user feedback
    - Adapts behavior over time
    - Tracks improvement metrics
    """

    def __init__(self):
        self.feedback_history: List[FeedbackEntry] = []
        self.optimization_rules: Dict[str, OptimizationRule] = {}
        self.improvement_metrics: Dict[str, List[float]] = defaultdict(list)
        self.learning_rate = 0.1  # How quickly to adapt

        # Success/failure tracking
        self.tool_success_rates: Dict[str, Dict[str, int]] = defaultdict(
            lambda: {"success": 0, "failure": 0}
        )

        # Parameter optimization tracking
        self.parameter_effectiveness: Dict[str, Dict[str, List[float]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Error pattern tracking
        self.error_patterns: List[Dict[str, Any]] = []

        # Load persisted rules
        self._load_rules()

        logger.info("Self-Improvement Engine initialized")

    def record_interaction_outcome(
        self,
        tool_name: str,
        params: Dict[str, Any],
        success: bool,
        duration_ms: float,
        error: Optional[str] = None
    ):
        """Record outcome of an interaction for learning"""
        # Update success rates
        if success:
            self.tool_success_rates[tool_name]["success"] += 1
        else:
            self.tool_success_rates[tool_name]["failure"] += 1

        # Track performance
        self.improvement_metrics[f"{tool_name}_duration"].append(duration_ms)

        # Track parameter effectiveness
        for param, value in params.items():
            score = 1.0 if success else 0.0
            self.parameter_effectiveness[tool_name][param].append(score)

        # Record error patterns
        if not success and error:
            self.error_patterns.append({
                "tool": tool_name,
                "params": params,
                "error": error,
                "timestamp": time.time()
            })

            # Keep only recent errors
            if len(self.error_patterns) > 100:
                self.error_patterns = self.error_patterns[-100:]

        # Try to learn new optimization rules
        self._learn_from_outcome(tool_name, params, success, error)

    def _learn_from_outcome(
        self,
        tool_name: str,
        params: Dict[str, Any],
        success: bool,
        error: Optional[str]
    ):
        """Learn optimization rules from outcomes"""
        # Learn from failures
        if not success and error:
            # Check if this error has occurred multiple times
            similar_errors = [
                e for e in self.error_patterns
                if e["tool"] == tool_name and error in e["error"]
            ]

            if len(similar_errors) >= 3:
                # Create an optimization rule
                rule = OptimizationRule(
                    rule_id=f"auto_rule_{len(self.optimization_rules)}",
                    area=ImprovementArea.ERROR_HANDLING,
                    condition=f"tool={tool_name} AND error_contains={error[:50]}",
                    action=f"suggest_alternative_tool",
                    confidence=0.6,
                    success_count=0,
                    failure_count=len(similar_errors),
                    created_at=time.time()
                )

                self.optimization_rules[rule.rule_id] = rule
                logger.info(f"Learned new error handling rule: {rule.rule_id}")

        # Learn from successes
        if success:
            # Find parameters that correlate with success
            for param, value in params.items():
                effectiveness = self.parameter_effectiveness[tool_name][param]
                if len(effectiveness) >= 5:
                    avg = statistics.mean(effectiveness[-10:])
                    if avg > 0.8:  # High success rate
                        # Create optimization rule
                        rule = OptimizationRule(
                            rule_id=f"param_opt_{tool_name}_{param}",
                            area=ImprovementArea.PARAMETER_OPTIMIZATION,
                            condition=f"tool={tool_name}",
                            action=f"prefer_param_{param}={value}",
                            confidence=avg,
                            success_count=int(sum(effectiveness)),
                            failure_count=len(effectiveness) - int(sum(effectiveness)),
                            created_at=time.time()
                        )

                        self.optimization_rules[rule.rule_id] = rule

    def add_feedback(
        self,
        user_id: str,
        interaction_id: str,
        rating: int,
        feedback_text: Optional[str] = None,
        improvement_areas: Optional[List[str]] = None
    ):
        """Add user feedback"""
        feedback = FeedbackEntry(
            timestamp=time.time(),
            user_id=user_id,
            interaction_id=interaction_id,
            rating=rating,
            feedback_text=feedback_text,
            improvement_areas=improvement_areas or []
        )

        self.feedback_history.append(feedback)

        # Analyze feedback for improvement
        if rating <= 2:  # Poor rating
            logger.warning(f"Negative feedback received: {feedback_text}")
            # Could trigger specific improvements based on feedback_text analysis

        # Keep only recent feedback
        if len(self.feedback_history) > 1000:
            self.feedback_history = self.feedback_history[-1000:]

    def get_tool_recommendations(self, intent: str) -> List[Tuple[str, float]]:
        """Get recommended tools based on learned success rates"""
        # Calculate tool scores based on success rate
        scores = []

        for tool, stats in self.tool_success_rates.items():
            total = stats["success"] + stats["failure"]
            if total > 0:
                success_rate = stats["success"] / total

                # Boost score if recently successful
                recent_metric = self.improvement_metrics.get(f"{tool}_duration", [])
                if recent_metric:
                    avg_duration = statistics.mean(recent_metric[-10:])
                    # Prefer faster tools
                    speed_factor = max(0.5, 1.0 - (avg_duration / 10000))
                    score = success_rate * speed_factor
                else:
                    score = success_rate

                scores.append((tool, score))

        # Sort by score
        scores.sort(key=lambda x: x[1], reverse=True)
        return scores[:5]

    def optimize_parameters(
        self,
        tool_name: str,
        base_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Optimize parameters based on learned effectiveness"""
        optimized = base_params.copy()

        # Apply learned optimization rules
        for rule in self.optimization_rules.values():
            if (rule.area == ImprovementArea.PARAMETER_OPTIMIZATION and
                f"tool={tool_name}" in rule.condition):

                # Parse action (e.g., "prefer_param_timeout=30")
                if "prefer_param_" in rule.action:
                    parts = rule.action.replace("prefer_param_", "").split("=")
                    if len(parts) == 2:
                        param_name, param_value = parts
                        # Only apply if confidence is high
                        if rule.confidence > 0.75:
                            optimized[param_name] = param_value
                            logger.debug(f"Applied optimization rule: {rule.rule_id}")

        return optimized

    def get_alternative_tool(self, failed_tool: str) -> Optional[str]:
        """Suggest alternative tool if one keeps failing"""
        # Check for error handling rules
        for rule in self.optimization_rules.values():
            if (rule.area == ImprovementArea.ERROR_HANDLING and
                f"tool={failed_tool}" in rule.condition):

                if "suggest_alternative_tool" in rule.action:
                    # Find similar successful tool
                    similar_tools = [
                        t for t, stats in self.tool_success_rates.items()
                        if t != failed_tool and stats["success"] > stats["failure"]
                    ]

                    if similar_tools:
                        # Return most successful alternative
                        best = max(
                            similar_tools,
                            key=lambda t: self.tool_success_rates[t]["success"]
                        )
                        return best

        return None

    def analyze_performance_trends(self) -> Dict[str, Any]:
        """Analyze performance trends over time"""
        trends = {}

        for metric_name, values in self.improvement_metrics.items():
            if len(values) < 10:
                continue

            # Split into old and new
            mid = len(values) // 2
            old_values = values[:mid]
            new_values = values[mid:]

            old_avg = statistics.mean(old_values)
            new_avg = statistics.mean(new_values)

            improvement = ((old_avg - new_avg) / old_avg * 100) if old_avg > 0 else 0

            trends[metric_name] = {
                "old_avg": old_avg,
                "new_avg": new_avg,
                "improvement_percent": improvement,
                "trend": "improving" if improvement > 5 else "stable" if improvement > -5 else "degrading"
            }

        return trends

    def get_improvement_recommendations(self) -> List[str]:
        """Get recommendations for improvement"""
        recommendations = []

        # Check success rates
        for tool, stats in self.tool_success_rates.items():
            total = stats["success"] + stats["failure"]
            if total >= 10:
                success_rate = stats["success"] / total
                if success_rate < 0.5:
                    recommendations.append(
                        f"Tool '{tool}' has low success rate ({success_rate:.0%}). "
                        f"Consider reviewing parameters or implementation."
                    )

        # Check feedback
        if len(self.feedback_history) >= 10:
            recent_ratings = [f.rating for f in self.feedback_history[-20:]]
            avg_rating = statistics.mean(recent_ratings)
            if avg_rating < 3:
                recommendations.append(
                    f"Recent user satisfaction is low ({avg_rating:.1f}/5). "
                    f"Review common feedback themes."
                )

        # Check error patterns
        if len(self.error_patterns) >= 10:
            error_types = Counter([e["error"][:50] for e in self.error_patterns[-50:]])
            most_common = error_types.most_common(3)
            for error, count in most_common:
                if count >= 5:
                    recommendations.append(
                        f"Recurring error '{error}' ({count} times). "
                        f"Implement specific handling."
                    )

        return recommendations

    def _save_rules(self):
        """Persist optimization rules"""
        try:
            rules_file = HOME_DIR / ".wiqo" / "optimization_rules.json"
            rules_file.parent.mkdir(parents=True, exist_ok=True)

            rules_data = {
                rule_id: {
                    "area": rule.area.value,
                    "condition": rule.condition,
                    "action": rule.action,
                    "confidence": rule.confidence,
                    "success_count": rule.success_count,
                    "failure_count": rule.failure_count,
                    "created_at": rule.created_at
                }
                for rule_id, rule in self.optimization_rules.items()
            }

            with open(rules_file, "w") as f:
                json.dump(rules_data, f, indent=2)

            logger.debug(f"Saved {len(rules_data)} optimization rules")

        except Exception as e:
            logger.error(f"Failed to save rules: {e}")

    def _load_rules(self):
        """Load persisted optimization rules"""
        try:
            rules_file = HOME_DIR / ".wiqo" / "optimization_rules.json"
            if not rules_file.exists():
                return

            with open(rules_file, "r") as f:
                rules_data = json.load(f)

            for rule_id, data in rules_data.items():
                rule = OptimizationRule(
                    rule_id=rule_id,
                    area=ImprovementArea(data["area"]),
                    condition=data["condition"],
                    action=data["action"],
                    confidence=data["confidence"],
                    success_count=data["success_count"],
                    failure_count=data["failure_count"],
                    created_at=data["created_at"]
                )
                self.optimization_rules[rule_id] = rule

            logger.info(f"Loaded {len(rules_data)} optimization rules")

        except Exception as e:
            logger.error(f"Failed to load rules: {e}")

    def get_summary(self) -> Dict[str, Any]:
        """Get self-improvement summary"""
        # Calculate overall success rate
        total_success = sum(stats["success"] for stats in self.tool_success_rates.values())
        total_failure = sum(stats["failure"] for stats in self.tool_success_rates.values())
        total_interactions = total_success + total_failure
        overall_success_rate = (total_success / total_interactions * 100) if total_interactions > 0 else 0

        # Average user rating
        avg_rating = statistics.mean([f.rating for f in self.feedback_history]) if self.feedback_history else 0

        return {
            "total_interactions": total_interactions,
            "overall_success_rate": f"{overall_success_rate:.1f}%",
            "optimization_rules": len(self.optimization_rules),
            "tracked_tools": len(self.tool_success_rates),
            "feedback_entries": len(self.feedback_history),
            "average_rating": f"{avg_rating:.1f}/5" if avg_rating > 0 else "N/A",
            "error_patterns_learned": len(set(e["error"][:50] for e in self.error_patterns))
        }


# Global instance
_self_improvement: Optional[SelfImprovement] = None


def get_self_improvement() -> SelfImprovement:
    """Get or create global self-improvement instance"""
    global _self_improvement
    if _self_improvement is None:
        _self_improvement = SelfImprovement()
    return _self_improvement
