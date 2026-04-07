"""
Proactive Suggestion Engine
Detects patterns and suggests fixes before user asks ("I noticed X, fix Y?").
"""

from __future__ import annotations

import re
from typing import Dict, Any, List
from datetime import datetime


class SuggestionEngine:
    """
    Generates proactive suggestions based on:
    - User intent and recent activity
    - Common error patterns
    - Unfinished tasks
    - Performance issues
    """

    def __init__(self):
        self.suggestion_rules: List[Dict[str, Any]] = self._init_rules()

    def _init_rules(self) -> List[Dict[str, Any]]:
        """Initialize suggestion rules."""
        return [
            {
                "id": "trailing_whitespace",
                "trigger": r"(paste|file|create)\b",
                "suggestion": "Dosyayı kaydetmeden önce gereksiz boşlukları da temizleyebilirim.",
                "severity": "low",
            },
            {
                "id": "missing_import",
                "trigger": r"(python|code|run)\b",
                "suggestion": "İstersen eksik import veya bağımlılık tarafını da hızlıca kontrol edeyim.",
                "severity": "medium",
            },
            {
                "id": "type_mismatch",
                "trigger": r"(error|fail|type|convert)\b",
                "suggestion": "Tip dönüşümü tarafında bir uyumsuzluk olabilir. Onu da tarayabilirim.",
                "severity": "medium",
            },
            {
                "id": "incomplete_task",
                "trigger": r"(test|build|deploy)\b",
                "suggestion": "İstersen son adımda doğrulamayı da ben çalıştırayım.",
                "severity": "low",
            },
            {
                "id": "performance_issue",
                "trigger": r"(slow|lag|hang|timeout)\b",
                "suggestion": "Darboğazı bulmak için profiling veya log tarafına da bakabilirim.",
                "severity": "high",
            },
            {
                "id": "security_concern",
                "trigger": r"(password|secret|key|token|credential|şifre|gizli)",
                "suggestion": "Güvenlik için bunu düz metin tutmayalım. Ortam değişkeni ya da vault daha doğru olur.",
                "severity": "critical",
            },
        ]

    async def generate_suggestions(
        self,
        user_message: str,
        session_data: Dict[str, Any],
        flow_analysis: Dict[str, Any],
        context_data: Dict[str, Any],
    ) -> List[str]:
        """
        Generate proactive suggestions for the user.

        Args:
            user_message: User's input
            session_data: Session conversation history
            flow_analysis: Flow analysis result
            context_data: Additional context

        Returns:
            List of suggestion strings
        """
        suggestions = []

        # 1. Rule-based suggestions
        rule_suggestions = self._check_rules(user_message)
        suggestions.extend(rule_suggestions)

        # 2. History-based suggestions
        history_suggestions = self._analyze_history(session_data.get("messages", []))
        suggestions.extend(history_suggestions)

        # 3. Context-based suggestions
        if context_data.get("repeat_question"):
            suggestions.append("Bu soruya benzer bir şeyi az önce konuştuk. İstersen oradan devam edeyim.")

        return suggestions[:3]  # Limit to 3 suggestions

    def _check_rules(self, message: str) -> List[str]:
        """Check suggestion rules against user message."""
        suggestions = []
        message_lower = message.lower()

        for rule in self.suggestion_rules:
            if re.search(rule["trigger"], message_lower):
                # Limit critical issues to 1, others to 2
                if rule["severity"] == "critical":
                    suggestions.insert(0, rule["suggestion"])
                    break
                else:
                    suggestions.append(rule["suggestion"])

        return suggestions

    def _analyze_history(self, messages: List[Dict[str, str]]) -> List[str]:
        """Analyze conversation history for patterns."""
        suggestions = []

        if not messages:
            return suggestions

        # Count message types
        message_count = len(messages)

        # If many questions without resolution
        if message_count > 5:
            recent = messages[-5:]
            question_count = sum(
                1 for m in recent if m.get("user", "").endswith("?")
            )
            if question_count >= 3:
                suggestions.append(
                    "İstersen bunu tek plan altında toparlayıp adım adım ilerleyeyim."
                )

        # If alternating quick messages (possible loop)
        if message_count >= 3:
            recent_lengths = [len(m.get("user", "").split()) for m in messages[-3:]]
            if all(l < 5 for l in recent_lengths):
                suggestions.append(
                    "Aynı noktada dönüyor olabiliriz. İstersen bir seviye geri çekilip kök nedeni ayıralım."
                )

        return suggestions

    def rate_suggestion(self, suggestion: str) -> float:
        """Rate suggestion quality (0.0-1.0)."""
        # Simple heuristic: emoji + specific advice = better
        emoji_count = sum(1 for c in suggestion if ord(c) > 127)
        has_specific_action = any(
            word in suggestion.lower()
            for word in ["misiniz", "etmek", "yap", "koy", "dene", "çalıştır"]
        )

        score = 0.5
        score += 0.2 if emoji_count > 0 else 0
        score += 0.3 if has_specific_action else 0

        return min(1.0, score)


__all__ = ["SuggestionEngine"]
