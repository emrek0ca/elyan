"""
User Intent Memory - Persistent Learning

Learns from user corrections and successful intents.
Tracks patterns per user with fuzzy matching.
SQLite-backed for persistence.
"""

import sqlite3
import os
from typing import Optional, Dict, Any, List
from pathlib import Path
from utils.logger import get_logger
from .models import IntentCandidate, IntentConfidence
from difflib import SequenceMatcher

logger = get_logger("user_intent_memory")


class UserIntentMemory:
    """Persistent user-specific intent memory."""

    def __init__(self, db_path: str = "~/.elyan/intent_memory.db"):
        self.db_path = os.path.expanduser(db_path)
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS intent_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    input_pattern TEXT NOT NULL,
                    action TEXT NOT NULL,
                    params TEXT,
                    frequency INTEGER DEFAULT 1,
                    confidence REAL DEFAULT 0.8,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, input_pattern, action)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_action
                ON intent_patterns(user_id, action)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_frequency
                ON intent_patterns(frequency DESC)
            """)

            conn.commit()
            conn.close()
            logger.info(f"Intent memory DB initialized at {self.db_path}")

        except Exception as e:
            logger.error(f"Failed to initialize intent memory DB: {e}")

    def learn_pattern(
        self,
        user_id: str,
        input_pattern: str,
        action: str,
        params: Dict[str, Any]
    ) -> None:
        """
        Learn a new pattern from user correction.

        Args:
            user_id: User ID
            input_pattern: Normalized user input
            action: Correct action
            params: Parameters
        """
        try:
            import json
            params_json = json.dumps(params) if params else None

            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Try to update existing pattern
            cursor.execute("""
                UPDATE intent_patterns
                SET frequency = frequency + 1,
                    last_used_at = CURRENT_TIMESTAMP,
                    confidence = MIN(0.95, confidence + 0.02)
                WHERE user_id = ? AND input_pattern = ? AND action = ?
            """, (user_id, input_pattern.lower(), action))

            # If not found, insert new pattern
            if cursor.rowcount == 0:
                cursor.execute("""
                    INSERT INTO intent_patterns
                    (user_id, input_pattern, action, params, frequency, confidence)
                    VALUES (?, ?, ?, ?, 1, 0.85)
                """, (user_id, input_pattern.lower(), action, params_json))

            conn.commit()
            conn.close()
            logger.info(f"Learned pattern for {user_id}: '{input_pattern}' → {action}")

        except Exception as e:
            logger.error(f"Failed to learn pattern: {e}")

    def get_intent(self, user_input: str, user_id: str) -> Optional[IntentCandidate]:
        """
        Get intent from user memory using fuzzy matching.

        Args:
            user_input: User's input
            user_id: User ID

        Returns:
            IntentCandidate if match found, None otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get all patterns for this user
            cursor.execute("""
                SELECT input_pattern, action, params, frequency, confidence
                FROM intent_patterns
                WHERE user_id = ?
                ORDER BY frequency DESC, confidence DESC
                LIMIT 20
            """, (user_id,))

            patterns = cursor.fetchall()
            conn.close()

            if not patterns:
                return None

            # Fuzzy match
            normalized_input = user_input.lower().strip()
            best_match = None
            best_ratio = 0.0

            for pattern, action, params_json, frequency, confidence in patterns:
                ratio = SequenceMatcher(None, normalized_input, pattern).ratio()
                if ratio > best_ratio and ratio >= 0.75:
                    best_ratio = ratio
                    best_match = (action, params_json, frequency, confidence)

            if not best_match:
                return None

            action, params_json, frequency, confidence = best_match

            # Scale confidence based on frequency and match ratio
            scaled_confidence = min(
                0.95,
                confidence * (0.5 + 0.5 * best_ratio) * (1 + frequency * 0.05)
            )

            import json
            params = json.loads(params_json) if params_json else {}

            return IntentCandidate(
                action=action,
                confidence=scaled_confidence,
                reasoning=f"User memory (frequency: {frequency})",
                params=params,
                source_tier="memory",
                metadata={"user_pattern_frequency": frequency, "match_ratio": best_ratio}
            )

        except Exception as e:
            logger.error(f"Error retrieving intent from memory: {e}")
            return None

    def get_top_intents(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Get user's top intents by frequency."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT action, frequency, confidence, COUNT(*) as pattern_count
                FROM intent_patterns
                WHERE user_id = ?
                GROUP BY action
                ORDER BY frequency DESC
                LIMIT ?
            """, (user_id, limit))

            results = cursor.fetchall()
            conn.close()

            return [
                {
                    "action": action,
                    "frequency": frequency,
                    "confidence": confidence,
                    "pattern_count": pattern_count
                }
                for action, frequency, confidence, pattern_count in results
            ]

        except Exception as e:
            logger.error(f"Error getting top intents: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("SELECT COUNT(DISTINCT user_id) FROM intent_patterns")
            user_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM intent_patterns")
            pattern_count = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(DISTINCT action) FROM intent_patterns")
            action_count = cursor.fetchone()[0]

            conn.close()

            return {
                "users": user_count,
                "total_patterns": pattern_count,
                "unique_actions": action_count
            }

        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def clear_user(self, user_id: str) -> None:
        """Clear all patterns for a user."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM intent_patterns WHERE user_id = ?", (user_id,))
            conn.commit()
            conn.close()
            logger.info(f"Cleared memory for user {user_id}")
        except Exception as e:
            logger.error(f"Error clearing user memory: {e}")

    def export_patterns(self, user_id: str) -> List[Dict[str, Any]]:
        """Export user's learned patterns."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT input_pattern, action, params, frequency, confidence
                FROM intent_patterns
                WHERE user_id = ?
                ORDER BY frequency DESC
            """, (user_id,))

            patterns = cursor.fetchall()
            conn.close()

            import json
            return [
                {
                    "input": pattern,
                    "action": action,
                    "params": json.loads(params) if params else {},
                    "frequency": frequency,
                    "confidence": confidence
                }
                for pattern, action, params, frequency, confidence in patterns
            ]

        except Exception as e:
            logger.error(f"Error exporting patterns: {e}")
            return []
