"""
Context Continuity Tracker
Ensures Elyan never repeats questions and maintains conversation context.
"""

from __future__ import annotations

import hashlib
from typing import Dict, Set, List
from datetime import datetime, timedelta


class ContextContinuityTracker:
    """
    Tracks questions asked to avoid repeating them.
    Implements simple similarity matching to catch variations.
    """

    def __init__(self, max_history: int = 100, ttl_hours: int = 24):
        """
        Args:
            max_history: Maximum questions to track
            ttl_hours: Time-to-live for question memory (hours)
        """
        self.max_history = max_history
        self.ttl_hours = ttl_hours
        self._session_questions: Dict[str, List[Dict[str, str | float]]] = {}

    def record_question(self, question: str, session_id: str) -> None:
        """Record that a question was asked."""
        if session_id not in self._session_questions:
            self._session_questions[session_id] = []

        # Normalize and hash for deduplication
        normalized = self._normalize(question)
        question_hash = hashlib.md5(normalized.encode()).hexdigest()

        self._session_questions[session_id].append(
            {
                "question": question,
                "hash": question_hash,
                "normalized": normalized,
                "timestamp": datetime.now().isoformat(),
            }
        )

        # Enforce max history
        if len(self._session_questions[session_id]) > self.max_history:
            self._session_questions[session_id].pop(0)

    def is_repeat_question(self, question: str, session_id: str) -> bool:
        """
        Check if question is a repeat of a previous one.

        Uses normalized matching + hash to catch variations.
        """
        if session_id not in self._session_questions:
            return False

        normalized = self._normalize(question)
        question_hash = hashlib.md5(normalized.encode()).hexdigest()

        # Check exact hash match (after normalization)
        for q_record in self._session_questions[session_id]:
            if q_record["hash"] == question_hash:
                # Check TTL
                if self._is_fresh(q_record["timestamp"]):
                    return True

        # Check semantic similarity (simple word overlap)
        similarity = self._semantic_similarity(
            question, self._get_all_questions(session_id)
        )
        return similarity > 0.8  # 80% match = repeat

    def get_asked_questions(self, session_id: str) -> List[str]:
        """Get all questions asked in session."""
        if session_id not in self._session_questions:
            return []

        return [q["question"] for q in self._session_questions[session_id]]

    def clear_session(self, session_id: str) -> None:
        """Clear question history for session."""
        if session_id in self._session_questions:
            del self._session_questions[session_id]

    def _normalize(self, text: str) -> str:
        """Normalize text for comparison."""
        # Remove punctuation, lowercase, collapse whitespace
        import re

        text = text.lower().strip()
        text = re.sub(r"[?!.,;:\-]", "", text)
        text = re.sub(r"\s+", " ", text)
        return text

    def _is_fresh(self, timestamp: str) -> bool:
        """Check if question is within TTL."""
        try:
            q_time = datetime.fromisoformat(timestamp)
            now = datetime.now()
            age = (now - q_time).total_seconds() / 3600  # hours
            return age < self.ttl_hours
        except Exception:
            return True

    def _get_all_questions(self, session_id: str) -> List[str]:
        """Get all questions in session (within TTL)."""
        if session_id not in self._session_questions:
            return []

        return [
            q["question"]
            for q in self._session_questions[session_id]
            if self._is_fresh(q["timestamp"])
        ]

    def _semantic_similarity(self, question: str, history: List[str]) -> float:
        """
        Compute similarity between question and history.

        Simple word overlap method.
        """
        if not history:
            return 0.0

        q_words = set(self._normalize(question).split())
        if not q_words:
            return 0.0

        max_similarity = 0.0
        for hist_q in history:
            h_words = set(self._normalize(hist_q).split())
            if not h_words:
                continue

            # Jaccard similarity
            intersection = len(q_words & h_words)
            union = len(q_words | h_words)

            if union > 0:
                similarity = intersection / union
                max_similarity = max(max_similarity, similarity)

        return max_similarity


__all__ = ["ContextContinuityTracker"]
