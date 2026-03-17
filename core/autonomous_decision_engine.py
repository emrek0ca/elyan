"""
Autonomous Decision Engine - Risk-based decision making and self-improvement
"""

import logging
from typing import Dict, List, Optional, Tuple, Any
from enum import Enum
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)


class DecisionRisk(Enum):
    """Risk levels for decisions"""
    LOW = 0.2
    MEDIUM = 0.5
    HIGH = 0.8


@dataclass
class Decision:
    """A decision record"""

    decision_id: str
    context: Dict
    options: List[Dict]
    selected_option: str
    confidence: float
    risk_level: DecisionRisk
    outcome: Optional[str] = None
    success: Optional[bool] = None
    timestamp: str = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


class AutonomousDecisionEngine:
    """Makes autonomous decisions"""

    def __init__(self, learning_engine=None):
        self.learning_engine = learning_engine
        self.decisions: List[Decision] = []
        self.decision_accuracy = 0.0
        self.decision_speed = 0.0  # avg time per decision

    def make_decision(self, context: Dict, options: List[Dict],
                     preferences: Dict = None) -> Tuple[str, float]:
        """Make autonomous decision"""
        try:
            preferences = preferences or {}

            # Score options
            scored_options = []
            for option in options:
                score = self._score_option(option, context, preferences)
                scored_options.append((option.get("name", ""), score))

            # Select best option
            if scored_options:
                best_option = max(scored_options, key=lambda x: x[1])
                confidence = self._calculate_confidence(best_option[1], len(scored_options))
                risk = self._assess_risk(context, best_option)

                # Record decision
                decision = Decision(
                    decision_id=f"decision_{len(self.decisions)}",
                    context=context,
                    options=options,
                    selected_option=best_option[0],
                    confidence=confidence,
                    risk_level=risk
                )
                self.decisions.append(decision)

                logger.info(f"Decision made: {best_option[0]} (confidence={confidence:.1%})")
                return best_option[0], confidence

            return "none", 0.0

        except Exception as e:
            logger.error(f"Decision making failed: {e}")
            return "none", 0.0

    def _score_option(self, option: Dict, context: Dict, preferences: Dict) -> float:
        """Score an option"""
        score = 0.0

        # Base score
        if "score" in option:
            score += option["score"] * 0.5

        # Preference matching
        if "category" in option and "preferred_categories" in preferences:
            if option["category"] in preferences["preferred_categories"]:
                score += 0.5

        # Risk consideration
        if "risk" in option and preferences.get("risk_tolerance", 0.5) > 0.5:
            if option["risk"] == "low":
                score += 0.3
            elif option["risk"] == "high":
                score -= 0.2

        return score

    def _calculate_confidence(self, best_score: float, num_options: int) -> float:
        """Calculate confidence in decision"""
        base_confidence = min(best_score / 10.0, 1.0)

        # Adjust for option count
        if num_options > 5:
            base_confidence *= 0.8

        return max(0.0, min(1.0, base_confidence))

    def _assess_risk(self, context: Dict, option: Tuple) -> DecisionRisk:
        """Assess risk level of decision"""
        # Simplified risk assessment
        if "risk_factors" in context:
            if len(context["risk_factors"]) > 3:
                return DecisionRisk.HIGH
            elif len(context["risk_factors"]) > 1:
                return DecisionRisk.MEDIUM

        return DecisionRisk.LOW

    def record_outcome(self, decision_id: str, outcome: str, success: bool):
        """Record outcome of decision"""
        try:
            for decision in self.decisions:
                if decision.decision_id == decision_id:
                    decision.outcome = outcome
                    decision.success = success

                    # Update accuracy
                    successful = sum(1 for d in self.decisions if d.success)
                    total = sum(1 for d in self.decisions if d.success is not None)
                    if total > 0:
                        self.decision_accuracy = successful / total

                    logger.info(f"Outcome recorded. Current accuracy: {self.decision_accuracy:.1%}")
                    return True

            return False

        except Exception as e:
            logger.error(f"Failed to record outcome: {e}")
            return False

    def self_improve(self) -> Dict:
        """Learn from past decisions"""
        try:
            improvements = {
                "accuracy": self.decision_accuracy,
                "decisions_made": len(self.decisions),
                "successful_decisions": sum(1 for d in self.decisions if d.success),
                "recommendations": []
            }

            # Generate recommendations
            if self.decision_accuracy < 0.7:
                improvements["recommendations"].append("Increase decision confidence threshold")
            if self.decision_accuracy > 0.9:
                improvements["recommendations"].append("Can increase risk tolerance")

            return improvements

        except Exception as e:
            logger.error(f"Failed to self-improve: {e}")
            return {"error": str(e)}

    def get_decision_stats(self) -> Dict:
        """Get decision statistics"""
        if not self.decisions:
            return {"status": "No decisions made yet"}

        successful = [d for d in self.decisions if d.success]
        high_risk = [d for d in self.decisions if d.risk_level == DecisionRisk.HIGH]

        return {
            "total_decisions": len(self.decisions),
            "successful": len(successful),
            "accuracy": self.decision_accuracy,
            "high_risk_decisions": len(high_risk),
            "average_confidence": sum(d.confidence for d in self.decisions) / len(self.decisions)
        }
