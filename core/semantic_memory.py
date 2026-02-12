"""
Semantic Conversation Memory System
Uses embeddings to find relevant past conversations for context
"""

import asyncio
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timedelta
from dataclasses import dataclass
from pathlib import Path
from utils.logger import get_logger

logger = get_logger("semantic_memory")


@dataclass
class ConversationEntry:
    """A conversation entry with embedding"""
    timestamp: str
    user_input: str
    bot_response: str
    embedding: Optional[List[float]] = None
    metadata: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "user_input": self.user_input,
            "bot_response": self.bot_response,
            "metadata": self.metadata or {}
        }


class SemanticMemory:
    """Stores conversations and retrieves semantically similar ones"""

    def __init__(self, cache_size: int = 1000, relevance_threshold: float = 0.6):
        self.conversations: List[ConversationEntry] = []
        self.cache_size = cache_size
        self.relevance_threshold = relevance_threshold
        self.embedder = None  # Will try to load embedder

    async def initialize(self):
        """Initialize embedding model (v17.0 Shared)"""
        from .model_manager import get_shared_embedder
        self.embedder = await get_shared_embedder()
        if self.embedder:
            logger.info("Semantic memory linked to shared embedder")
        else:
            logger.warning("Shared embedder not available, using keyword matching")

    async def add_conversation(self, user_input: str, bot_response: str, metadata: Optional[Dict] = None):
        """Add a conversation entry"""
        entry = ConversationEntry(
            timestamp=datetime.now().isoformat(),
            user_input=user_input,
            bot_response=bot_response,
            metadata=metadata or {}
        )

        # Add embedding if available
        if self.embedder:
            try:
                embedding = self.embedder.encode(user_input).tolist()
                entry.embedding = embedding
            except Exception as e:
                logger.debug(f"Failed to create embedding: {e}")

        self.conversations.append(entry)

        # Maintain cache size
        if len(self.conversations) > self.cache_size:
            self.conversations = self.conversations[-self.cache_size:]

    async def find_relevant(self, query: str, top_k: int = 3) -> List[ConversationEntry]:
        """Find relevant past conversations"""
        if not self.conversations:
            return []

        if self.embedder and self.conversations[0].embedding:
            return await self._semantic_search(query, top_k)
        else:
            return await self._keyword_search(query, top_k)

    async def _semantic_search(self, query: str, top_k: int) -> List[ConversationEntry]:
        """Semantic search using embeddings"""
        try:
            query_embedding = self.embedder.encode(query).tolist()

            scores = []
            for entry in self.conversations:
                if entry.embedding:
                    similarity = self._cosine_similarity(query_embedding, entry.embedding)
                    if similarity >= self.relevance_threshold:
                        scores.append((entry, similarity))

            scores.sort(key=lambda x: x[1], reverse=True)
            return [entry for entry, _ in scores[:top_k]]
        except Exception as e:
            logger.debug(f"Semantic search failed: {e}")
            return []

    async def _keyword_search(self, query: str, top_k: int) -> List[ConversationEntry]:
        """Fallback keyword-based search"""
        query_words = set(query.lower().split())
        scores = []

        for entry in self.conversations:
            input_words = set(entry.user_input.lower().split())
            matching_words = len(query_words & input_words)

            if matching_words > 0:
                similarity = matching_words / len(query_words | input_words)
                if similarity >= self.relevance_threshold:
                    scores.append((entry, similarity))

        scores.sort(key=lambda x: x[1], reverse=True)
        return [entry for entry, _ in scores[:top_k]]

    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """Calculate cosine similarity between vectors"""
        import math
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        magnitude1 = math.sqrt(sum(a * a for a in vec1))
        magnitude2 = math.sqrt(sum(b * b for b in vec2))

        if magnitude1 == 0 or magnitude2 == 0:
            return 0.0

        return dot_product / (magnitude1 * magnitude2)

    def get_recent(self, days: int = 1) -> List[ConversationEntry]:
        """Get recent conversations from last N days"""
        cutoff = datetime.now() - timedelta(days=days)
        return [
            entry for entry in self.conversations
            if datetime.fromisoformat(entry.timestamp) > cutoff
        ]

    def get_context_summary(self, top_k: int = 5) -> str:
        """Get summary of recent conversations for context"""
        recent = self.get_recent(days=1)
        if not recent:
            return ""

        summary = "Recent conversation history:\n"
        for entry in recent[-top_k:]:
            summary += f"- User: {entry.user_input[:80]}\n"

        return summary

    def clear_old(self, days: int = 30):
        """Clear conversations older than N days"""
        cutoff = datetime.now() - timedelta(days=days)
        initial_count = len(self.conversations)
        self.conversations = [
            entry for entry in self.conversations
            if datetime.fromisoformat(entry.timestamp) > cutoff
        ]
        removed = initial_count - len(self.conversations)
        logger.info(f"Cleared {removed} old conversations")

    def export(self) -> Dict[str, Any]:
        """Export all conversations"""
        return {
            "exported_at": datetime.now().isoformat(),
            "count": len(self.conversations),
            "conversations": [entry.to_dict() for entry in self.conversations]
        }


# Global instance
_semantic_memory: Optional[SemanticMemory] = None


async def get_semantic_memory() -> SemanticMemory:
    """Get or create semantic memory"""
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory()
        await _semantic_memory.initialize()
    return _semantic_memory
