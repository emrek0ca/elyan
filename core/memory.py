"""
Memory System for CDACS Bot

Provides:
- Conversation history storage
- User preference learning
- Task execution tracking
- Semantic search over history
"""

import sqlite3
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List, Dict
from utils.logger import get_logger

logger = get_logger("memory")


class Memory:
    """
    Memory system for storing and retrieving conversation history,
    user preferences, and task execution results
    """
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            # Default location
            config_dir = Path.home() / ".config" / "cdacs-bot"
            config_dir.mkdir(parents=True, exist_ok=True)
            db_path = str(config_dir / "memory.db")
        
        self.db_path = db_path
        self.conn = None
        self._initialize_db()
    
    def _initialize_db(self):
        """Initialize database with required tables"""
        try:
            self.conn = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
            try:
                self.conn.execute("PRAGMA journal_mode=WAL")
            except sqlite3.OperationalError:
                pass  # WAL mode not available if DB is in use, timeout handles concurrency
            
            cursor = self.conn.cursor()
            
            # Conversations table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    timestamp TEXT NOT NULL,
                    user_message TEXT NOT NULL,
                    bot_response TEXT,
                    action TEXT,
                    success BOOLEAN,
                    metadata TEXT
                )
            """)
            
            # User preferences table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS preferences (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    learned_at TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5,
                    UNIQUE(user_id, key)
                )
            """)
            
            # Task history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    timestamp TEXT NOT NULL,
                    goal TEXT NOT NULL,
                    plan TEXT,
                    outcome TEXT,
                    duration REAL,
                    success BOOLEAN,
                    error TEXT
                )
            """)
            
            # Knowledge graph table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS knowledge (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    value TEXT NOT NULL,
                    source TEXT,
                    timestamp TEXT NOT NULL,
                    confidence REAL DEFAULT 0.5
                )
            """)
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_user_time ON conversations(user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pref_user ON preferences(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_user_time ON task_history(user_id, timestamp)")
            
            self.conn.commit()
            logger.info(f"Memory database initialized at {self.db_path}")
        
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise
    
    def store_conversation(self, user_id: int, user_message: str, bot_response: dict) -> int:
        """
        Store a conversation exchange
        
        Args:
            user_id: Telegram user ID
            user_message: User's message
            bot_response: Bot's response dict
        
        Returns:
            Conversation ID
        """
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO conversations (user_id, timestamp, user_message, bot_response, action, success, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                datetime.now().isoformat(),
                user_message,
                json.dumps(bot_response),
                bot_response.get("action", "unknown"),
                bot_response.get("success", True),
                json.dumps(bot_response.get("metadata", {}))
            ))
            self.conn.commit()
            return cursor.lastrowid
        
        except Exception as e:
            logger.error(f"Error storing conversation: {e}")
            return -1
    
    def get_recent_conversations(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Get recent conversations for a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM conversations
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error retrieving conversations: {e}")
            return []
    
    def search_conversations(self, user_id: int, query: str, limit: int = 20) -> List[Dict]:
        """Search conversations by keyword"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM conversations
                WHERE user_id = ? AND (
                    user_message LIKE ? OR
                    bot_response LIKE ?
                )
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, f"%{query}%", f"%{query}%", limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error searching conversations: {e}")
            return []
    
    def store_preference(self, user_id: int, key: str, value: str, confidence: float = 0.8):
        """Store or update a user preference"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO preferences (user_id, key, value, learned_at, confidence)
                VALUES (?, ?, ?, ?, ?)
            """, (user_id, key, value, datetime.now().isoformat(), confidence))
            self.conn.commit()
            logger.info(f"Stored preference for user {user_id}: {key} = {value}")
        
        except Exception as e:
            logger.error(f"Error storing preference: {e}")
    
    def get_preference(self, user_id: int, key: str, default: Any = None) -> Any:
        """Get a user preference"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT value FROM preferences
                WHERE user_id = ? AND key = ?
            """, (user_id, key))
            
            row = cursor.fetchone()
            if row:
                value = row["value"]
                # Try to parse as JSON, otherwise return as string
                try:
                    return json.loads(value)
                except:
                    return value
            return default
        
        except Exception as e:
            logger.error(f"Error getting preference: {e}")
            return default
    
    def get_all_preferences(self, user_id: int) -> Dict[str, Any]:
        """Get all preferences for a user"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT key, value, confidence FROM preferences
                WHERE user_id = ?
            """, (user_id,))

            prefs = {}
            for row in cursor.fetchall():
                key = row["key"]
                value = row["value"]
                try:
                    prefs[key] = json.loads(value)
                except:
                    prefs[key] = value

            return prefs

        except Exception as e:
            logger.error(f"Error getting preferences: {e}")
            return {}

    def get_user_preferences(self, user_id: int) -> Dict[str, Any]:
        """Alias for get_all_preferences - returns all user preferences"""
        return self.get_all_preferences(user_id)
    
    def store_task(self, user_id: int, goal: str, plan: dict = None, outcome: str = None, 
                   duration: float = 0, success: bool = True, error: str = None):
        """Store task execution history"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO task_history (user_id, timestamp, goal, plan, outcome, duration, success, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                datetime.now().isoformat(),
                goal,
                json.dumps(plan) if plan else None,
                outcome,
                duration,
                success,
                error
            ))
            self.conn.commit()
        
        except Exception as e:
            logger.error(f"Error storing task: {e}")
    
    def get_task_history(self, user_id: int, limit: int = 50) -> List[Dict]:
        """Get task execution history"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM task_history
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, limit))
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error getting task history: {e}")
            return []
    
    def get_task_statistics(self, user_id: int) -> Dict[str, Any]:
        """Get task execution statistics"""
        try:
            cursor = self.conn.cursor()
            
            # Total tasks
            cursor.execute("SELECT COUNT(*) as count FROM task_history WHERE user_id = ?", (user_id,))
            total = cursor.fetchone()["count"]
            
            # Success rate
            cursor.execute("SELECT COUNT(*) as count FROM task_history WHERE user_id = ? AND success = 1", (user_id,))
            successful = cursor.fetchone()["count"]
            
            # Average duration
            cursor.execute("SELECT AVG(duration) as avg_dur FROM task_history WHERE user_id = ? AND duration > 0", (user_id,))
            avg_duration = cursor.fetchone()["avg_dur"] or 0
            
            return {
                "total_tasks": total,
                "successful_tasks": successful,
                "failed_tasks": total - successful,
                "success_rate": (successful / total * 100) if total > 0 else 0,
                "average_duration": avg_duration
            }
        
        except Exception as e:
            logger.error(f"Error getting task statistics: {e}")
            return {}
    
    def store_knowledge(self, entity: str, relation: str, value: str, 
                       source: str = None, confidence: float = 0.8):
        """Store knowledge triple"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                INSERT INTO knowledge (entity, relation, value, source, timestamp, confidence)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entity, relation, value, source, datetime.now().isoformat(), confidence))
            self.conn.commit()
        
        except Exception as e:
            logger.error(f"Error storing knowledge: {e}")
    
    def query_knowledge(self, entity: str = None, relation: str = None) -> List[Dict]:
        """Query knowledge graph"""
        try:
            cursor = self.conn.cursor()
            
            if entity and relation:
                cursor.execute("""
                    SELECT * FROM knowledge
                    WHERE entity = ? AND relation = ?
                    ORDER BY confidence DESC
                """, (entity, relation))
            elif entity:
                cursor.execute("""
                    SELECT * FROM knowledge
                    WHERE entity = ?
                    ORDER BY confidence DESC
                """, (entity,))
            elif relation:
                cursor.execute("""
                    SELECT * FROM knowledge
                    WHERE relation = ?
                    ORDER BY confidence DESC
                """, (relation,))
            else:
                cursor.execute("SELECT * FROM knowledge ORDER BY timestamp DESC LIMIT 100")
            
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        
        except Exception as e:
            logger.error(f"Error querying knowledge: {e}")
            return []
    
    def clear_user_data(self, user_id: int):
        """Clear all data for a user (for privacy/GDPR)"""
        try:
            cursor = self.conn.cursor()
            cursor.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM preferences WHERE user_id = ?", (user_id,))
            cursor.execute("DELETE FROM task_history WHERE user_id = ?", (user_id,))
            self.conn.commit()
            logger.info(f"Cleared all data for user {user_id}")
        
        except Exception as e:
            logger.error(f"Error clearing user data: {e}")
    
    def get_stats(self) -> Dict[str, Any]:
        """Get overall memory statistics"""
        try:
            cursor = self.conn.cursor()
            
            cursor.execute("SELECT COUNT(*) as count FROM conversations")
            conv_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM preferences")
            pref_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM task_history")
            task_count = cursor.fetchone()["count"]
            
            cursor.execute("SELECT COUNT(*) as count FROM knowledge")
            knowledge_count = cursor.fetchone()["count"]
            
            return {
                "conversations": conv_count,
                "preferences": pref_count,
                "tasks": task_count,
                "knowledge_items": knowledge_count,
                "database_path": self.db_path
            }
        
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Memory database connection closed")


# Global memory instance
_memory_instance = None


def get_memory() -> Memory:
    """Get or create the global memory instance"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = Memory()
    return _memory_instance
