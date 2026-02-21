"""
Conversation Memory System

Stores and retrieves conversation history for context-aware responses.
"""

import sqlite3
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("conversation_memory")


class ConversationMemory:
    """Manages conversation history storage"""
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = str(Path.home() / ".config" / "cdacs-bot" / "conversation.db")
        
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        self._init_db()
        logger.info(f"Conversation memory initialized: {db_path}")
    
    def _init_db(self):
        """Initialize database schema"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                metadata TEXT
            )
        """)
        
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_user_timestamp 
            ON conversations(user_id, timestamp DESC)
        """)
        
        conn.commit()
        conn.close()
    
    def add_message(
        self,
        user_id: int,
        role: str,
        content: str,
        metadata: Optional[str] = None
    ):
        """
        Add message to conversation history.
        
        Args:
            user_id: Telegram user ID
            role: 'user' or 'assistant'
            content: Message content
            metadata: Optional JSON metadata
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO conversations (user_id, role, content, metadata)
                VALUES (?, ?, ?, ?)
            """, (user_id, role, content, metadata))
            
            conn.commit()
            conn.close()
            
            logger.debug(f"Added {role} message for user {user_id}")
        
        except Exception as e:
            logger.error(f"Failed to add message: {e}")
    
    def get_history(
        self,
        user_id: int,
        limit: int = 10,
        hours: int = 24
    ) -> List[Dict]:
        """
        Get recent conversation history.
        
        Args:
            user_id: Telegram user ID
            limit: Max number of messages
            hours: Only messages within last N hours
        
        Returns:
            List of {"role": str, "content": str, "timestamp": str}
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
            
            cursor.execute("""
                SELECT role, content, timestamp
                FROM conversations
                WHERE user_id = ? AND timestamp > ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (user_id, cutoff, limit))
            
            rows = cursor.fetchall()
            conn.close()
            
            # Reverse to get chronological order
            history = [
                {
                    "role": row[0],
                    "content": row[1],
                    "timestamp": row[2]
                }
                for row in reversed(rows)
            ]
            
            return history
        
        except Exception as e:
            logger.error(f"Failed to get history: {e}")
            return []
    
    def get_last_user_message(self, user_id: int) -> Optional[str]:
        """Get last user message"""
        history = self.get_history(user_id, limit=1, hours=1)
        
        for msg in reversed(history):
            if msg["role"] == "user":
                return msg["content"]
        
        return None
    
    def clear_history(self, user_id: int, hours: int = 24):
        """Clear conversation history"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if hours:
                cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
                cursor.execute("""
                    DELETE FROM conversations
                    WHERE user_id = ? AND timestamp < ?
                """, (user_id, cutoff))
            else:
                cursor.execute("""
                    DELETE FROM conversations WHERE user_id = ?
                """, (user_id,))
            
            deleted = cursor.rowcount
            conn.commit()
            conn.close()
            
            logger.info(f"Cleared {deleted} messages for user {user_id}")
        
        except Exception as e:
            logger.error(f"Failed to clear history: {e}")
    
    def get_conversation_summary(self, user_id: int, limit: int = 20) -> str:
        """Get brief conversation summary"""
        history = self.get_history(user_id, limit=limit, hours=24)
        
        if not history:
            return "No recent conversation."
        
        summary_parts = []
        for msg in history[-5:]:  # Last 5 messages
            role_emoji = "" if msg["role"] == "user" else ""
            content_preview = msg["content"][:50]
            summary_parts.append(f"{role_emoji} {content_preview}")
        
        return "\n".join(summary_parts)


# Global singleton
_conversation_memory: Optional[ConversationMemory] = None


def get_conversation_memory() -> ConversationMemory:
    """Get global conversation memory instance"""
    global _conversation_memory
    
    if _conversation_memory is None:
        _conversation_memory = ConversationMemory()
    
    return _conversation_memory
