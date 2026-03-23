"""
Adaptive Response Engine

Provides intelligent suggestions, adaptive responses, and context-aware decisions
based on user patterns, history, and preferences.
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict

from core.observability.logger import get_structured_logger
from core.user_preferences import get_preference_manager

slog = get_structured_logger("adaptive_engine")


class AdaptiveEngine:
    """Learns from user behavior and provides intelligent suggestions."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize adaptive engine.

        Args:
            storage_path: Path to store learning data
        """
        if storage_path is None:
            storage_path = os.path.expanduser("~/.elyan/adaptive")
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self.pref_manager = get_preference_manager()

    def get_adaptive_response(
        self,
        intent: str,
        context: Dict[str, Any],
        available_actions: List[str]
    ) -> Dict[str, Any]:
        """Get adaptive response recommendation based on user patterns.

        Args:
            intent: User's stated intent
            context: Current context (prior runs, session data)
            available_actions: List of possible actions

        Returns:
            Dict with recommended action, confidence, and reasoning
        """
        # Analyze user's historical preference for this intent type
        intent_success = self.pref_manager.get_intent_success_rate(intent)

        # Get most frequently used actions for this intent
        top_actions = self.pref_manager.get_top_actions_for_intent(intent, top_n=3)

        # Score each action based on history and context
        scored_actions = []
        for action in available_actions:
            score = self._score_action(action, intent, context, top_actions)
            scored_actions.append((action, score))

        # Sort by score
        scored_actions.sort(key=lambda x: x[1], reverse=True)

        if not scored_actions:
            return {"success": False, "error": "No actions to score"}

        recommended_action, confidence = scored_actions[0]

        return {
            "success": True,
            "recommended_action": recommended_action,
            "confidence": min(confidence, 1.0),
            "alternatives": [a[0] for a, _ in scored_actions[1:3]],
            "reasoning": self._generate_reasoning(intent, recommended_action, intent_success)
        }

    def _score_action(
        self,
        action: str,
        intent: str,
        context: Dict[str, Any],
        top_actions: List[str]
    ) -> float:
        """Score an action based on various factors."""
        score = 0.5  # Base score

        # Boost if it's a top action for this intent
        if action in top_actions:
            index = top_actions.index(action)
            score += (3 - index) * 0.2  # 0.6, 0.4, 0.2

        # Boost if similar context has led to this action before
        if context.get("session_count", 0) > 0:
            similarity = self._calculate_context_similarity(action, context)
            score += similarity * 0.3

        # Factor in action success rate
        success_rate = self.pref_manager.command_frequency.get(action, {}).get("success_rate", 0.5)
        score += success_rate * 0.2

        return score

    def _calculate_context_similarity(self, action: str, context: Dict[str, Any]) -> float:
        """Calculate similarity between current context and past successful contexts."""
        # Load historical contexts for this action
        try:
            context_file = self.storage_path / f"contexts_{action}.json"
            if not context_file.exists():
                return 0.0

            with open(context_file, "r") as f:
                historical_contexts = json.load(f)

            # Simple similarity: compare keys that match
            current_keys = set(context.keys())
            similarities = []

            for hist_context in historical_contexts[-10:]:  # Last 10 contexts
                hist_keys = set(hist_context.keys())
                overlap = len(current_keys & hist_keys) / max(len(current_keys), len(hist_keys), 1)
                similarities.append(overlap)

            return sum(similarities) / len(similarities) if similarities else 0.0
        except Exception:
            return 0.0

    def _generate_reasoning(self, intent: str, action: str, success_rate: float) -> str:
        """Generate human-readable reasoning for the recommendation."""
        if success_rate > 0.8:
            return f"Action '{action}' has {success_rate*100:.0f}% success rate for '{intent}' intent"
        elif success_rate > 0.5:
            return f"Action '{action}' is recommended based on your usage patterns"
        else:
            return f"Action '{action}' is available for this '{intent}' intent"

    def get_smart_suggestions(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Get proactive suggestions based on current context.

        Returns:
            List of suggested actions with reasoning
        """
        suggestions = []

        # Suggestion 1: Frequently used commands in similar context
        if context.get("time_of_day"):
            time_suggestions = self._suggest_by_time_of_day(context.get("time_of_day"))
            suggestions.extend(time_suggestions)

        # Suggestion 2: Next likely action in sequence
        if context.get("last_action"):
            next_action = self._predict_next_action(context.get("last_action"))
            if next_action:
                suggestions.append({
                    "action": next_action["action"],
                    "reason": "Frequently follows your last action",
                    "confidence": next_action["confidence"]
                })

        # Suggestion 3: Overdue maintenance actions
        maintenance = self._suggest_maintenance_actions()
        suggestions.extend(maintenance)

        # Sort by confidence
        suggestions.sort(key=lambda x: x.get("confidence", 0), reverse=True)

        return suggestions[:3]  # Top 3 suggestions

    def _suggest_by_time_of_day(self, time_of_day: str) -> List[Dict[str, Any]]:
        """Suggest actions based on time of day patterns."""
        try:
            patterns_file = self.storage_path / "time_patterns.json"
            if not patterns_file.exists():
                return []

            with open(patterns_file, "r") as f:
                patterns = json.load(f)

            time_actions = patterns.get(time_of_day, [])
            return [
                {
                    "action": action["name"],
                    "reason": f"Usually done in the {time_of_day}",
                    "confidence": action.get("frequency", 0.5)
                }
                for action in time_actions[:2]
            ]
        except Exception:
            return []

    def _predict_next_action(self, last_action: str) -> Optional[Dict[str, Any]]:
        """Predict the next action in a sequence."""
        try:
            sequence_file = self.storage_path / "action_sequences.json"
            if not sequence_file.exists():
                return None

            with open(sequence_file, "r") as f:
                sequences = json.load(f)

            next_actions = sequences.get(last_action, [])
            if next_actions:
                # Return most common next action
                next_actions.sort(key=lambda x: x["count"], reverse=True)
                return {
                    "action": next_actions[0]["action"],
                    "confidence": min(next_actions[0]["count"] / 10, 1.0)
                }
            return None
        except Exception:
            return None

    def _suggest_maintenance_actions(self) -> List[Dict[str, Any]]:
        """Suggest maintenance or health-check actions."""
        suggestions = []

        # Check if health check is overdue
        try:
            last_health_check_file = self.storage_path / "last_health_check.json"
            if last_health_check_file.exists():
                with open(last_health_check_file, "r") as f:
                    data = json.load(f)
                    last_check = data.get("timestamp", 0)
                    now = datetime.now().timestamp()
                    if now - last_check > 86400:  # More than 24 hours
                        suggestions.append({
                            "action": "health_check",
                            "reason": "System health check is overdue",
                            "confidence": 0.7
                        })
        except Exception:
            pass

        return suggestions

    def learn_from_interaction(
        self,
        intent: str,
        action: str,
        success: bool,
        context: Dict[str, Any],
        duration: float = 0.0
    ) -> None:
        """Learn from user interaction results.

        Args:
            intent: The intent that was executed
            action: The action that was taken
            success: Whether the action succeeded
            context: Context of the action
            duration: How long the action took
        """
        try:
            # Update preference manager
            self.pref_manager.record_intent_result(intent, action, success)

            # Store context for this action
            context_file = self.storage_path / f"contexts_{action}.json"
            contexts = []
            if context_file.exists():
                with open(context_file, "r") as f:
                    contexts = json.load(f)

            context["success"] = success
            context["timestamp"] = datetime.now().isoformat()
            context["duration"] = duration
            contexts.append(context)
            contexts = contexts[-100:]  # Keep last 100 contexts

            with open(context_file, "w") as f:
                json.dump(contexts, f, indent=2)

            # Update action sequences
            if context.get("last_action"):
                self._update_action_sequence(context.get("last_action"), action)

            # Update time patterns
            time_of_day = self._get_time_of_day()
            self._update_time_pattern(time_of_day, action, success)

            slog.log_event("adaptive_learning", {
                "intent": intent,
                "action": action,
                "success": success,
                "duration": duration
            })
        except Exception as e:
            slog.log_event("adaptive_learning_error", {
                "error": str(e)
            }, level="warning")

    def _update_action_sequence(self, from_action: str, to_action: str) -> None:
        """Update action sequence patterns."""
        try:
            sequence_file = self.storage_path / "action_sequences.json"
            sequences = {}
            if sequence_file.exists():
                with open(sequence_file, "r") as f:
                    sequences = json.load(f)

            if from_action not in sequences:
                sequences[from_action] = []

            # Find or create the sequence entry
            next_action = None
            for entry in sequences[from_action]:
                if entry["action"] == to_action:
                    entry["count"] += 1
                    next_action = entry
                    break

            if not next_action:
                sequences[from_action].append({
                    "action": to_action,
                    "count": 1
                })

            with open(sequence_file, "w") as f:
                json.dump(sequences, f, indent=2)
        except Exception:
            pass

    def _update_time_pattern(self, time_of_day: str, action: str, success: bool) -> None:
        """Update patterns for actions at specific times."""
        try:
            patterns_file = self.storage_path / "time_patterns.json"
            patterns = {}
            if patterns_file.exists():
                with open(patterns_file, "r") as f:
                    patterns = json.load(f)

            if time_of_day not in patterns:
                patterns[time_of_day] = []

            # Find or update action in this time pattern
            action_found = False
            for entry in patterns[time_of_day]:
                if entry["name"] == action:
                    entry["count"] += 1 if success else 0
                    entry["frequency"] = entry["count"] / max(entry["count"] + 1, 1)
                    action_found = True
                    break

            if not action_found:
                patterns[time_of_day].append({
                    "name": action,
                    "count": 1 if success else 0,
                    "frequency": 1.0 if success else 0.0
                })

            with open(patterns_file, "w") as f:
                json.dump(patterns, f, indent=2)
        except Exception:
            pass

    @staticmethod
    def _get_time_of_day() -> str:
        """Get time of day category."""
        hour = datetime.now().hour
        if 5 <= hour < 12:
            return "morning"
        elif 12 <= hour < 17:
            return "afternoon"
        elif 17 <= hour < 21:
            return "evening"
        else:
            return "night"


# Global instance
_adaptive_engine: Optional[AdaptiveEngine] = None


def get_adaptive_engine(storage_path: Optional[str] = None) -> AdaptiveEngine:
    """Get or create adaptive engine singleton."""
    global _adaptive_engine
    if _adaptive_engine is None:
        _adaptive_engine = AdaptiveEngine(storage_path)
    return _adaptive_engine
