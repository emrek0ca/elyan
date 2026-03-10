"""
Elyan Episodic Memory — Event-based narrative memory.

Stores interactions as discrete events with timestamp, importance, and type.
Useful for tracking project milestones and user preferences over time.
"""

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("episodic_memory")

def _default_episodic_db_path() -> Path:
    return resolve_elyan_data_dir() / "memory" / "episodic.db"


DB_PATH = _default_episodic_db_path()
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

class EpisodicMemory:
    """Manages event-based memory storage and retrieval."""

    def __init__(self):
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                importance INTEGER DEFAULT 1,
                metadata TEXT
            )
        """)
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_user_time ON events(user_id, timestamp)")
        self.conn.commit()

    async def record_event(self, user_id: str, event_type: str, content: str, metadata: Dict = None, importance: int = 1):
        """Store a new event."""
        try:
            self.conn.execute(
                "INSERT INTO events (user_id, timestamp, event_type, content, importance, metadata) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, time.time(), event_type, content, importance, json.dumps(metadata) if metadata else None)
            )
            self.conn.commit()
        except Exception as e:
            logger.error(f"Failed to record event: {e}")

    async def search_events(self, user_id: str, query: str = None, limit: int = 10) -> List[Dict]:
        """Retrieve recent events for a user, optionally filtered by keyword."""
        try:
            if query:
                cursor = self.conn.execute(
                    "SELECT timestamp, event_type, content, importance, metadata FROM events "
                    "WHERE user_id = ? AND content LIKE ? ORDER BY timestamp DESC LIMIT ?",
                    (user_id, f"%{query}%", limit)
                )
            else:
                cursor = self.conn.execute(
                    "SELECT timestamp, event_type, content, importance, metadata FROM events "
                    "WHERE user_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (user_id, limit)
                )
            
            rows = cursor.fetchall()
            return [
                {
                    "timestamp": r[0],
                    "type": r[1],
                    "content": r[2],
                    "importance": r[3],
                    "metadata": json.loads(r[4]) if r[4] else {}
                } for r in rows
            ]
        except Exception as e:
            logger.error(f"Failed to search events: {e}")
            return []

    async def get_summary(self, user_id: str, last_n_hours: int = 24) -> str:
        """Create a textual summary of recent events for LLM consumption."""
        events = await self.search_events(user_id, limit=20)
        if not events:
            return "No recent episodic events."
        
        summary_lines = ["Recent Events:"]
        for e in reversed(events):
            t_str = time.strftime("%H:%M", time.localtime(e["timestamp"]))
            summary_lines.append(f"- [{t_str}] {e['type']}: {e['content'][:100]}")
            
        return "\n".join(summary_lines)

    async def clear(self, user_id: str):
        """Wipe user data."""
        self.conn.execute("DELETE FROM events WHERE user_id = ?", (user_id,))
        self.conn.commit()

# Global instance
episodic_memory = EpisodicMemory()
