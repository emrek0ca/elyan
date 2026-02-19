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
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, List, Dict
from utils.logger import get_logger
from .embedding_codec import serialize_embedding, deserialize_embedding

logger = get_logger("memory")
DEFAULT_USER_MEMORY_LIMIT_GB = 10.0


def _is_unwritable_db_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "readonly" in msg
        or "read-only" in msg
        or "unable to open database file" in msg
        or "permission denied" in msg
    )


def _resolve_default_db_path() -> str:
    """
    Resolve default memory DB path.
    Canonical path: ~/.elyan/memory/memory.db
    Legacy path:    ~/.config/cdacs-bot/memory.db (auto-copied if needed)
    """
    canonical_dir = Path.home() / ".elyan" / "memory"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical_db = canonical_dir / "memory.db"

    legacy_db = Path.home() / ".config" / "cdacs-bot" / "memory.db"
    if not canonical_db.exists() and legacy_db.exists():
        try:
            shutil.copy2(legacy_db, canonical_db)
            logger.info(f"Migrated legacy memory DB to {canonical_db}")
        except Exception as exc:
            logger.warning(f"Legacy memory DB migration skipped: {exc}")

    return str(canonical_db)


def _config_user_limit_gb() -> Optional[float]:
    """
    Read memory.maxUserStorageGB from ~/.elyan/elyan.json if available.
    """
    config_path = Path.home() / ".elyan" / "elyan.json"
    if not config_path.exists():
        return None
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
        memory_cfg = data.get("memory") if isinstance(data, dict) else None
        if not isinstance(memory_cfg, dict):
            return None
        raw = memory_cfg.get("maxUserStorageGB")
        if raw is None:
            return None
        gb = float(raw)
        return gb if gb > 0 else None
    except Exception:
        return None


def _default_user_limit_bytes() -> int:
    """
    Resolve per-user memory cap.

    Priority:
    1) ELYAN_MAX_USER_MEMORY_BYTES
    2) ELYAN_MAX_USER_MEMORY_GB
    3) ~/.elyan/elyan.json memory.maxUserStorageGB
    4) default: 10GB
    """
    raw_bytes = os.getenv("ELYAN_MAX_USER_MEMORY_BYTES")
    if raw_bytes:
        try:
            parsed = int(raw_bytes)
            if parsed > 0:
                return parsed
        except ValueError:
            logger.warning("Invalid ELYAN_MAX_USER_MEMORY_BYTES, using GB fallback")

    raw_gb_env = os.getenv("ELYAN_MAX_USER_MEMORY_GB")
    gb: float
    if raw_gb_env is not None:
        try:
            gb = float(raw_gb_env)
        except ValueError:
            gb = DEFAULT_USER_MEMORY_LIMIT_GB
    else:
        gb = _config_user_limit_gb() or DEFAULT_USER_MEMORY_LIMIT_GB

    gb = max(gb, 0.01)
    return int(gb * 1024 * 1024 * 1024)


class Memory:
    """
    Memory system for storing and retrieving conversation history,
    user preferences, and task execution results
    """
    
    def __init__(self, db_path: str = None):
        if db_path is None:
            db_path = _resolve_default_db_path()
        
        self.db_path = db_path
        self.default_user_limit_bytes = _default_user_limit_bytes()
        self.conn = None
        try:
            self._initialize_db()
        except sqlite3.OperationalError as exc:
            # Some environments expose unwritable HOME/config mounts during tests.
            if _is_unwritable_db_error(exc):
                fallback_dir = Path.cwd() / ".elyan_memory"
                fallback_dir.mkdir(parents=True, exist_ok=True)
                self.db_path = str(fallback_dir / "memory.db")
                logger.warning(f"Primary memory DB unavailable, using fallback: {self.db_path}")
                self._initialize_db()
            else:
                raise
    
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
                    metadata TEXT,
                    size_bytes INTEGER NOT NULL DEFAULT 0
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

            # Canonical embedding storage (BUG-FUNC-003 consistency)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_embeddings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    conversation_id INTEGER,
                    model TEXT,
                    embedding_json TEXT NOT NULL,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    size_bytes INTEGER NOT NULL DEFAULT 0
                )
            """)

            # Backward-compatible migrations for older DBs.
            self._ensure_column(cursor, "conversations", "size_bytes", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(
                cursor,
                "conversation_embeddings",
                "size_bytes",
                "INTEGER NOT NULL DEFAULT 0",
            )
            
            # Create indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_conv_user_time ON conversations(user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pref_user ON preferences(user_id)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_task_user_time ON task_history(user_id, timestamp)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_emb_user_time ON conversation_embeddings(user_id, created_at DESC)")
            
            self.conn.commit()
            logger.info(f"Memory database initialized at {self.db_path}")
        
        except Exception as e:
            logger.error(f"Error initializing database: {e}")
            raise

    def _ensure_column(self, cursor, table: str, column: str, definition: str):
        cursor.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in cursor.fetchall()}
        if column not in columns:
            cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _estimate_size_bytes(self, *values: Any) -> int:
        total = 0
        for value in values:
            if value is None:
                continue
            text = value if isinstance(value, str) else str(value)
            total += len(text.encode("utf-8"))
        return total

    def _get_user_limit_bytes(self, user_id: int) -> int:
        _ = user_id  # reserved for per-user custom limits in future
        return self.default_user_limit_bytes

    def _get_user_storage_usage_bytes(self, cursor, user_id: int) -> int:
        cursor.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM conversations WHERE user_id = ?",
            (user_id,),
        )
        conv_bytes = int(cursor.fetchone()["total"] or 0)
        cursor.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS total FROM conversation_embeddings WHERE user_id = ?",
            (user_id,),
        )
        emb_bytes = int(cursor.fetchone()["total"] or 0)
        return conv_bytes + emb_bytes

    def _prune_oldest_conversation(self, cursor, user_id: int) -> int:
        cursor.execute(
            """
            SELECT id, COALESCE(size_bytes, 0) AS size_bytes
            FROM conversations
            WHERE user_id = ?
            ORDER BY timestamp ASC
            LIMIT 1
            """,
            (user_id,),
        )
        row = cursor.fetchone()
        if not row:
            return 0

        conversation_id = int(row["id"])
        freed = int(row["size_bytes"] or 0)

        cursor.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS emb_size FROM conversation_embeddings WHERE conversation_id = ?",
            (conversation_id,),
        )
        freed += int(cursor.fetchone()["emb_size"] or 0)
        cursor.execute("DELETE FROM conversation_embeddings WHERE conversation_id = ?", (conversation_id,))
        cursor.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        return freed

    def _ensure_user_capacity(self, cursor, user_id: int, additional_bytes: int) -> bool:
        if additional_bytes <= 0:
            return True

        limit_bytes = self._get_user_limit_bytes(user_id)
        if additional_bytes > limit_bytes:
            return False

        used_bytes = self._get_user_storage_usage_bytes(cursor, user_id)
        while used_bytes + additional_bytes > limit_bytes:
            freed_bytes = self._prune_oldest_conversation(cursor, user_id)
            if freed_bytes <= 0:
                return False
            used_bytes = max(0, used_bytes - freed_bytes)
        return True
    
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
            bot_response_json = json.dumps(bot_response, ensure_ascii=False)
            metadata_json = json.dumps(bot_response.get("metadata", {}), ensure_ascii=False)
            action = bot_response.get("action", "unknown")
            conversation_size = self._estimate_size_bytes(
                user_message,
                bot_response_json,
                action,
                metadata_json,
            )

            if not self._ensure_user_capacity(cursor, user_id, conversation_size):
                logger.warning(
                    "Memory quota exceeded for user %s: conversation dropped (limit=%s bytes)",
                    user_id,
                    self._get_user_limit_bytes(user_id),
                )
                return -1

            cursor.execute("""
                INSERT INTO conversations (
                    user_id, timestamp, user_message, bot_response, action, success, metadata, size_bytes
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                datetime.now().isoformat(),
                user_message,
                bot_response_json,
                action,
                bot_response.get("success", True),
                metadata_json,
                conversation_size,
            ))
            conversation_id = cursor.lastrowid

            # BUG-FUNC-003: Store embedding in canonical JSON format if provided.
            embedding = bot_response.get("embedding")
            if embedding is not None:
                try:
                    embedding_json = serialize_embedding(embedding)
                    embedding_metadata_json = json.dumps(
                        bot_response.get("embedding_metadata", {}),
                        ensure_ascii=False,
                    )
                    embedding_model = str(bot_response.get("embedding_model", "") or "")
                    embedding_size = self._estimate_size_bytes(
                        embedding_json,
                        embedding_metadata_json,
                        embedding_model,
                    )
                    if not self._ensure_user_capacity(cursor, user_id, embedding_size):
                        logger.warning(
                            "Memory quota exceeded for user %s: embedding skipped",
                            user_id,
                        )
                    else:
                        cursor.execute("""
                            INSERT INTO conversation_embeddings (
                                user_id, conversation_id, model, embedding_json, metadata, created_at, size_bytes
                            ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        """, (
                            user_id,
                            conversation_id,
                            embedding_model,
                            embedding_json,
                            embedding_metadata_json,
                            datetime.now().isoformat(),
                            embedding_size,
                        ))
                except Exception as emb_exc:
                    logger.warning(f"Embedding skipped due to format error: {emb_exc}")

            self.conn.commit()
            return conversation_id
        
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
            cursor.execute("DELETE FROM conversation_embeddings WHERE user_id = ?", (user_id,))
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

            cursor.execute("SELECT COUNT(*) as count FROM conversation_embeddings")
            embedding_count = cursor.fetchone()["count"]

            cursor.execute("SELECT COUNT(DISTINCT user_id) AS count FROM conversations")
            user_count = cursor.fetchone()["count"] or 0

            db_size_bytes = 0
            db_file = Path(self.db_path)
            if db_file.exists():
                db_size_bytes = db_file.stat().st_size
            
            return {
                "conversations": conv_count,
                "preferences": pref_count,
                "tasks": task_count,
                "knowledge_items": knowledge_count,
                "embeddings": embedding_count,
                "users": user_count,
                "database_path": self.db_path,
                "database_size_bytes": db_size_bytes,
                "default_user_limit_bytes": self.default_user_limit_bytes,
            }
        
        except Exception as e:
            logger.error(f"Error getting stats: {e}")
            return {}

    def store_embedding(
        self,
        user_id: int,
        embedding: Any,
        *,
        conversation_id: Optional[int] = None,
        model: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Store embedding with canonical JSON representation."""
        try:
            cursor = self.conn.cursor()
            embedding_json = serialize_embedding(embedding)
            metadata_json = json.dumps(metadata or {}, ensure_ascii=False)
            embedding_size = self._estimate_size_bytes(embedding_json, metadata_json, model)
            if not self._ensure_user_capacity(cursor, user_id, embedding_size):
                logger.warning(
                    "Memory quota exceeded for user %s: standalone embedding skipped",
                    user_id,
                )
                return -1
            cursor.execute("""
                INSERT INTO conversation_embeddings (
                    user_id, conversation_id, model, embedding_json, metadata, created_at, size_bytes
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                user_id,
                conversation_id,
                model or "",
                embedding_json,
                metadata_json,
                datetime.now().isoformat(),
                embedding_size,
            ))
            self.conn.commit()
            return cursor.lastrowid
        except Exception as e:
            logger.error(f"Error storing embedding: {e}")
            return -1

    def get_user_embeddings(self, user_id: int, limit: int = 100) -> List[Dict[str, Any]]:
        """Get embeddings for user with decoded vector payload."""
        try:
            cursor = self.conn.cursor()
            cursor.execute("""
                SELECT * FROM conversation_embeddings
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (user_id, limit))
            rows = [dict(row) for row in cursor.fetchall()]
            for row in rows:
                row["embedding"] = deserialize_embedding(row.get("embedding_json"))
                row["metadata"] = json.loads(row["metadata"]) if row.get("metadata") else {}
            return rows
        except Exception as e:
            logger.error(f"Error getting embeddings: {e}")
            return []
    
    def close(self):
        """Close database connection"""
        if self.conn:
            self.conn.close()
            logger.info("Memory database connection closed")

    def get_user_storage_stats(self, user_id: int) -> Dict[str, Any]:
        """Get per-user storage usage and cap."""
        try:
            cursor = self.conn.cursor()
            used_bytes = self._get_user_storage_usage_bytes(cursor, user_id)
            limit_bytes = self._get_user_limit_bytes(user_id)
            usage_pct = (used_bytes / limit_bytes * 100) if limit_bytes > 0 else 0
            return {
                "user_id": user_id,
                "used_bytes": used_bytes,
                "used_mb": round(used_bytes / (1024 * 1024), 2),
                "limit_bytes": limit_bytes,
                "limit_gb": round(limit_bytes / (1024 * 1024 * 1024), 2),
                "usage_percent": round(usage_pct, 2),
            }
        except Exception as e:
            logger.error(f"Error getting user storage stats: {e}")
            return {
                "user_id": user_id,
                "used_bytes": 0,
                "used_mb": 0.0,
                "limit_bytes": self.default_user_limit_bytes,
                "limit_gb": round(self.default_user_limit_bytes / (1024 * 1024 * 1024), 2),
                "usage_percent": 0.0,
            }

    def get_top_users_storage(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Return top users by persisted storage usage."""
        limit = max(1, int(limit or 10))
        try:
            cursor = self.conn.cursor()
            usage: Dict[int, Dict[str, Any]] = {}

            cursor.execute(
                """
                SELECT user_id, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
                FROM conversations
                WHERE user_id IS NOT NULL
                GROUP BY user_id
                """
            )
            for row in cursor.fetchall():
                user_id = int(row["user_id"])
                usage[user_id] = {
                    "user_id": user_id,
                    "conversation_count": int(row["count"] or 0),
                    "embedding_count": 0,
                    "used_bytes": int(row["bytes"] or 0),
                }

            cursor.execute(
                """
                SELECT user_id, COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS bytes
                FROM conversation_embeddings
                WHERE user_id IS NOT NULL
                GROUP BY user_id
                """
            )
            for row in cursor.fetchall():
                user_id = int(row["user_id"])
                entry = usage.setdefault(
                    user_id,
                    {
                        "user_id": user_id,
                        "conversation_count": 0,
                        "embedding_count": 0,
                        "used_bytes": 0,
                    },
                )
                entry["embedding_count"] += int(row["count"] or 0)
                entry["used_bytes"] += int(row["bytes"] or 0)

            rows = sorted(usage.values(), key=lambda x: x["used_bytes"], reverse=True)[:limit]
            limit_bytes = self.default_user_limit_bytes
            for row in rows:
                used_bytes = row["used_bytes"]
                row["used_mb"] = round(used_bytes / (1024 * 1024), 2)
                row["usage_percent"] = round((used_bytes / limit_bytes) * 100, 2) if limit_bytes > 0 else 0.0
            return rows
        except Exception as e:
            logger.error(f"Error getting top user storage stats: {e}")
            return []


class MemoryManager:
    """
    CLI-friendly memory manager facade.
    Keeps async-compatible method names used by CLI commands.
    """

    def __init__(self, db_path: Optional[str] = None):
        self.memory = Memory(db_path=db_path)

    def get_stats(self, user_id: Optional[int] = None) -> Dict[str, Any]:
        base = self.memory.get_stats()
        total_items = (
            int(base.get("conversations", 0))
            + int(base.get("preferences", 0))
            + int(base.get("tasks", 0))
            + int(base.get("knowledge_items", 0))
            + int(base.get("embeddings", 0))
        )
        size_bytes = int(base.get("database_size_bytes", 0))
        stats = {
            **base,
            "total_items": total_items,
            "size_bytes": size_bytes,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "path": base.get("database_path", self.memory.db_path),
            "index_ok": True,
        }
        if user_id is not None:
            stats["user_storage"] = self.memory.get_user_storage_stats(user_id)
        return stats

    def rebuild_index(self) -> bool:
        # SQLite-backed memory does not require vector index rebuild here.
        return True

    def search(self, query: str, limit: int = 10, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        cursor = self.memory.conn.cursor()
        if user_id is None:
            cursor.execute(
                """
                SELECT user_id, timestamp, user_message, bot_response
                FROM conversations
                WHERE user_message LIKE ? OR bot_response LIKE ?
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                (f"%{query}%", f"%{query}%", limit),
            )
            rows = cursor.fetchall()
        else:
            rows = self.memory.search_conversations(user_id=user_id, query=query, limit=limit)
            return [
                {
                    "user_id": row.get("user_id"),
                    "content": row.get("user_message", ""),
                    "timestamp": row.get("timestamp"),
                    "score": 1.0,
                }
                for row in rows
            ]

        return [
            {
                "user_id": row["user_id"],
                "content": row["user_message"],
                "timestamp": row["timestamp"],
                "score": 1.0,
            }
            for row in rows
        ]

    def export(self, format: str = "json", user_id: Optional[int] = None):
        cursor = self.memory.conn.cursor()
        if user_id is None:
            cursor.execute("SELECT * FROM conversations ORDER BY timestamp DESC")
        else:
            cursor.execute(
                "SELECT * FROM conversations WHERE user_id = ? ORDER BY timestamp DESC",
                (user_id,),
            )
        conversations = [dict(row) for row in cursor.fetchall()]

        payload = {
            "generated_at": datetime.now().isoformat(),
            "db_path": self.memory.db_path,
            "user_id": user_id,
            "conversations": conversations,
        }

        if format == "markdown":
            lines = [f"# Elyan Memory Export ({datetime.now().isoformat()})", ""]
            for item in conversations:
                lines.append(f"## User {item.get('user_id')} — {item.get('timestamp')}")
                lines.append(f"**User:** {item.get('user_message', '')}")
                lines.append(f"**Bot:** {item.get('bot_response', '')}")
                lines.append("")
            return "\n".join(lines)
        return payload

    def clear(self, user_id: Optional[int] = None):
        cursor = self.memory.conn.cursor()
        if user_id is not None:
            self.memory.clear_user_data(user_id)
            return

        cursor.execute("DELETE FROM conversation_embeddings")
        cursor.execute("DELETE FROM conversations")
        cursor.execute("DELETE FROM preferences")
        cursor.execute("DELETE FROM task_history")
        self.memory.conn.commit()

    def import_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        conversations = data.get("conversations", [])
        imported = 0
        for row in conversations:
            user_id = int(row.get("user_id", 0) or 0)
            if user_id <= 0:
                continue
            user_message = str(row.get("user_message", "") or "")
            bot_response = row.get("bot_response", {})
            if isinstance(bot_response, str):
                try:
                    bot_response = json.loads(bot_response)
                except json.JSONDecodeError:
                    bot_response = {"message": bot_response, "action": "imported", "success": True}
            if self.memory.store_conversation(user_id, user_message, bot_response) > 0:
                imported += 1
        return {"imported": imported, "total": len(conversations)}

    def close(self):
        self.memory.close()


# Global memory instance
_memory_instance = None


def get_memory() -> Memory:
    """Get or create the global memory instance"""
    global _memory_instance
    if _memory_instance is None:
        _memory_instance = Memory()
    return _memory_instance
