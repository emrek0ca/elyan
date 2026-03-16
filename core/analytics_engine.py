"""
Analytics Engine - Comprehensive Performance Monitoring

Tracks execution metrics, tool performance, user behavior, and LLM provider performance.
Provides AI-driven recommendations and dashboard-ready metrics.

Turkish/English support with SQLite persistence.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from enum import Enum

from utils.logger import get_logger

logger = get_logger("analytics_engine")


class MetricType(Enum):
    """Types of metrics tracked"""
    EXECUTION = "execution"
    TOOL_USAGE = "tool_usage"
    USER_BEHAVIOR = "user_behavior"
    LLM_PERFORMANCE = "llm_performance"
    ERROR_RATE = "error_rate"


@dataclass
class ExecutionMetric:
    """Execution performance metric"""
    timestamp: float
    duration_ms: int
    success: bool
    tool: str
    intent: str
    complexity: float  # 0.0-1.0
    error_type: Optional[str] = None
    recovery_attempts: int = 0


@dataclass
class ToolAnalytic:
    """Per-tool performance analytics"""
    tool_name: str
    total_calls: int
    successful_calls: int
    avg_duration_ms: float
    cost_usd: float
    reliability_score: float  # 0.0-1.0 based on success rate
    avg_complexity: float
    peak_usage_hour: Optional[int] = None


@dataclass
class UserAnalytic:
    """User behavior analytics"""
    user_id: str
    total_interactions: int
    preferred_tools: Dict[str, int]
    avg_session_duration_ms: float
    learning_rate: float  # How fast user improves at using bot
    favorite_intent: Optional[str]
    language_preference: str  # "tr", "en"
    peak_activity_hours: List[int]


@dataclass
class LLMMetric:
    """LLM provider performance"""
    provider: str
    model: str
    total_calls: int
    successful_calls: int
    avg_latency_ms: float
    avg_cost_usd: float
    quality_score: float  # 0.0-1.0
    error_types: Dict[str, int]
    token_usage_total: int


class AnalyticsEngine:
    """
    Comprehensive analytics tracking system.

    Monitors:
    - Execution metrics (latency, success, complexity)
    - Tool performance (reliability, cost, usage)
    - User behavior (patterns, preferences, learning)
    - LLM provider metrics (quality, cost, latency)

    Provides insights and recommendations.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize analytics engine with SQLite backend"""
        if db_path is None:
            db_path = Path.home() / ".elyan" / "analytics.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory caches
        self._execution_cache: List[ExecutionMetric] = []
        self._tool_cache: Dict[str, ToolAnalytic] = {}
        self._user_cache: Dict[str, UserAnalytic] = {}
        self._llm_cache: Dict[str, LLMMetric] = {}

        self._initialize_database()
        self._load_caches()

        logger.info(f"Analytics engine initialized: {self.db_path}")

    def _initialize_database(self) -> None:
        """Create database schema"""
        with sqlite3.connect(self.db_path) as conn:
            # Execution metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_metrics (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    success INTEGER NOT NULL,
                    tool TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    complexity REAL NOT NULL,
                    error_type TEXT,
                    recovery_attempts INTEGER DEFAULT 0
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_exec_timestamp
                ON execution_metrics (timestamp DESC)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_exec_tool
                ON execution_metrics (tool)
            """)

            # Tool analytics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tool_analytics (
                    tool_name TEXT PRIMARY KEY,
                    total_calls INTEGER DEFAULT 0,
                    successful_calls INTEGER DEFAULT 0,
                    avg_duration_ms REAL DEFAULT 0.0,
                    cost_usd REAL DEFAULT 0.0,
                    reliability_score REAL DEFAULT 0.5,
                    avg_complexity REAL DEFAULT 0.5,
                    peak_usage_hour INTEGER,
                    last_updated REAL NOT NULL
                )
            """)

            # User analytics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS user_analytics (
                    user_id TEXT PRIMARY KEY,
                    total_interactions INTEGER DEFAULT 0,
                    preferred_tools TEXT DEFAULT '{}',
                    avg_session_duration_ms REAL DEFAULT 0.0,
                    learning_rate REAL DEFAULT 0.5,
                    favorite_intent TEXT,
                    language_preference TEXT DEFAULT 'tr',
                    peak_activity_hours TEXT DEFAULT '[]',
                    last_updated REAL NOT NULL
                )
            """)

            # LLM metrics table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_metrics (
                    id TEXT PRIMARY KEY,
                    provider TEXT NOT NULL,
                    model TEXT NOT NULL,
                    total_calls INTEGER DEFAULT 0,
                    successful_calls INTEGER DEFAULT 0,
                    avg_latency_ms REAL DEFAULT 0.0,
                    avg_cost_usd REAL DEFAULT 0.0,
                    quality_score REAL DEFAULT 0.5,
                    error_types TEXT DEFAULT '{}',
                    token_usage_total INTEGER DEFAULT 0,
                    last_updated REAL NOT NULL
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_llm_provider
                ON llm_metrics (provider)
            """)

            # Error tracking table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS error_tracking (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    error_type TEXT NOT NULL,
                    tool TEXT NOT NULL,
                    count INTEGER DEFAULT 1,
                    recovery_success INTEGER DEFAULT 0
                )
            """)

            conn.commit()

    def _load_caches(self) -> None:
        """Load analytics from database into memory"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row

                # Load recent execution metrics
                cursor = conn.execute(
                    "SELECT * FROM execution_metrics ORDER BY timestamp DESC LIMIT 1000"
                )
                for row in cursor:
                    self._execution_cache.append(ExecutionMetric(
                        timestamp=row["timestamp"],
                        duration_ms=row["duration_ms"],
                        success=bool(row["success"]),
                        tool=row["tool"],
                        intent=row["intent"],
                        complexity=row["complexity"],
                        error_type=row["error_type"],
                        recovery_attempts=row["recovery_attempts"]
                    ))

                # Load tool analytics
                cursor = conn.execute("SELECT * FROM tool_analytics")
                for row in cursor:
                    self._tool_cache[row["tool_name"]] = ToolAnalytic(
                        tool_name=row["tool_name"],
                        total_calls=row["total_calls"],
                        successful_calls=row["successful_calls"],
                        avg_duration_ms=row["avg_duration_ms"],
                        cost_usd=row["cost_usd"],
                        reliability_score=row["reliability_score"],
                        avg_complexity=row["avg_complexity"],
                        peak_usage_hour=row["peak_usage_hour"]
                    )

                # Load user analytics
                cursor = conn.execute("SELECT * FROM user_analytics")
                for row in cursor:
                    self._user_cache[row["user_id"]] = UserAnalytic(
                        user_id=row["user_id"],
                        total_interactions=row["total_interactions"],
                        preferred_tools=json.loads(row["preferred_tools"] or "{}"),
                        avg_session_duration_ms=row["avg_session_duration_ms"],
                        learning_rate=row["learning_rate"],
                        favorite_intent=row["favorite_intent"],
                        language_preference=row["language_preference"],
                        peak_activity_hours=json.loads(row["peak_activity_hours"] or "[]")
                    )

                # Load LLM metrics
                cursor = conn.execute("SELECT * FROM llm_metrics")
                for row in cursor:
                    self._llm_cache[row["id"]] = LLMMetric(
                        provider=row["provider"],
                        model=row["model"],
                        total_calls=row["total_calls"],
                        successful_calls=row["successful_calls"],
                        avg_latency_ms=row["avg_latency_ms"],
                        avg_cost_usd=row["avg_cost_usd"],
                        quality_score=row["quality_score"],
                        error_types=json.loads(row["error_types"] or "{}"),
                        token_usage_total=row["token_usage_total"]
                    )

            logger.info(f"Loaded analytics: {len(self._tool_cache)} tools, "
                       f"{len(self._user_cache)} users, {len(self._llm_cache)} LLM configs")
        except Exception as e:
            logger.error(f"Error loading analytics: {e}")

    def record_execution(
        self,
        tool: str,
        intent: str,
        duration_ms: int,
        success: bool,
        complexity: float = 0.5,
        error_type: Optional[str] = None,
        recovery_attempts: int = 0
    ) -> None:
        """Record execution metric"""
        metric = ExecutionMetric(
            timestamp=time.time(),
            duration_ms=max(0, duration_ms),
            success=success,
            tool=tool,
            intent=intent,
            complexity=max(0.0, min(1.0, complexity)),
            error_type=error_type,
            recovery_attempts=recovery_attempts
        )

        self._execution_cache.append(metric)
        if len(self._execution_cache) > 10000:
            self._execution_cache.pop(0)

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO execution_metrics
                    (timestamp, duration_ms, success, tool, intent, complexity, error_type, recovery_attempts)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (metric.timestamp, metric.duration_ms, metric.success,
                      metric.tool, metric.intent, metric.complexity,
                      metric.error_type, metric.recovery_attempts))
                conn.commit()

            self._update_tool_analytics(tool, duration_ms, success, complexity)
        except Exception as e:
            logger.error(f"Error recording execution: {e}")

    def _update_tool_analytics(
        self,
        tool: str,
        duration_ms: int,
        success: bool,
        complexity: float
    ) -> None:
        """Update tool analytics"""
        if tool not in self._tool_cache:
            self._tool_cache[tool] = ToolAnalytic(
                tool_name=tool,
                total_calls=0,
                successful_calls=0,
                avg_duration_ms=0.0,
                cost_usd=0.0,
                reliability_score=0.5,
                avg_complexity=0.0
            )

        analytic = self._tool_cache[tool]
        n = analytic.total_calls + 1

        # Update rolling averages
        analytic.avg_duration_ms = (
            (analytic.avg_duration_ms * (n - 1) + duration_ms) / n
        )
        analytic.avg_complexity = (
            (analytic.avg_complexity * (n - 1) + complexity) / n
        )

        analytic.total_calls = n
        if success:
            analytic.successful_calls += 1

        analytic.reliability_score = (
            analytic.successful_calls / analytic.total_calls
            if analytic.total_calls > 0 else 0.5
        )

        # Update peak usage hour
        current_hour = datetime.now().hour
        if analytic.peak_usage_hour is None:
            analytic.peak_usage_hour = current_hour

        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO tool_analytics
                    (tool_name, total_calls, successful_calls, avg_duration_ms,
                     reliability_score, avg_complexity, peak_usage_hour, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (tool, analytic.total_calls, analytic.successful_calls,
                      analytic.avg_duration_ms, analytic.reliability_score,
                      analytic.avg_complexity, analytic.peak_usage_hour, time.time()))
                conn.commit()
        except Exception as e:
            logger.error(f"Error updating tool analytics: {e}")

    def record_user_interaction(
        self,
        user_id: str,
        tool_used: str,
        intent: str,
        duration_ms: int,
        language: str = "tr"
    ) -> None:
        """Record user interaction"""
        if user_id not in self._user_cache:
            self._user_cache[user_id] = UserAnalytic(
                user_id=user_id,
                total_interactions=0,
                preferred_tools={},
                avg_session_duration_ms=0.0,
                learning_rate=0.5,
                favorite_intent=None,
                language_preference=language,
                peak_activity_hours=[]
            )

        analytic = self._user_cache[user_id]
        n = analytic.total_interactions + 1

        # Update metrics
        analytic.total_interactions = n
        analytic.avg_session_duration_ms = (
            (analytic.avg_session_duration_ms * (n - 1) + duration_ms) / n
        )
        analytic.preferred_tools[tool_used] = analytic.preferred_tools.get(tool_used, 0) + 1
        analytic.language_preference = language

        # Update favorite intent
        intent_counts = Counter()
        for inter in self._execution_cache:
            intent_counts[inter.intent] += 1
        if intent_counts:
            analytic.favorite_intent = intent_counts.most_common(1)[0][0]

        # Update peak activity hours
        hour = datetime.now().hour
        if hour not in analytic.peak_activity_hours:
            analytic.peak_activity_hours.append(hour)
            if len(analytic.peak_activity_hours) > 5:
                analytic.peak_activity_hours.pop(0)

        # Calculate learning rate (improvement over time)
        recent_metrics = [m for m in self._execution_cache
                         if m.timestamp > time.time() - 86400]  # Last 24 hours
        if len(recent_metrics) > 10:
            early = recent_metrics[:len(recent_metrics)//2]
            late = recent_metrics[len(recent_metrics)//2:]
            early_success = sum(1 for m in early if m.success) / len(early)
            late_success = sum(1 for m in late if m.success) / len(late)
            analytic.learning_rate = max(0.0, late_success - early_success)

        self._persist_user_analytics(analytic)

    def _persist_user_analytics(self, analytic: UserAnalytic) -> None:
        """Persist user analytics to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO user_analytics
                    (user_id, total_interactions, preferred_tools, avg_session_duration_ms,
                     learning_rate, favorite_intent, language_preference, peak_activity_hours, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (analytic.user_id, analytic.total_interactions,
                      json.dumps(analytic.preferred_tools),
                      analytic.avg_session_duration_ms, analytic.learning_rate,
                      analytic.favorite_intent, analytic.language_preference,
                      json.dumps(analytic.peak_activity_hours), time.time()))
                conn.commit()
        except Exception as e:
            logger.error(f"Error persisting user analytics: {e}")

    def record_llm_call(
        self,
        provider: str,
        model: str,
        success: bool,
        latency_ms: float,
        cost_usd: float = 0.0,
        tokens: int = 0,
        error_type: Optional[str] = None,
        quality_score: float = 0.5
    ) -> None:
        """Record LLM provider call"""
        llm_id = f"{provider}:{model}"

        if llm_id not in self._llm_cache:
            self._llm_cache[llm_id] = LLMMetric(
                provider=provider,
                model=model,
                total_calls=0,
                successful_calls=0,
                avg_latency_ms=0.0,
                avg_cost_usd=0.0,
                quality_score=0.5,
                error_types={},
                token_usage_total=0
            )

        metric = self._llm_cache[llm_id]
        n = metric.total_calls + 1

        # Update metrics
        metric.avg_latency_ms = (
            (metric.avg_latency_ms * (n - 1) + latency_ms) / n
        )
        metric.avg_cost_usd = (
            (metric.avg_cost_usd * (n - 1) + cost_usd) / n
        )
        metric.total_calls = n
        if success:
            metric.successful_calls += 1

        metric.quality_score = (
            (metric.quality_score * (n - 1) + quality_score) / n
        )

        if error_type:
            metric.error_types[error_type] = metric.error_types.get(error_type, 0) + 1

        metric.token_usage_total += tokens

        self._persist_llm_metric(metric)

    def _persist_llm_metric(self, metric: LLMMetric) -> None:
        """Persist LLM metric to database"""
        try:
            llm_id = f"{metric.provider}:{metric.model}"
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO llm_metrics
                    (id, provider, model, total_calls, successful_calls,
                     avg_latency_ms, avg_cost_usd, quality_score, error_types,
                     token_usage_total, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (llm_id, metric.provider, metric.model, metric.total_calls,
                      metric.successful_calls, metric.avg_latency_ms, metric.avg_cost_usd,
                      metric.quality_score, json.dumps(metric.error_types),
                      metric.token_usage_total, time.time()))
                conn.commit()
        except Exception as e:
            logger.error(f"Error persisting LLM metric: {e}")

    def get_tool_analytics(self, tool: str) -> Optional[ToolAnalytic]:
        """Get analytics for specific tool"""
        return self._tool_cache.get(tool)

    def get_all_tool_analytics(self) -> Dict[str, ToolAnalytic]:
        """Get analytics for all tools"""
        return self._tool_cache.copy()

    def get_user_analytics(self, user_id: str) -> Optional[UserAnalytic]:
        """Get analytics for specific user"""
        return self._user_cache.get(user_id)

    def get_llm_metrics(self, provider: Optional[str] = None) -> Dict[str, LLMMetric]:
        """Get LLM metrics, optionally filtered by provider"""
        if provider is None:
            return self._llm_cache.copy()
        return {
            k: v for k, v in self._llm_cache.items()
            if v.provider.lower() == provider.lower()
        }

    def generate_insights(self) -> Dict[str, Any]:
        """Generate AI-driven recommendations"""
        insights = {
            "timestamp": datetime.now().isoformat(),
            "recommendations": [],
            "warnings": [],
            "opportunities": []
        }

        # Tool recommendations
        for tool_name, analytic in self._tool_cache.items():
            if analytic.total_calls >= 10:
                if analytic.reliability_score < 0.7:
                    insights["warnings"].append({
                        "type": "low_reliability",
                        "tool": tool_name,
                        "reliability": f"{analytic.reliability_score:.1%}",
                        "recommendation": f"Araştır: {tool_name} düşük başarı oranı gösteriyor"
                    })

                if analytic.avg_complexity > 0.7 and analytic.reliability_score > 0.8:
                    insights["opportunities"].append({
                        "type": "high_complexity_success",
                        "tool": tool_name,
                        "complexity": f"{analytic.avg_complexity:.1f}",
                        "recommendation": f"Başarılı: {tool_name} karmaşık görevlerde başarılı"
                    })

        # LLM provider recommendations
        sorted_llms = sorted(
            self._llm_cache.values(),
            key=lambda x: (x.quality_score / x.avg_latency_ms if x.avg_latency_ms > 0 else 0),
            reverse=True
        )

        if sorted_llms:
            best_llm = sorted_llms[0]
            insights["recommendations"].append({
                "type": "best_llm",
                "provider": best_llm.provider,
                "model": best_llm.model,
                "quality": f"{best_llm.quality_score:.1f}",
                "latency": f"{best_llm.avg_latency_ms:.0f}ms",
                "recommendation": f"Önerilen: {best_llm.provider}/{best_llm.model} en iyi kalite/hız"
            })

        # User learning insights
        for user_id, analytic in self._user_cache.items():
            if analytic.learning_rate > 0.1:
                insights["opportunities"].append({
                    "type": "user_learning",
                    "user_id": user_id,
                    "learning_rate": f"{analytic.learning_rate:.1f}",
                    "recommendation": f"Kullanıcı {user_id} hızlı öğreniyor, karmaşıklık artırılabilir"
                })

        return insights

    def get_dashboard_metrics(self) -> Dict[str, Any]:
        """Get dashboard-ready metrics"""
        total_executions = len(self._execution_cache)
        successful = sum(1 for m in self._execution_cache if m.success)
        success_rate = (successful / total_executions * 100) if total_executions > 0 else 0

        avg_latency = (
            sum(m.duration_ms for m in self._execution_cache) / total_executions
            if total_executions > 0 else 0
        )

        total_cost = sum(m.avg_cost_usd for m in self._llm_cache.values())
        avg_quality = (
            sum(m.quality_score for m in self._llm_cache.values()) / len(self._llm_cache)
            if self._llm_cache else 0.5
        )

        return {
            "execution_metrics": {
                "total_executions": total_executions,
                "success_rate": f"{success_rate:.1f}%",
                "avg_latency_ms": f"{avg_latency:.0f}",
                "successful_calls": successful
            },
            "tool_metrics": {
                "total_tools": len(self._tool_cache),
                "avg_reliability": f"{(sum(t.reliability_score for t in self._tool_cache.values()) / len(self._tool_cache) if self._tool_cache else 0.5):.1f}",
                "top_tool": max(self._tool_cache.values(), key=lambda x: x.total_calls).tool_name if self._tool_cache else None
            },
            "user_metrics": {
                "total_users": len(self._user_cache),
                "avg_learning_rate": f"{(sum(u.learning_rate for u in self._user_cache.values()) / len(self._user_cache) if self._user_cache else 0.5):.1f}"
            },
            "llm_metrics": {
                "total_providers": len(self._llm_cache),
                "avg_quality_score": f"{avg_quality:.1f}",
                "total_cost": f"${total_cost:.2f}"
            }
        }


# Singleton instance
_analytics_engine: Optional[AnalyticsEngine] = None


def get_analytics_engine() -> AnalyticsEngine:
    """Get or create analytics engine instance"""
    global _analytics_engine
    if _analytics_engine is None:
        _analytics_engine = AnalyticsEngine()
    return _analytics_engine
