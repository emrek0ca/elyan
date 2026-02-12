"""
Learning Engine - Wiqo's Adaptive Intelligence System

Kullanıcı davranışlarını öğrenir, tercihlerini kaydeder ve zamanla adapte olur.

Features:
1. User Preference Learning - Tercihler
2. Pattern Recognition - Sık kullanılan komutlar
3. Success/Failure Tracking - Başarı oranları
4. Context Awareness - Bağlam anlama
5. Predictive Suggestions - Tahminler
6. Auto-optimization - Kendini geliştirme

Database Schema:
- user_interactions: Her etkileşim
- learned_patterns: Öğrenilen pattern'ler
- user_preferences: Kullanıcı tercihleri
- success_metrics: Başarı metrikleri
- context_history: Bağlam geçmişi
"""

import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from collections import Counter, defaultdict
import asyncio

from utils.logger import get_logger

logger = get_logger("learning_engine")


@dataclass
class Interaction:
    """Single user interaction record"""
    timestamp: float
    user_id: str
    input_text: str
    intent: str
    action: str
    success: bool
    duration_ms: int
    context: Dict[str, Any]
    feedback: Optional[str] = None


@dataclass
class LearnedPattern:
    """Pattern learned from user behavior"""
    pattern: str
    intent: str
    action: str
    frequency: int
    success_rate: float
    avg_duration_ms: int
    last_used: float
    confidence: float


@dataclass
class UserPreference:
    """User preference"""
    key: str
    value: Any
    learned_from: str  # "explicit" or "implicit"
    confidence: float
    last_updated: float


class LearningEngine:
    """
    Adaptive learning system that improves over time.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".wiqo" / "learning.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory caches for speed
        self._pattern_cache: Dict[str, LearnedPattern] = {}
        self._preference_cache: Dict[str, UserPreference] = {}
        self._context_window: List[Interaction] = []
        self._quick_patterns: Dict[str, str] = {}  # Fast lookup

        self._initialize_database()
        self._load_caches()

        logger.info(f"Learning engine initialized: {self.db_path}")

    def _initialize_database(self):
        """Create database tables"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    user_id TEXT NOT NULL,
                    input_text TEXT NOT NULL,
                    intent TEXT,
                    action TEXT,
                    success INTEGER NOT NULL,
                    duration_ms INTEGER,
                    context TEXT,
                    feedback TEXT
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_user_time ON interactions (user_id, timestamp)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_intent ON interactions (intent)
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS learned_patterns (
                    pattern TEXT PRIMARY KEY,
                    intent TEXT NOT NULL,
                    action TEXT NOT NULL,
                    frequency INTEGER DEFAULT 1,
                    success_rate REAL DEFAULT 1.0,
                    avg_duration_ms INTEGER,
                    last_used REAL NOT NULL,
                    confidence REAL DEFAULT 0.5
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    learned_from TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    last_updated REAL NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS success_metrics (
                    action TEXT PRIMARY KEY,
                    total_executions INTEGER DEFAULT 0,
                    successful_executions INTEGER DEFAULT 0,
                    avg_duration_ms INTEGER DEFAULT 0,
                    last_execution REAL
                )
            """)

            conn.commit()

    def _load_caches(self):
        """Load frequently used data into memory"""
        with sqlite3.connect(self.db_path) as conn:
            # Load learned patterns
            cursor = conn.execute("""
                SELECT * FROM learned_patterns
                ORDER BY frequency DESC, confidence DESC
                LIMIT 100
            """)

            for row in cursor:
                pattern = LearnedPattern(
                    pattern=row[0],
                    intent=row[1],
                    action=row[2],
                    frequency=row[3],
                    success_rate=row[4],
                    avg_duration_ms=row[5],
                    last_used=row[6],
                    confidence=row[7]
                )
                self._pattern_cache[row[0]] = pattern
                self._quick_patterns[row[0].lower()] = row[2]

            # Load preferences
            cursor = conn.execute("SELECT * FROM user_preferences")
            for row in cursor:
                pref = UserPreference(
                    key=row[0],
                    value=json.loads(row[1]),
                    learned_from=row[2],
                    confidence=row[3],
                    last_updated=row[4]
                )
                self._preference_cache[row[0]] = pref

        logger.info(f"Loaded {len(self._pattern_cache)} patterns, {len(self._preference_cache)} preferences")

    async def record_interaction(
        self,
        user_id: str,
        input_text: str,
        intent: str,
        action: str,
        success: bool,
        duration_ms: int,
        context: Optional[Dict] = None,
        feedback: Optional[str] = None
    ):
        """Record user interaction for learning"""
        interaction = Interaction(
            timestamp=time.time(),
            user_id=user_id,
            input_text=input_text,
            intent=intent,
            action=action,
            success=success,
            duration_ms=duration_ms,
            context=context or {},
            feedback=feedback
        )

        # Store in context window (last 10 interactions)
        self._context_window.append(interaction)
        if len(self._context_window) > 10:
            self._context_window.pop(0)

        # Async database insert
        asyncio.create_task(self._store_interaction(interaction))

        # Learn from this interaction
        await self._learn_from_interaction(interaction)

    async def _store_interaction(self, interaction: Interaction):
        """Store interaction in database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO interactions
                    (timestamp, user_id, input_text, intent, action, success, duration_ms, context, feedback)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    interaction.timestamp,
                    interaction.user_id,
                    interaction.input_text,
                    interaction.intent,
                    interaction.action,
                    1 if interaction.success else 0,
                    interaction.duration_ms,
                    json.dumps(interaction.context),
                    interaction.feedback
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to store interaction: {e}")

    async def _learn_from_interaction(self, interaction: Interaction):
        """Learn patterns and preferences from interaction"""
        # 1. Update pattern learning
        pattern_key = interaction.input_text.lower().strip()

        if pattern_key in self._pattern_cache:
            # Update existing pattern
            pattern = self._pattern_cache[pattern_key]
            pattern.frequency += 1
            pattern.last_used = interaction.timestamp

            # Update success rate (running average)
            new_success = 1.0 if interaction.success else 0.0
            pattern.success_rate = (pattern.success_rate * 0.9) + (new_success * 0.1)

            # Update avg duration
            pattern.avg_duration_ms = int(
                (pattern.avg_duration_ms * 0.9) + (interaction.duration_ms * 0.1)
            )

            # Increase confidence
            pattern.confidence = min(1.0, pattern.confidence + 0.05)

        else:
            # Create new pattern
            pattern = LearnedPattern(
                pattern=pattern_key,
                intent=interaction.intent,
                action=interaction.action,
                frequency=1,
                success_rate=1.0 if interaction.success else 0.0,
                avg_duration_ms=interaction.duration_ms,
                last_used=interaction.timestamp,
                confidence=0.5
            )
            self._pattern_cache[pattern_key] = pattern
            self._quick_patterns[pattern_key] = interaction.action

        # 2. Update success metrics
        await self._update_success_metrics(interaction)

        # 3. Learn preferences (if any signals)
        await self._learn_preferences(interaction)

        # 4. Persist to database (async)
        asyncio.create_task(self._persist_learned_pattern(pattern))

    async def _update_success_metrics(self, interaction: Interaction):
        """Update success metrics for action"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO success_metrics (action, total_executions, successful_executions, avg_duration_ms, last_execution)
                    VALUES (?, 1, ?, ?, ?)
                    ON CONFLICT(action) DO UPDATE SET
                        total_executions = total_executions + 1,
                        successful_executions = successful_executions + excluded.successful_executions,
                        avg_duration_ms = (avg_duration_ms * 9 + excluded.avg_duration_ms) / 10,
                        last_execution = excluded.last_execution
                """, (
                    interaction.action,
                    1 if interaction.success else 0,
                    interaction.duration_ms,
                    interaction.timestamp
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to update metrics: {e}")

    async def _learn_preferences(self, interaction: Interaction):
        """Implicitly learn user preferences"""
        # Example: If user frequently uses certain tools, prefer them
        # Example: If user prefers short/long responses
        # Example: Time of day preferences

        # Time preference
        hour = datetime.fromtimestamp(interaction.timestamp).hour
        time_key = f"active_hours_{hour}"

        if time_key in self._preference_cache:
            pref = self._preference_cache[time_key]
            pref.value = pref.value + 1
            pref.confidence = min(1.0, pref.confidence + 0.01)
            pref.last_updated = interaction.timestamp
        else:
            pref = UserPreference(
                key=time_key,
                value=1,
                learned_from="implicit",
                confidence=0.1,
                last_updated=interaction.timestamp
            )
            self._preference_cache[time_key] = pref

    async def _persist_learned_pattern(self, pattern: LearnedPattern):
        """Persist pattern to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO learned_patterns
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    pattern.pattern,
                    pattern.intent,
                    pattern.action,
                    pattern.frequency,
                    pattern.success_rate,
                    pattern.avg_duration_ms,
                    pattern.last_used,
                    pattern.confidence
                ))
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist pattern: {e}")

    def quick_match(self, input_text: str) -> Optional[str]:
        """
        Ultra-fast pattern matching using learned patterns.
        Returns action directly if confident match found.
        """
        key = input_text.lower().strip()

        # Exact match
        if key in self._quick_patterns:
            pattern = self._pattern_cache.get(key)
            if pattern and pattern.confidence > 0.7:
                logger.info(f"Quick match: '{input_text}' -> {pattern.action}")
                return pattern.action

        # Fuzzy match (contains)
        for pattern_key, action in self._quick_patterns.items():
            if pattern_key in key or key in pattern_key:
                pattern = self._pattern_cache.get(pattern_key)
                if pattern and pattern.confidence > 0.6:
                    logger.info(f"Fuzzy match: '{input_text}' -> {action}")
                    return action

        return None

    def get_suggestions(self, context: Optional[Dict] = None) -> List[str]:
        """Get predictive suggestions based on context and history"""
        suggestions = []

        # Recent patterns
        recent_patterns = sorted(
            self._pattern_cache.values(),
            key=lambda p: (p.last_used, p.frequency),
            reverse=True
        )[:5]

        for pattern in recent_patterns:
            if pattern.success_rate > 0.7:
                suggestions.append(pattern.pattern)

        return suggestions

    def get_stats(self) -> Dict[str, Any]:
        """Get learning statistics"""
        total_patterns = len(self._pattern_cache)
        high_confidence = sum(1 for p in self._pattern_cache.values() if p.confidence > 0.7)

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM interactions")
            total_interactions = cursor.fetchone()[0]

            cursor = conn.execute("SELECT COUNT(*) FROM interactions WHERE success = 1")
            successful = cursor.fetchone()[0]

        success_rate = successful / total_interactions if total_interactions > 0 else 0

        return {
            "total_patterns": total_patterns,
            "high_confidence_patterns": high_confidence,
            "total_interactions": total_interactions,
            "success_rate": success_rate,
            "preferences": len(self._preference_cache)
        }


# Singleton instance
_learning_engine: Optional[LearningEngine] = None


def get_learning_engine() -> LearningEngine:
    """Get singleton learning engine instance"""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine
