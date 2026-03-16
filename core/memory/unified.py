"""
Elyan Unified Memory Layer — The central nervous system for memory.

Consolidates episodic, semantic, and conversation memory into a single API.
Provides high-level methods: remember(), recall(), forget(), and summarize().
"""

import asyncio
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import existing_text_path
from utils.logger import get_logger

logger = get_logger("unified_memory")

class UnifiedMemory:
    """Central entry point for all memory-related operations."""

    def __init__(self):
        self._initialized = False
        self.episodic = None
        self.semantic = None
        self.conversation = None

    async def initialize(self):
        """Lazy initialization of memory sub-modules."""
        if self._initialized:
            return
        
        try:
            # Import modules inside to avoid circular dependencies
            from core.memory.episodic import episodic_memory
            from core.semantic_memory import semantic_memory
            from core.conversation_memory import conversation_memory
            
            self.episodic = episodic_memory
            self.semantic = semantic_memory
            self.conversation = conversation_memory
            self._initialized = True
            logger.info("Unified Memory Layer initialized.")
        except Exception as e:
            logger.error(f"Failed to initialize Unified Memory: {e}")

    async def remember(self, user_id: str, content: str, metadata: Dict[str, Any] = None):
        """Store a new piece of information across relevant memory subsystems."""
        if not self._initialized: await self.initialize()
        
        t0 = time.time()
        tasks = []
        
        # 1. Store in conversation memory (short-term) - SYNC
        if self.conversation:
            try:
                # conversation_memory works synchronously with sqlite3
                self.conversation.add_message(user_id, "user" if metadata and metadata.get("role") == "user" else "assistant", content)
            except Exception as e:
                logger.error(f"Conv memory record error: {e}")
            
        # 2. Store in episodic memory (event-based) - ASYNC
        if self.episodic:
            tasks.append(self.episodic.record_event(user_id, "memory_entry", content, metadata))
            
        # 3. Store in semantic memory (long-term/embedding) - ASYNC
        if self.semantic:
            tasks.append(self.semantic.add_entry(user_id, content, metadata))
            
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            
        logger.debug(f"Remembered content for {user_id} in {int((time.time()-t0)*1000)}ms")

    async def recall(self, user_id: str, query: str, limit: int = 5) -> Dict[str, Any]:
        """Retrieve relevant context from all memory systems."""
        if not self._initialized: await self.initialize()
        
        results = {
            "conversation": [],
            "episodic": [],
            "semantic": []
        }
        
        # Sync retrieval for conversation
        if self.conversation:
            try:
                results["conversation"] = self.conversation.get_history(user_id, limit=limit)
            except Exception as e:
                logger.error(f"Conv memory recall error: {e}")

        # Parallel retrieval for async sources
        tasks = []
        source_keys = []
        
        if self.episodic:
            tasks.append(self.episodic.search_events(user_id, query, limit=limit))
            source_keys.append("episodic")
        if self.semantic:
            tasks.append(self.semantic.search(user_id, query, limit=limit))
            source_keys.append("semantic")
            
        if tasks:
            retrieved = await asyncio.gather(*tasks, return_exceptions=True)
            for i, res in enumerate(retrieved):
                if not isinstance(res, Exception):
                    results[source_keys[i]] = res
            
        return results

    async def forget(self, user_id: str):
        """Wipe all data for a user (Compliance: Right to be forgotten)."""
        if not self._initialized: await self.initialize()
        
        tasks = []
        if self.conversation: tasks.append(self.conversation.clear(user_id))
        if self.episodic: tasks.append(self.episodic.clear(user_id))
        if self.semantic: tasks.append(self.semantic.clear_user(user_id))
        
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info(f"Memory wiped for user: {user_id}")

    @staticmethod
    def _safe_sqlite_count(db_path: Path, query: str, params: tuple = ()) -> int:
        try:
            if not db_path.exists():
                return 0
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(query, params)
            row = cur.fetchone()
            conn.close()
            if not row:
                return 0
            return int(row[0] or 0)
        except Exception:
            return 0

    @staticmethod
    def _safe_sqlite_rows(db_path: Path, query: str, params: tuple = ()) -> list[tuple]:
        try:
            if not db_path.exists():
                return []
            conn = sqlite3.connect(str(db_path))
            cur = conn.cursor()
            cur.execute(query, params)
            rows = cur.fetchall()
            conn.close()
            return rows
        except Exception:
            return []

    @staticmethod
    def _legacy_memory():
        """
        Best-effort bridge to legacy core/memory.py singleton.
        This keeps dashboard memory stats working while unified memory is default.
        """
        try:
            mod = sys.modules.get("core._memory_legacy")
            if not mod:
                return None
            # Avoid side effects: do not instantiate legacy memory just for stats.
            existing = getattr(mod, "_memory_instance", None)
            if existing is not None:
                return existing
            if hasattr(mod, "get_memory_if_initialized"):
                maybe = mod.get_memory_if_initialized()
                if maybe is not None:
                    return maybe
        except Exception:
            pass
        return None

    def get_stats(self) -> Dict[str, Any]:
        """
        Backward-compatible stats contract used by dashboard `/api/memory/stats`.
        """
        legacy = self._legacy_memory()
        if legacy and hasattr(legacy, "get_stats"):
            try:
                stats = legacy.get_stats()
                if isinstance(stats, dict):
                    return stats
            except Exception as e:
                logger.debug(f"Legacy memory stats fallback failed: {e}")

        conv_db = Path.home() / ".config" / "cdacs-bot" / "conversation.db"
        conv_count = self._safe_sqlite_count(conv_db, "SELECT COUNT(*) FROM conversations")
        conv_users = self._safe_sqlite_count(conv_db, "SELECT COUNT(DISTINCT user_id) FROM conversations")

        episodic_db = resolve_elyan_data_dir() / "memory" / "episodic.db"
        episodic_count = self._safe_sqlite_count(episodic_db, "SELECT COUNT(*) FROM events")

        semantic_patterns = existing_text_path(resolve_elyan_data_dir() / "memory" / "patterns.txt")
        semantic_count = 0
        try:
            if semantic_patterns.exists():
                semantic_count = semantic_patterns.read_text(encoding="utf-8", errors="ignore").count("### Entry:")
        except Exception:
            semantic_count = 0

        db_size = 0
        for p in (conv_db, episodic_db, semantic_patterns):
            try:
                if p.exists():
                    db_size += int(p.stat().st_size)
            except Exception:
                pass

        return {
            "conversations": conv_count,
            "preferences": 0,
            "tasks": episodic_count,
            "knowledge_items": semantic_count,
            "embeddings": 0,
            "users": conv_users,
            "database_path": str(conv_db),
            "database_size_bytes": int(db_size),
            "default_user_limit_bytes": 0,
        }

    def get_top_users_storage(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Backward-compatible top-user storage API used by dashboard.
        """
        legacy = self._legacy_memory()
        if legacy and hasattr(legacy, "get_top_users_storage"):
            try:
                rows = legacy.get_top_users_storage(limit=limit)
                return rows if isinstance(rows, list) else []
            except Exception as e:
                logger.debug(f"Legacy top_users fallback failed: {e}")

        conv_db = Path.home() / ".config" / "cdacs-bot" / "conversation.db"
        lim = max(1, int(limit or 10))
        rows = self._safe_sqlite_rows(
            conv_db,
            """
            SELECT user_id, COUNT(*) AS cnt, COALESCE(SUM(LENGTH(content)), 0) AS bytes
            FROM conversations
            GROUP BY user_id
            ORDER BY bytes DESC
            LIMIT ?
            """,
            (lim,),
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            try:
                uid = int(row[0])
            except Exception:
                uid = 0
            out.append(
                {
                    "user_id": uid,
                    "conversation_count": int(row[1] or 0),
                    "embedding_count": 0,
                    "used_bytes": int(row[2] or 0),
                    "used_mb": round((int(row[2] or 0) / (1024 * 1024)), 2),
                    "limit_bytes": 0,
                    "usage_percent": 0.0,
                }
            )
        return out

# Global instance
memory = UnifiedMemory()
