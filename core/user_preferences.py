"""
User Preference Learning System

Tracks and learns user patterns:
- Command frequency and preferences
- Approval decision patterns
- Response format preferences
- Intent success rates
- Session-level continuity
"""

import json
import os
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
import hashlib

from core.observability.logger import get_structured_logger

slog = get_structured_logger("user_preferences")


@dataclass
class UserPreferences:
    """User preference profile."""
    user_id: str
    creation_date: float = field(default_factory=lambda: datetime.now().timestamp())
    last_updated: float = field(default_factory=lambda: datetime.now().timestamp())

    # Behavioral patterns
    command_frequency: Dict[str, int] = field(default_factory=dict)
    approval_patterns: Dict[str, float] = field(default_factory=dict)  # action_type -> approval_rate
    intent_success_rates: Dict[str, float] = field(default_factory=dict)
    response_format_preference: str = "concise"  # verbose, normal, concise

    # Session continuity
    last_session_id: Optional[str] = None
    last_session_context: Dict[str, Any] = field(default_factory=dict)
    session_history: List[str] = field(default_factory=list)  # recent session IDs

    # Model preferences
    preferred_model: Optional[str] = None
    model_performance: Dict[str, float] = field(default_factory=dict)  # model -> avg_score

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)


class PreferenceManager:
    """Manages user preferences and learning."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize preference manager.

        Args:
            storage_path: Path to store preferences (default: ~/.elyan/preferences)
        """
        if storage_path is None:
            storage_path = os.path.expanduser("~/.elyan/preferences")
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        self._preferences: Dict[str, UserPreferences] = {}
        self._load_all_preferences()

    def _load_all_preferences(self) -> None:
        """Load all preference files from storage."""
        try:
            for file_path in self.storage_path.glob("*.json"):
                try:
                    with open(file_path, "r") as f:
                        data = json.load(f)
                    user_id = file_path.stem
                    prefs = UserPreferences(**data)
                    self._preferences[user_id] = prefs
                except Exception as e:
                    slog.log_event("pref_load_error", {
                        "file": file_path.name,
                        "error": str(e)
                    }, level="warning")
        except Exception as e:
            slog.log_event("pref_load_all_error", {"error": str(e)}, level="error")

    def _get_user_id(self, session_id: str) -> str:
        """Extract or generate user ID from session."""
        # Simple approach: hash of session prefix (user identifier)
        # In production, this would be actual user ID from auth system
        prefix = session_id.split("_")[0] if "_" in session_id else "anon"
        return prefix

    def _save_preferences(self, user_id: str) -> None:
        """Save preferences to disk."""
        try:
            file_path = self.storage_path / f"{user_id}.json"
            prefs = self._preferences.get(user_id)
            if prefs:
                with open(file_path, "w") as f:
                    json.dump(prefs.to_dict(), f, indent=2)
        except Exception as e:
            slog.log_event("pref_save_error", {
                "user_id": user_id,
                "error": str(e)
            }, level="error")

    def get_preferences(self, session_id: str) -> UserPreferences:
        """Get or create user preferences."""
        user_id = self._get_user_id(session_id)
        if user_id not in self._preferences:
            self._preferences[user_id] = UserPreferences(user_id=user_id)
            self._save_preferences(user_id)
        return self._preferences[user_id]

    def record_command(self, session_id: str, command: str) -> None:
        """Record command execution."""
        prefs = self.get_preferences(session_id)
        prefs.command_frequency[command] = prefs.command_frequency.get(command, 0) + 1
        prefs.last_updated = datetime.now().timestamp()
        self._save_preferences(prefs.user_id)

    def record_approval_decision(self, session_id: str, action_type: str, approved: bool) -> None:
        """Record approval decision for pattern learning."""
        prefs = self.get_preferences(session_id)

        # Update approval pattern
        key = action_type
        if key not in prefs.approval_patterns:
            prefs.approval_patterns[key] = 0.0

        # Running average
        current_count = int(prefs.approval_patterns.get(f"{key}_count", 0))
        current_sum = prefs.approval_patterns[key] * current_count
        current_sum += 1.0 if approved else 0.0
        current_count += 1
        prefs.approval_patterns[key] = current_sum / current_count
        prefs.approval_patterns[f"{key}_count"] = current_count

        prefs.last_updated = datetime.now().timestamp()
        self._save_preferences(prefs.user_id)

    def record_intent_result(self, session_id: str, intent: str, success: bool, confidence: float = 1.0) -> None:
        """Record intent execution result."""
        prefs = self.get_preferences(session_id)

        # Update success rate
        key = intent
        if key not in prefs.intent_success_rates:
            prefs.intent_success_rates[key] = 0.0

        current_count = int(prefs.intent_success_rates.get(f"{key}_count", 0))
        current_sum = prefs.intent_success_rates[key] * current_count
        current_sum += 1.0 if success else 0.0
        current_count += 1
        prefs.intent_success_rates[key] = current_sum / current_count
        prefs.intent_success_rates[f"{key}_count"] = current_count

        prefs.last_updated = datetime.now().timestamp()
        self._save_preferences(prefs.user_id)

    def set_response_preference(self, session_id: str, format_style: str) -> None:
        """Set user's preferred response format."""
        prefs = self.get_preferences(session_id)
        if format_style in ("verbose", "normal", "concise"):
            prefs.response_format_preference = format_style
            prefs.last_updated = datetime.now().timestamp()
            self._save_preferences(prefs.user_id)

    def record_session(self, session_id: str) -> None:
        """Record session for continuity tracking."""
        prefs = self.get_preferences(session_id)
        prefs.last_session_id = session_id
        prefs.session_history.append(session_id)
        # Keep only last 10 sessions
        prefs.session_history = prefs.session_history[-10:]
        prefs.last_updated = datetime.now().timestamp()
        self._save_preferences(prefs.user_id)

    def get_top_commands(self, session_id: str, limit: int = 5) -> List[str]:
        """Get user's most frequently used commands."""
        prefs = self.get_preferences(session_id)
        sorted_commands = sorted(
            prefs.command_frequency.items(),
            key=lambda x: x[1],
            reverse=True
        )
        return [cmd for cmd, _ in sorted_commands[:limit]]

    def get_approval_prediction(self, session_id: str, action_type: str) -> float:
        """Predict likelihood user will approve this action type.

        Returns probability 0.0-1.0 based on historical patterns.
        """
        prefs = self.get_preferences(session_id)
        return prefs.approval_patterns.get(action_type, 0.5)

    def get_intent_confidence(self, session_id: str, intent: str) -> float:
        """Get historical success rate for intent type."""
        prefs = self.get_preferences(session_id)
        return prefs.intent_success_rates.get(intent, 0.5)

    def get_adaptive_context(self, session_id: str) -> Dict[str, Any]:
        """Get user context for adaptive behavior."""
        prefs = self.get_preferences(session_id)
        return {
            "user_id": prefs.user_id,
            "response_format": prefs.response_format_preference,
            "top_commands": self.get_top_commands(session_id),
            "last_session_id": prefs.last_session_id,
            "session_count": len(prefs.session_history),
            "preferred_model": prefs.preferred_model
        }


# Global instance
_preference_manager: Optional[PreferenceManager] = None


def get_preference_manager(storage_path: Optional[str] = None) -> PreferenceManager:
    """Get or create preference manager singleton."""
    global _preference_manager
    if _preference_manager is None:
        _preference_manager = PreferenceManager(storage_path)
    return _preference_manager
