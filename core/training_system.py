"""
Training System - Teaching Elyan Like a Child

Progressive learning approach:
1. Start with exact matches (high confidence)
2. Advance to fuzzy matching (medium confidence)
3. Semantic understanding (low confidence, needs LLM)
4. Reward successes, learn from failures
5. Personalize over time
6. Meta-learning (improve learning itself)

Turkish/English support with progression tracking.
"""

import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from utils.logger import get_logger

logger = get_logger("training_system")


class LearningLevel(Enum):
    """Stages of learning"""
    BEGINNER = 1       # Exact matches only, high confidence
    INTERMEDIATE = 2   # Fuzzy matching, medium confidence
    ADVANCED = 3       # Semantic understanding, low confidence
    EXPERT = 4         # Complex reasoning, autonomous


class ConfidenceLevel(Enum):
    """Confidence in decision"""
    VERY_HIGH = 0.9
    HIGH = 0.75
    MEDIUM = 0.5
    LOW = 0.25
    VERY_LOW = 0.1


@dataclass
class TrainingExample:
    """Example for training"""
    input_text: str
    expected_output: str
    intent: str
    success: bool
    timestamp: float
    feedback: Optional[str] = None
    confidence: float = 0.5


@dataclass
class Concept:
    """Learned concept"""
    name: str
    definition: str
    examples: List[str]
    counterexamples: List[str]
    related_concepts: List[str]
    confidence: float
    times_used: int = 0
    times_correct: int = 0


@dataclass
class KnowledgeBaseEntry:
    """Entry in knowledge base"""
    pattern: str
    action: str
    confidence: float
    times_used: int
    success_rate: float
    learning_level: LearningLevel


@dataclass
class ProgressMilestone:
    """Learning progress milestone"""
    name: str
    description: str
    achieved: bool
    achievement_date: Optional[datetime]
    requirements: Dict[str, float]  # metric -> threshold


class ConceptProgression:
    """Progressive concept learning"""

    def __init__(self):
        self.concepts: Dict[str, Concept] = {}
        self._load_concepts()

    def _load_concepts(self) -> None:
        """Load concept definitions"""
        self.concepts = {
            "greeting": Concept(
                name="greeting",
                definition="Casual conversation start",
                examples=["hello", "hi", "merhaba", "hey"],
                counterexamples=["goodbye", "bye", "exit"],
                related_concepts=["politeness", "conversation"],
                confidence=0.95
            ),
            "command": Concept(
                name="command",
                definition="Instruction to perform action",
                examples=["open", "create", "delete", "run"],
                counterexamples=["hello", "how are you", "thanks"],
                related_concepts=["action", "task"],
                confidence=0.9
            ),
            "question": Concept(
                name="question",
                definition="Request for information",
                examples=["what is", "how do", "why", "tell me about"],
                counterexamples=["I think", "It seems", "I know"],
                related_concepts=["inquiry", "information_seeking"],
                confidence=0.85
            ),
        }

    def is_concept_known(self, concept_name: str, confidence_threshold: float = 0.7) -> bool:
        """Check if concept is known above threshold"""
        if concept_name not in self.concepts:
            return False
        return self.concepts[concept_name].confidence >= confidence_threshold

    def get_concept(self, concept_name: str) -> Optional[Concept]:
        """Get concept by name"""
        return self.concepts.get(concept_name)

    def learn_concept(self, concept: Concept) -> None:
        """Learn new concept"""
        self.concepts[concept.name] = concept
        logger.info(f"Learned concept: {concept.name}")


class RewardSystem:
    """Positive reinforcement system"""

    def __init__(self):
        self.reward_history: List[Tuple[datetime, str, float]] = []
        self.total_rewards: float = 0.0
        self.reward_multiplier: float = 1.0

    def reward_success(
        self,
        action: str,
        magnitude: float = 1.0
    ) -> None:
        """Reward successful action"""
        reward = magnitude * self.reward_multiplier
        self.reward_history.append((datetime.now(), action, reward))
        self.total_rewards += reward

        # Increase multiplier for consecutive successes
        if len(self.reward_history) >= 2:
            recent = self.reward_history[-2:]
            if all(r[2] > 0 for r in recent):
                self.reward_multiplier = min(2.0, self.reward_multiplier * 1.1)

        logger.debug(f"Reward: {action} (+{reward:.2f}, total: {self.total_rewards:.2f})")

    def penalize_failure(self, action: str, magnitude: float = 0.5) -> None:
        """Penalize failed action"""
        penalty = -magnitude * self.reward_multiplier
        self.reward_history.append((datetime.now(), action, penalty))
        self.total_rewards += penalty

        # Decrease multiplier for consecutive failures
        self.reward_multiplier = max(0.5, self.reward_multiplier * 0.9)

        logger.debug(f"Penalty: {action} ({penalty:.2f}, total: {self.total_rewards:.2f})")

    def get_recent_rewards(self, hours: int = 24) -> float:
        """Get total rewards from last N hours"""
        cutoff = datetime.now() - timedelta(hours=hours)
        return sum(
            r[2] for r in self.reward_history
            if r[0] > cutoff
        )


class FeedbackLoop:
    """Learning from corrections and feedback"""

    def __init__(self):
        self.corrections: List[Dict[str, Any]] = []
        self.patterns_learned_from_feedback: Dict[str, int] = {}

    def record_correction(
        self,
        user_input: str,
        bot_output: str,
        correct_output: str,
        intent: str
    ) -> None:
        """Record user correction"""
        correction = {
            "timestamp": datetime.now(),
            "user_input": user_input,
            "bot_output": bot_output,
            "correct_output": correct_output,
            "intent": intent,
            "processed": False
        }
        self.corrections.append(correction)
        logger.info(f"Correction recorded for intent: {intent}")

    def process_corrections(self) -> List[TrainingExample]:
        """Extract training examples from corrections"""
        training_examples = []

        for correction in self.corrections:
            if correction["processed"]:
                continue

            example = TrainingExample(
                input_text=correction["user_input"],
                expected_output=correction["correct_output"],
                intent=correction["intent"],
                success=True,
                timestamp=time.time(),
                feedback=f"Corrected from: {correction['bot_output']}"
            )
            training_examples.append(example)
            correction["processed"] = True

            pattern = correction["intent"]
            self.patterns_learned_from_feedback[pattern] = (
                self.patterns_learned_from_feedback.get(pattern, 0) + 1
            )

        return training_examples


class ProgressTracking:
    """Track learning progress and milestones"""

    def __init__(self):
        self.milestones: Dict[str, ProgressMilestone] = {}
        self.metrics: Dict[str, float] = {}
        self._initialize_milestones()

    def _initialize_milestones(self) -> None:
        """Initialize milestone definitions"""
        self.milestones = {
            "first_success": ProgressMilestone(
                name="first_success",
                description="First successful command",
                achieved=False,
                achievement_date=None,
                requirements={"total_calls": 1, "success_rate": 1.0}
            ),
            "10_successes": ProgressMilestone(
                name="10_successes",
                description="10 successful commands",
                achieved=False,
                achievement_date=None,
                requirements={"total_calls": 10, "success_rate": 0.8}
            ),
            "expert_level": ProgressMilestone(
                name="expert_level",
                description="Expert level (90% success)",
                achieved=False,
                achievement_date=None,
                requirements={"total_calls": 50, "success_rate": 0.9}
            ),
            "personalization": ProgressMilestone(
                name="personalization",
                description="Learned user preferences",
                achieved=False,
                achievement_date=None,
                requirements={"distinct_intents": 5, "confidence": 0.7}
            ),
        }

    def check_milestones(self, metrics: Dict[str, float]) -> List[str]:
        """Check if any milestones are achieved"""
        achieved = []

        for milestone_name, milestone in self.milestones.items():
            if milestone.achieved:
                continue

            # Check all requirements
            all_met = all(
                metrics.get(key, 0) >= threshold
                for key, threshold in milestone.requirements.items()
            )

            if all_met:
                milestone.achieved = True
                milestone.achievement_date = datetime.now()
                achieved.append(milestone_name)
                logger.info(f"Milestone achieved: {milestone_name}")

        return achieved

    def get_progress_percentage(self) -> float:
        """Get overall progress as percentage"""
        if not self.milestones:
            return 0.0
        achieved = sum(1 for m in self.milestones.values() if m.achieved)
        return (achieved / len(self.milestones)) * 100


class ChildLearningModel:
    """Like training a child - progressive, rewarding, adaptive"""

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            db_path = Path.home() / ".elyan" / "training.db"

        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Learning components
        self.concept_progression = ConceptProgression()
        self.reward_system = RewardSystem()
        self.feedback_loop = FeedbackLoop()
        self.progress_tracking = ProgressTracking()

        # Knowledge base
        self.knowledge_base: Dict[str, KnowledgeBaseEntry] = {}
        self.learning_level = LearningLevel.BEGINNER
        self.current_confidence: float = 0.5

        self._initialize_database()
        self._load_knowledge_base()

        logger.info(f"Child Learning Model initialized: {self.db_path}")

    def _initialize_database(self) -> None:
        """Initialize database"""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS training_examples (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    input_text TEXT NOT NULL,
                    expected_output TEXT NOT NULL,
                    intent TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    feedback TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS knowledge_base (
                    pattern TEXT PRIMARY KEY,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    times_used INTEGER DEFAULT 0,
                    success_rate REAL DEFAULT 0.5,
                    learning_level INTEGER DEFAULT 1,
                    last_updated REAL NOT NULL
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    input_text TEXT,
                    bot_output TEXT,
                    correct_output TEXT,
                    intent TEXT,
                    processed INTEGER DEFAULT 0
                )
            """)

            conn.commit()

    def _load_knowledge_base(self) -> None:
        """Load knowledge base"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.execute("SELECT * FROM knowledge_base")
                for row in cursor:
                    entry = KnowledgeBaseEntry(
                        pattern=row[0],
                        action=row[1],
                        confidence=row[2],
                        times_used=row[3],
                        success_rate=row[4],
                        learning_level=LearningLevel(row[5])
                    )
                    self.knowledge_base[row[0]] = entry
            logger.info(f"Loaded {len(self.knowledge_base)} patterns from knowledge base")
        except Exception as e:
            logger.error(f"Error loading knowledge base: {e}")

    def learn_from_example(self, example: TrainingExample) -> None:
        """Learn from training example"""
        # Record in database
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT INTO training_examples
                    (timestamp, input_text, expected_output, intent, success, feedback)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (example.timestamp, example.input_text, example.expected_output,
                      example.intent, example.success, example.feedback))
                conn.commit()
        except Exception as e:
            logger.error(f"Error recording training example: {e}")

        # Update knowledge base
        if example.success:
            self.reward_system.reward_success(example.intent)
            pattern = example.input_text[:50]  # Use prefix as pattern

            if pattern not in self.knowledge_base:
                self.knowledge_base[pattern] = KnowledgeBaseEntry(
                    pattern=pattern,
                    action=example.expected_output,
                    confidence=0.6,
                    times_used=1,
                    success_rate=1.0,
                    learning_level=LearningLevel.BEGINNER
                )
            else:
                entry = self.knowledge_base[pattern]
                entry.times_used += 1
                entry.success_rate = (
                    (entry.success_rate * (entry.times_used - 1) + 1.0) /
                    entry.times_used
                )
                entry.confidence = min(0.95, entry.confidence + 0.05)

            self._persist_knowledge_entry(pattern, self.knowledge_base[pattern])
        else:
            self.reward_system.penalize_failure(example.intent)

    def get_prediction(self, input_text: str) -> Tuple[Optional[str], float]:
        """Get prediction with confidence"""
        # Try exact match first (highest confidence)
        pattern_key = input_text[:50]
        if pattern_key in self.knowledge_base:
            entry = self.knowledge_base[pattern_key]
            return entry.action, entry.confidence

        # Try fuzzy match (medium confidence)
        for pattern, entry in self.knowledge_base.items():
            if self._fuzzy_match(input_text, pattern):
                return entry.action, entry.confidence * 0.8

        # No match found
        return None, ConfidenceLevel.VERY_LOW.value

    def _fuzzy_match(self, text: str, pattern: str) -> bool:
        """Simple fuzzy matching"""
        words_text = set(text.lower().split())
        words_pattern = set(pattern.lower().split())
        overlap = len(words_text & words_pattern)
        return overlap >= len(words_pattern) * 0.5

    def _persist_knowledge_entry(self, pattern: str, entry: KnowledgeBaseEntry) -> None:
        """Save knowledge entry to database"""
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO knowledge_base
                    (pattern, action, confidence, times_used, success_rate, learning_level, last_updated)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (pattern, entry.action, entry.confidence, entry.times_used,
                      entry.success_rate, entry.learning_level.value, time.time()))
                conn.commit()
        except Exception as e:
            logger.error(f"Error persisting knowledge entry: {e}")

    def advance_learning_level(self) -> None:
        """Advance to next learning level"""
        current = self.learning_level.value
        if current < LearningLevel.EXPERT.value:
            self.learning_level = LearningLevel(current + 1)
            logger.info(f"Advanced to learning level: {self.learning_level.name}")

    def get_learning_metrics(self) -> Dict[str, Any]:
        """Get learning metrics and progress"""
        total_patterns = len(self.knowledge_base)
        avg_confidence = (
            sum(e.confidence for e in self.knowledge_base.values()) / total_patterns
            if total_patterns > 0 else 0.0
        )

        avg_success_rate = (
            sum(e.success_rate for e in self.knowledge_base.values()) / total_patterns
            if total_patterns > 0 else 0.0
        )

        return {
            "learning_level": self.learning_level.name,
            "total_patterns": total_patterns,
            "avg_confidence": f"{avg_confidence:.2f}",
            "avg_success_rate": f"{avg_success_rate:.1%}",
            "reward_score": f"{self.reward_system.total_rewards:.1f}",
            "progress": f"{self.progress_tracking.get_progress_percentage():.0f}%",
            "concepts_known": len([c for c in self.concept_progression.concepts.values()
                                  if c.confidence > 0.7])
        }


# Singleton instance
_training_system: Optional[ChildLearningModel] = None


def get_training_system() -> ChildLearningModel:
    """Get or create training system instance"""
    global _training_system
    if _training_system is None:
        _training_system = ChildLearningModel()
    return _training_system
