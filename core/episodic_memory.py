"""
Episodic Memory - Session-level episode recording and pattern extraction
"""

import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass
import sqlite3
import logging

logger = logging.getLogger(__name__)


@dataclass
class Episode:
    """Represents a single episode/session"""

    episode_id: str
    session_start: str
    session_end: Optional[str]
    actions: List[Dict]
    outcomes: List[Dict]
    duration: float
    success_rate: float
    key_learnings: List[str]

    def to_dict(self) -> Dict:
        return {
            "episode_id": self.episode_id,
            "session_start": self.session_start,
            "session_end": self.session_end,
            "actions": self.actions,
            "outcomes": self.outcomes,
            "duration": self.duration,
            "success_rate": self.success_rate,
            "key_learnings": self.key_learnings
        }


class EpisodicMemory:
    """Stores and retrieves episodic memories"""

    def __init__(self, storage_path: str = ".elyan/episodic_memory"):
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        self.current_episode: Optional[Episode] = None
        self.episodes: Dict[str, Episode] = {}
        self.pattern_index: Dict[str, List[str]] = {}

        self.db_path = self.storage_path / "episodes.db"
        self._init_db()
        self._load_episodes()

    def _init_db(self):
        """Initialize database"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    episode_id TEXT PRIMARY KEY,
                    session_start TEXT,
                    session_end TEXT,
                    actions TEXT,
                    outcomes TEXT,
                    duration REAL,
                    success_rate REAL,
                    key_learnings TEXT
                )
            """)

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to init DB: {e}")

    def _load_episodes(self):
        """Load episodes from storage"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM episodes")
            for row in cursor.fetchall():
                episode = Episode(
                    episode_id=row[0],
                    session_start=row[1],
                    session_end=row[2],
                    actions=json.loads(row[3]) if row[3] else [],
                    outcomes=json.loads(row[4]) if row[4] else [],
                    duration=row[5],
                    success_rate=row[6],
                    key_learnings=json.loads(row[7]) if row[7] else []
                )
                self.episodes[episode.episode_id] = episode

            conn.close()
            logger.info(f"Loaded {len(self.episodes)} episodes")
        except Exception as e:
            logger.error(f"Failed to load episodes: {e}")

    def start_episode(self) -> str:
        """Start new episode"""
        episode_id = f"episode_{datetime.now().timestamp()}"
        self.current_episode = Episode(
            episode_id=episode_id,
            session_start=datetime.now().isoformat(),
            session_end=None,
            actions=[],
            outcomes=[],
            duration=0.0,
            success_rate=0.0,
            key_learnings=[]
        )
        return episode_id

    def record_action(self, action: str, params: Dict, success: bool):
        """Record action in current episode"""
        if not self.current_episode:
            return False

        action_record = {
            "action": action,
            "params": params,
            "success": success,
            "timestamp": datetime.now().isoformat()
        }
        self.current_episode.actions.append(action_record)
        return True

    def record_outcome(self, outcome: Dict):
        """Record outcome"""
        if not self.current_episode:
            return False

        self.current_episode.outcomes.append({
            **outcome,
            "timestamp": datetime.now().isoformat()
        })
        return True

    def end_episode(self, learnings: List[str] = None) -> str:
        """End current episode"""
        if not self.current_episode:
            return "No active episode"

        self.current_episode.session_end = datetime.now().isoformat()
        self.current_episode.key_learnings = learnings or []

        # Calculate metrics
        if self.current_episode.actions:
            successes = sum(1 for a in self.current_episode.actions if a.get("success"))
            self.current_episode.success_rate = successes / len(self.current_episode.actions)

        # Parse timestamps
        start = datetime.fromisoformat(self.current_episode.session_start)
        end = datetime.fromisoformat(self.current_episode.session_end)
        self.current_episode.duration = (end - start).total_seconds()

        # Save
        episode_id = self.current_episode.episode_id
        self.episodes[episode_id] = self.current_episode
        self._save_episode(self.current_episode)
        self.current_episode = None

        logger.info(f"Episode {episode_id} ended")
        return episode_id

    def _save_episode(self, episode: Episode):
        """Save episode to DB"""
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("""
                INSERT OR REPLACE INTO episodes
                (episode_id, session_start, session_end, actions, outcomes, duration, success_rate, key_learnings)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                episode.episode_id,
                episode.session_start,
                episode.session_end,
                json.dumps(episode.actions),
                json.dumps(episode.outcomes),
                episode.duration,
                episode.success_rate,
                json.dumps(episode.key_learnings)
            ))

            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"Failed to save episode: {e}")

    def recall_similar_episodes(self, pattern: Dict, limit: int = 5) -> List[Episode]:
        """Find similar past episodes"""
        candidates = []

        for episode in self.episodes.values():
            similarity = self._calculate_similarity(episode, pattern)
            if similarity > 0.3:
                candidates.append((similarity, episode))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in candidates[:limit]]

    def _calculate_similarity(self, episode: Episode, pattern: Dict) -> float:
        """Calculate similarity between episode and pattern"""
        score = 0.0

        if episode.actions and len(episode.actions) > 0:
            first_action = episode.actions[0].get("action", "")
            if first_action == pattern.get("action"):
                score += 0.5

        if episode.success_rate > 0.7:
            score += 0.3

        return min(1.0, score)

    def get_quick_recall(self, max_lookback: int = 5) -> List[Dict]:
        """Quickly recall recent episodes"""
        sorted_episodes = sorted(
            self.episodes.values(),
            key=lambda e: e.session_start,
            reverse=True
        )

        return [e.to_dict() for e in sorted_episodes[:max_lookback]]

    def extract_patterns(self) -> Dict[str, int]:
        """Extract common action patterns"""
        pattern_freq = {}

        for episode in self.episodes.values():
            for action in episode.actions:
                action_name = action.get("action", "unknown")
                pattern_freq[action_name] = pattern_freq.get(action_name, 0) + 1

        return pattern_freq

    def get_statistics(self) -> Dict:
        """Get episode statistics"""
        if not self.episodes:
            return {"status": "No episodes recorded"}

        success_rates = [e.success_rate for e in self.episodes.values() if e.success_rate]
        avg_success = sum(success_rates) / len(success_rates) if success_rates else 0

        return {
            "total_episodes": len(self.episodes),
            "average_success_rate": avg_success,
            "patterns_extracted": self.extract_patterns(),
            "total_actions": sum(len(e.actions) for e in self.episodes.values()),
            "total_outcomes": sum(len(e.outcomes) for e in self.episodes.values())
        }
