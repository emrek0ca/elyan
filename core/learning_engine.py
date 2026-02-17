"""
Learning Engine - Elyan's Adaptive Intelligence System

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
import re
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
            db_path = Path.home() / ".elyan" / "learning.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory caches for speed
        self._pattern_cache: Dict[str, LearnedPattern] = {}
        self._preference_cache: Dict[str, UserPreference] = {}
        self._context_window: List[Interaction] = []
        self._quick_patterns: Dict[str, str] = {}  # Fast lookup
        self._skill_memory_cache: Dict[Tuple[str, str], Dict[str, Any]] = {}

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

            conn.execute("""
                CREATE TABLE IF NOT EXISTS skill_memory (
                    domain TEXT NOT NULL,
                    pattern TEXT NOT NULL,
                    preferred_tools TEXT,
                    preferred_output TEXT,
                    quality_focus TEXT,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    avg_quality REAL DEFAULT 0.0,
                    last_used REAL NOT NULL,
                    PRIMARY KEY (domain, pattern)
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

            # Load skill memory rows
            cursor = conn.execute("""
                SELECT domain, pattern, preferred_tools, preferred_output, quality_focus,
                       success_count, failure_count, avg_quality, last_used
                FROM skill_memory
                ORDER BY (success_count - failure_count) DESC, avg_quality DESC, last_used DESC
                LIMIT 200
            """)
            for row in cursor:
                key = (str(row[0] or "general"), str(row[1] or ""))
                self._skill_memory_cache[key] = {
                    "domain": key[0],
                    "pattern": key[1],
                    "preferred_tools": json.loads(row[2]) if row[2] else [],
                    "preferred_output": str(row[3] or ""),
                    "quality_focus": json.loads(row[4]) if row[4] else [],
                    "success_count": int(row[5] or 0),
                    "failure_count": int(row[6] or 0),
                    "avg_quality": float(row[7] or 0.0),
                    "last_used": float(row[8] or 0.0),
                }
        logger.info(
            f"Loaded {len(self._pattern_cache)} patterns, {len(self._preference_cache)} preferences, "
            f"{len(self._skill_memory_cache)} skill memories"
        )

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

        # Explicit preference signals in user text.
        explicit_prefs = self._detect_preferences(interaction.input_text)
        for pref_key, pref_value, confidence, learned_from in explicit_prefs:
            self._upsert_preference(
                key=pref_key,
                value=pref_value,
                learned_from=learned_from,
                confidence=confidence,
                timestamp=interaction.timestamp,
            )

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(str(text or "").lower().strip().split())

    def _detect_preferences(self, text: str) -> List[Tuple[str, Any, float, str]]:
        t = self._normalize(text)
        if not t:
            return []

        explicit_markers = [
            "bundan sonra",
            "artık",
            "tercihim",
            "lütfen",
            "her zaman",
        ]
        is_explicit = any(m in t for m in explicit_markers)
        base_conf = 0.6 if is_explicit else 0.45

        prefs: List[Tuple[str, Any, float, str]] = []

        # Length preference
        if any(k in t for k in ["kısa", "kisa", "özet", "ozet", "özetle", "kısa tut"]):
            prefs.append(("response_length", "short", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
        if any(k in t for k in ["detaylı", "detayli", "uzun", "tüm detay", "tum detay"]):
            prefs.append(("response_length", "detailed", base_conf + 0.1, "explicit" if is_explicit else "implicit"))

        # Tone preference
        if any(k in t for k in ["resmi", "kurumsal"]):
            prefs.append(("communication_tone", "formal", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
        if any(k in t for k in ["samimi", "sıcak", "sicak"]):
            prefs.append(("communication_tone", "friendly", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
        if "profesyonel" in t:
            prefs.append(("communication_tone", "professional_friendly", base_conf + 0.05, "explicit" if is_explicit else "implicit"))

        # Language preference
        if any(k in t for k in ["ingilizce", "english"]):
            prefs.append(("preferred_language", "en", base_conf + 0.15, "explicit" if is_explicit else "implicit"))
        if any(k in t for k in ["türkçe", "turkce"]):
            prefs.append(("preferred_language", "tr", base_conf + 0.15, "explicit" if is_explicit else "implicit"))

        # Format style
        if "adım adım" in t or "adim adim" in t:
            prefs.append(("format_style", "steps", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
        if "madde madde" in t:
            prefs.append(("format_style", "bullets", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
        if "tablo" in t:
            prefs.append(("format_style", "table", base_conf + 0.1, "explicit" if is_explicit else "implicit"))

        # Code inclusion
        if any(k in t for k in ["kodsuz", "kod istemiyorum", "kod olmasın"]):
            prefs.append(("include_code", False, base_conf + 0.2, "explicit" if is_explicit else "implicit"))
        if any(k in t for k in ["kod yaz", "kodu ver", "kodla", "code"]):
            prefs.append(("include_code", True, base_conf + 0.15, "explicit" if is_explicit else "implicit"))

        # Output format preference
        if any(k in t for k in ["pdf", "docx", "word", "markdown", "md", "json", "csv", "yaml", "excel"]):
            if "pdf" in t:
                prefs.append(("preferred_output", "pdf", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
            elif "docx" in t or "word" in t:
                prefs.append(("preferred_output", "docx", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
            elif "json" in t:
                prefs.append(("preferred_output", "json", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
            elif "csv" in t or "excel" in t:
                prefs.append(("preferred_output", "csv", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
            elif "yaml" in t:
                prefs.append(("preferred_output", "yaml", base_conf + 0.1, "explicit" if is_explicit else "implicit"))
            elif "markdown" in t or "md" in t:
                prefs.append(("preferred_output", "markdown", base_conf + 0.1, "explicit" if is_explicit else "implicit"))

        # User alias preference
        alias_match = re.search(
            r"\bbana\s+([a-z0-9çğıöşü _-]{2,24})\s+(de|diye hitap et|diye seslen|olarak hitap et)\b",
            t,
        )
        if alias_match:
            alias = alias_match.group(1).strip()
            if alias:
                prefs.append(("user_alias", alias, 0.75, "explicit"))

        return prefs

    def _upsert_preference(
        self,
        *,
        key: str,
        value: Any,
        learned_from: str,
        confidence: float,
        timestamp: float,
    ) -> None:
        pref = self._preference_cache.get(key)
        if pref:
            pref.value = value
            pref.learned_from = learned_from
            pref.confidence = max(pref.confidence, float(confidence))
            pref.last_updated = timestamp
        else:
            pref = UserPreference(
                key=key,
                value=value,
                learned_from=learned_from,
                confidence=float(confidence),
                last_updated=timestamp,
            )
            self._preference_cache[key] = pref
        asyncio.create_task(self._persist_preference(pref))

    async def _persist_preference(self, pref: UserPreference):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO user_preferences (key, value, learned_from, confidence, last_updated)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value,
                        learned_from=excluded.learned_from,
                        confidence=excluded.confidence,
                        last_updated=excluded.last_updated
                    """,
                    (
                        pref.key,
                        json.dumps(pref.value, ensure_ascii=False),
                        pref.learned_from,
                        float(pref.confidence),
                        float(pref.last_updated),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist preference: {e}")

    def get_preference(self, key: str, min_confidence: float = 0.6) -> Optional[Any]:
        pref = self._preference_cache.get(key)
        if not pref:
            return None
        if float(pref.confidence or 0.0) < float(min_confidence):
            return None
        return pref.value

    def get_preferences(self, min_confidence: float = 0.6) -> Dict[str, Any]:
        prefs: Dict[str, Any] = {}
        for key, pref in self._preference_cache.items():
            if float(pref.confidence or 0.0) >= float(min_confidence):
                prefs[key] = pref.value
        return prefs

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
            "preferences": len(self._preference_cache),
            "skill_memories": len(self._skill_memory_cache),
        }

    @staticmethod
    def _signature(input_text: str) -> str:
        words = [w.strip(".,:;!?()[]{}\"'").lower() for w in str(input_text or "").split()]
        words = [w for w in words if len(w) >= 3]
        return " ".join(words[:8])

    async def record_outcome(
        self,
        *,
        domain: str,
        input_text: str,
        execution_requirements: Optional[Dict[str, Any]] = None,
        tool_actions: Optional[List[str]] = None,
        success: bool,
        quality_score: float,
        publish_ready: bool,
    ):
        req = execution_requirements or {}
        signature = self._signature(input_text)
        if not signature:
            return
        domain_key = str(domain or "general")
        key = (domain_key, signature)
        current = self._skill_memory_cache.get(key, {
            "domain": domain_key,
            "pattern": signature,
            "preferred_tools": [],
            "preferred_output": "",
            "quality_focus": [],
            "success_count": 0,
            "failure_count": 0,
            "avg_quality": 0.0,
            "last_used": 0.0,
        })
        if success and publish_ready:
            current["success_count"] = int(current.get("success_count", 0)) + 1
        else:
            current["failure_count"] = int(current.get("failure_count", 0)) + 1

        prev_quality = float(current.get("avg_quality", 0.0))
        if prev_quality <= 0:
            current["avg_quality"] = float(quality_score)
        else:
            current["avg_quality"] = round((prev_quality * 0.8) + (float(quality_score) * 0.2), 2)

        if req.get("preferred_output"):
            current["preferred_output"] = str(req.get("preferred_output"))
        tools = tool_actions or req.get("preferred_tools", [])
        if isinstance(tools, list) and tools:
            uniq = []
            for tool in tools:
                tool_s = str(tool or "").strip()
                if tool_s and tool_s not in uniq:
                    uniq.append(tool_s)
            current["preferred_tools"] = uniq[:6]
        focus = req.get("quality_checklist", [])
        if isinstance(focus, list) and focus:
            current["quality_focus"] = [str(x) for x in focus[:6]]
        current["last_used"] = time.time()
        self._skill_memory_cache[key] = current

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO skill_memory (
                        domain, pattern, preferred_tools, preferred_output, quality_focus,
                        success_count, failure_count, avg_quality, last_used
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(domain, pattern) DO UPDATE SET
                        preferred_tools=excluded.preferred_tools,
                        preferred_output=excluded.preferred_output,
                        quality_focus=excluded.quality_focus,
                        success_count=excluded.success_count,
                        failure_count=excluded.failure_count,
                        avg_quality=excluded.avg_quality,
                        last_used=excluded.last_used
                    """,
                    (
                        domain_key,
                        signature,
                        json.dumps(current.get("preferred_tools", [])),
                        str(current.get("preferred_output", "")),
                        json.dumps(current.get("quality_focus", [])),
                        int(current.get("success_count", 0)),
                        int(current.get("failure_count", 0)),
                        float(current.get("avg_quality", 0.0)),
                        float(current.get("last_used", 0.0)),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to persist skill memory: {e}")

    def get_execution_hints(self, input_text: str, domain: str) -> Dict[str, Any]:
        signature = self._signature(input_text)
        domain_key = str(domain or "general")
        if not signature:
            return {}

        candidates: List[Dict[str, Any]] = []
        for (row_domain, row_pattern), row in self._skill_memory_cache.items():
            if row_domain != domain_key:
                continue
            if signature == row_pattern or signature in row_pattern or row_pattern in signature:
                candidates.append(row)
        if not candidates:
            return {}

        def row_score(row: Dict[str, Any]) -> float:
            success = float(row.get("success_count", 0))
            failure = float(row.get("failure_count", 0))
            ratio = success / max(1.0, success + failure)
            return (ratio * 0.55) + (float(row.get("avg_quality", 0.0)) / 100.0 * 0.35) + (min(1.0, success / 5.0) * 0.10)

        best = sorted(candidates, key=row_score, reverse=True)[0]
        confidence = round(min(0.95, row_score(best)), 2)
        if confidence < 0.45:
            return {}

        return {
            "preferred_output": best.get("preferred_output", ""),
            "preferred_tools_boost": best.get("preferred_tools", [])[:4],
            "quality_focus": best.get("quality_focus", [])[:4],
            "confidence": confidence,
        }

    def self_review(self, window_days: int = 14) -> Dict[str, Any]:
        cutoff = time.time() - (max(1, int(window_days)) * 86400)
        recommendations: List[str] = []
        try:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT action, total_executions, successful_executions, avg_duration_ms
                    FROM success_metrics
                    ORDER BY total_executions DESC
                    LIMIT 15
                    """
                ).fetchall()
                for action, total_exec, successful_exec, avg_duration in rows:
                    total = int(total_exec or 0)
                    if total < 5:
                        continue
                    success_rate = (int(successful_exec or 0) / max(1, total)) * 100.0
                    if success_rate < 65.0:
                        recommendations.append(
                            f"{action}: başarı oranı düşük ({success_rate:.0f}%), plan doğrulamasını güçlendir."
                        )
                    if int(avg_duration or 0) > 30000:
                        recommendations.append(
                            f"{action}: ortalama süre yüksek ({int(avg_duration)}ms), kompakt plan veya cache öner."
                        )

                skill_rows = conn.execute(
                    """
                    SELECT domain, pattern, success_count, failure_count, avg_quality
                    FROM skill_memory
                    WHERE last_used >= ?
                    ORDER BY (success_count - failure_count) ASC, avg_quality ASC
                    LIMIT 10
                    """,
                    (cutoff,),
                ).fetchall()
                for domain, pattern, success_count, failure_count, avg_quality in skill_rows:
                    if int(failure_count or 0) > int(success_count or 0):
                        recommendations.append(
                            f"{domain}: '{pattern}' için başarısızlık yüksek, fallback stratejisi güncelle."
                        )
                    if float(avg_quality or 0.0) < 70.0:
                        recommendations.append(
                            f"{domain}: kalite ortalaması düşük ({float(avg_quality):.1f}), checklist kapsamını artır."
                        )
        except Exception as e:
            logger.error(f"Self-review failed: {e}")

        return {
            "window_days": window_days,
            "recommendations": recommendations[:10],
            "count": min(10, len(recommendations)),
        }


# Singleton instance
_learning_engine: Optional[LearningEngine] = None


def get_learning_engine() -> LearningEngine:
    """Get singleton learning engine instance"""
    global _learning_engine
    if _learning_engine is None:
        _learning_engine = LearningEngine()
    return _learning_engine
