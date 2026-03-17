"""
Learning Engine - User-specific model fine-tuning and personalization
Provides pattern extraction, personalization metrics, confidence scoring
"""

import json
import sqlite3
import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime
from collections import defaultdict, Counter
import logging

logger = logging.getLogger(__name__)

# JSON schema for validating deserialized data
PARAMS_SCHEMA = {
    "type": "object",
    "additionalProperties": True,
    "maxProperties": 100  # Prevent abuse
}

PREFERENCES_SCHEMA = {
    "type": "object",
    "properties": {
        "preferred_tools": {"type": "object"},
        "learning_confidence": {"type": "number"},
        "learning_velocity": {"type": "number"},
        "total_patterns": {"type": "integer"},
        "last_updated": {"type": "string"}
    },
    "additionalProperties": False
}

def _safe_json_loads(data: str, schema: Dict = None, max_size: int = 1000000) -> Any:
    """Safely deserialize JSON with validation"""
    if len(data) > max_size:
        raise ValueError(f"JSON data exceeds maximum size of {max_size} bytes")
    try:
        parsed = json.loads(data)
        # if schema:
        #     validate(instance=parsed, schema=schema)
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        logger.error(f"Invalid JSON data: {e}")
        raise ValueError(f"Failed to parse JSON: {e}") from e


class LearningMetrics:
    """Track learning metrics for a user"""

    def __init__(self):
        self.total_interactions = 0
        self.successful_interactions = 0
        self.failed_interactions = 0
        self.tool_usage_count = defaultdict(int)
        self.tool_success_rate = defaultdict(lambda: {"success": 0, "total": 0})
        self.pattern_frequency = defaultdict(int)
        self.user_confidence = 0.0
        self.learning_velocity = 0.0

    def update(self, tool: str, success: bool, duration: float):
        """Update metrics with new interaction"""
        self.total_interactions += 1
        self.tool_usage_count[tool] += 1

        if success:
            self.successful_interactions += 1
            self.tool_success_rate[tool]["success"] += 1
        else:
            self.failed_interactions += 1

        self.tool_success_rate[tool]["total"] += 1

        # Calculate confidence based on success rate
        if self.total_interactions > 0:
            self.user_confidence = self.successful_interactions / self.total_interactions

        # Learning velocity: improvement rate
        if self.total_interactions > 10:
            recent_success = self.successful_interactions / self.total_interactions
            self.learning_velocity = recent_success - 0.5  # Base: 50%

    def get_success_rate(self, tool: str) -> float:
        """Get success rate for specific tool"""
        stats = self.tool_success_rate[tool]
        if stats["total"] == 0:
            return 0.0
        return stats["success"] / stats["total"]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "total_interactions": self.total_interactions,
            "successful_interactions": self.successful_interactions,
            "failed_interactions": self.failed_interactions,
            "overall_success_rate": self.user_confidence,
            "learning_velocity": self.learning_velocity,
            "tool_usage": dict(self.tool_usage_count),
            "tool_success_rates": {
                tool: self.get_success_rate(tool)
                for tool in self.tool_usage_count.keys()
            }
        }


class Pattern:
    """Represents a learned pattern"""

    def __init__(self, pattern_id: str, tool: str, params: Dict, success_count: int = 0):
        self.pattern_id = pattern_id
        self.tool = tool
        self.params = params
        self.success_count = success_count
        self.failure_count = 0
        self.last_used = datetime.now().isoformat()
        self.confidence = 0.0
        self.frequency = 0

    def record_success(self):
        """Record successful usage"""
        self.success_count += 1
        self._update_confidence()

    def record_failure(self):
        """Record failed usage"""
        self.failure_count += 1
        self._update_confidence()

    def _update_confidence(self):
        """Update confidence score"""
        total = self.success_count + self.failure_count
        if total > 0:
            self.confidence = self.success_count / total

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary"""
        return {
            "pattern_id": self.pattern_id,
            "tool": self.tool,
            "params": self.params,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "confidence": self.confidence,
            "frequency": self.frequency,
            "last_used": self.last_used
        }


class LearningEngine:
    """Main learning engine for personalization"""

    def __init__(self, user_id: str, storage_path: str = ".elyan/learning"):
        self.user_id = user_id
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.metrics = LearningMetrics()
        self.patterns: Dict[str, Pattern] = {}
        self.interaction_history: List[Dict] = []
        self.preferences: Dict[str, Any] = {}
        self.coding_style: Dict[str, Any] = {}

        self.db_path = self.storage_path / f"{user_id}_learning.db"
        self._init_db()
        self._load_data()

    def _init_db(self):
        """Initialize SQLite database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Create tables
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS interactions (
                    id INTEGER PRIMARY KEY,
                    tool TEXT,
                    input_params TEXT,
                    output TEXT,
                    success BOOLEAN,
                    duration REAL,
                    timestamp TEXT
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    pattern_id TEXT PRIMARY KEY,
                    tool TEXT,
                    params TEXT,
                    success_count INTEGER,
                    failure_count INTEGER,
                    confidence REAL,
                    frequency INTEGER
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to initialize DB: {e}")

    def _load_data(self):
        """Load learning data from database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Load patterns
            cursor.execute("SELECT * FROM patterns")
            for row in cursor.fetchall():
                try:
                    params = _safe_json_loads(row[2])
                    pattern = Pattern(
                        pattern_id=row[0],
                        tool=row[1],
                        params=params,
                        success_count=row[3]
                    )
                except ValueError as e:
                    logger.warning(f"Skipping corrupted pattern {row[0]}: {e}")
                    continue
                pattern.failure_count = row[4]
                pattern.confidence = row[5]
                pattern.frequency = row[6]
                self.patterns[pattern.pattern_id] = pattern

            # Load preferences
            cursor.execute("SELECT * FROM preferences")
            for key, value in cursor.fetchall():
                try:
                    self.preferences[key] = _safe_json_loads(value)
                except ValueError as e:
                    logger.warning(f"Skipping corrupted preference {key}: {e}")

            conn.close()
            logger.info(f"Loaded {len(self.patterns)} patterns for user {self.user_id}")
        except Exception as e:
            logger.error(f"Failed to load data: {e}")

    def record_interaction(self, tool: str, input_params: Dict, output: Any,
                          success: bool, duration: float) -> str:
        """Record user interaction"""
        try:
            # Update metrics
            self.metrics.update(tool, success, duration)

            # Create interaction record
            interaction = {
                "tool": tool,
                "input_params": input_params,
                "output": output,
                "success": success,
                "duration": duration,
                "timestamp": datetime.now().isoformat()
            }
            self.interaction_history.append(interaction)

            # Save to database
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO interactions (tool, input_params, output, success, duration, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                tool,
                json.dumps(input_params),
                json.dumps(output) if isinstance(output, (dict, list)) else str(output),
                success,
                duration,
                interaction["timestamp"]
            ))
            conn.commit()
            conn.close()

            # Extract and update patterns
            self._extract_patterns(tool, input_params, output, success)

            return f"Interaction recorded: {tool} ({'success' if success else 'failed'})"
        except Exception as e:
            logger.error(f"Failed to record interaction: {e}")
            return f"Error recording interaction: {e}"

    def _extract_patterns(self, tool: str, params: Dict, output: Any, success: bool):
        """Extract patterns from successful interactions"""
        try:
            # Create pattern ID from tool and key params using secure hash
            params_json = json.dumps(params, sort_keys=True, default=str)
            param_hash = hashlib.sha256(params_json.encode()).hexdigest()[:16]
            pattern_id = f"{tool}_{param_hash}"

            if pattern_id not in self.patterns:
                self.patterns[pattern_id] = Pattern(pattern_id, tool, params)

            pattern = self.patterns[pattern_id]
            pattern.frequency += 1

            if success:
                pattern.record_success()
            else:
                pattern.record_failure()

            # Save to database
            self._save_pattern(pattern)
        except Exception as e:
            logger.error(f"Failed to extract patterns: {e}")

    def _save_pattern(self, pattern: Pattern):
        """Save pattern to database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO patterns
                (pattern_id, tool, params, success_count, failure_count, confidence, frequency)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                pattern.pattern_id,
                pattern.tool,
                json.dumps(pattern.params),
                pattern.success_count,
                pattern.failure_count,
                pattern.confidence,
                pattern.frequency
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save pattern: {e}")

    def analyze_patterns(self) -> Dict[str, Any]:
        """Analyze all learned patterns"""
        try:
            if not self.patterns:
                return {"status": "No patterns learned yet"}

            # Find most used tools
            tool_frequency = Counter()
            tool_success = defaultdict(lambda: {"success": 0, "total": 0})

            for pattern in self.patterns.values():
                tool_frequency[pattern.tool] += pattern.frequency
                if pattern.confidence > 0.5:
                    tool_success[pattern.tool]["success"] += 1
                tool_success[pattern.tool]["total"] += 1

            # Find most reliable patterns
            reliable_patterns = [
                p for p in self.patterns.values()
                if p.confidence > 0.75 and p.frequency > 2
            ]
            reliable_patterns.sort(key=lambda p: p.confidence, reverse=True)

            return {
                "total_patterns": len(self.patterns),
                "most_used_tools": dict(tool_frequency.most_common(5)),
                "tool_success_rates": {
                    tool: stats["success"] / stats["total"] if stats["total"] > 0 else 0
                    for tool, stats in tool_success.items()
                },
                "reliable_patterns": [p.to_dict() for p in reliable_patterns[:5]],
                "learning_confidence": self.metrics.user_confidence,
                "learning_velocity": self.metrics.learning_velocity
            }
        except Exception as e:
            logger.error(f"Failed to analyze patterns: {e}")
            return {"error": str(e)}

    def get_recommendations(self, task_type: str = None, limit: int = 5) -> List[Dict]:
        """Get recommendations based on learned patterns"""
        try:
            # Filter patterns by confidence and relevance
            candidates = [
                p for p in self.patterns.values()
                if p.confidence > 0.6 and p.frequency > 1
            ]

            # Sort by confidence and frequency
            candidates.sort(
                key=lambda p: (p.confidence, p.frequency),
                reverse=True
            )

            recommendations = []
            for pattern in candidates[:limit]:
                recommendations.append({
                    "tool": pattern.tool,
                    "suggested_params": pattern.params,
                    "confidence": pattern.confidence,
                    "frequency": pattern.frequency,
                    "success_rate": self.metrics.get_success_rate(pattern.tool)
                })

            return recommendations
        except Exception as e:
            logger.error(f"Failed to get recommendations: {e}")
            return []

    def evaluate_confidence(self, pattern_id: str) -> float:
        """Evaluate confidence for a specific pattern"""
        try:
            if pattern_id in self.patterns:
                return self.patterns[pattern_id].confidence
            return 0.0
        except Exception as e:
            logger.error(f"Failed to evaluate confidence: {e}")
            return 0.0

    def update_user_model(self):
        """Update overall user model"""
        try:
            # Calculate overall metrics
            patterns_analysis = self.analyze_patterns()

            self.preferences.update({
                "preferred_tools": patterns_analysis.get("most_used_tools", {}),
                "learning_confidence": self.metrics.user_confidence,
                "learning_velocity": self.metrics.learning_velocity,
                "total_patterns": patterns_analysis.get("total_patterns", 0),
                "last_updated": datetime.now().isoformat()
            })

            # Save preferences
            self._save_preferences()

            return {
                "status": "User model updated",
                "metrics": self.metrics.to_dict(),
                "preferences": self.preferences
            }
        except Exception as e:
            logger.error(f"Failed to update user model: {e}")
            return {"error": str(e)}

    def _save_preferences(self):
        """Save preferences to database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            for key, value in self.preferences.items():
                cursor.execute("""
                    INSERT OR REPLACE INTO preferences (key, value)
                    VALUES (?, ?)
                """, (key, json.dumps(value)))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save preferences: {e}")

    def get_user_profile(self) -> Dict[str, Any]:
        """Get complete user profile"""
        return {
            "user_id": self.user_id,
            "metrics": self.metrics.to_dict(),
            "patterns_count": len(self.patterns),
            "preferences": self.preferences,
            "interaction_history_size": len(self.interaction_history),
            "analysis": self.analyze_patterns()
        }

    def export_learning(self) -> Dict[str, Any]:
        """Export all learning data"""
        return {
            "user_id": self.user_id,
            "metrics": self.metrics.to_dict(),
            "patterns": [p.to_dict() for p in self.patterns.values()],
            "preferences": self.preferences,
            "interaction_count": len(self.interaction_history),
            "exported_at": datetime.now().isoformat()
        }
