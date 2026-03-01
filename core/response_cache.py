"""
Response Cache System
Cache common questions and answers for instant responses
"""

import time
import hashlib
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from collections import OrderedDict

from utils.logger import get_logger

logger = get_logger("response_cache")


@dataclass
class CachedResponse:
    """Cached response entry"""
    question: str
    answer: str
    created_at: float
    accessed_at: float
    access_count: int
    ttl: int
    confidence: float


class ResponseCache:
    """
    Response Cache System
    - Cache question-answer pairs
    - Fuzzy matching for similar questions
    - TTL-based expiration
    - LRU eviction
    - Statistics tracking
    """

    def __init__(
        self,
        max_size: int = 500,
        default_ttl: int = 3600,  # 1 hour
        similarity_threshold: float = 0.85
    ):
        self.cache: OrderedDict[str, CachedResponse] = OrderedDict()
        self.max_size = max_size
        self.default_ttl = default_ttl
        self.similarity_threshold = similarity_threshold

        # Question index for fuzzy matching
        self.question_index: Dict[str, List[str]] = {}  # keyword -> [cache_keys]

        # Stats
        self.stats = {
            "hits": 0,
            "misses": 0,
            "evictions": 0,
            "expirations": 0,
            "fuzzy_matches": 0
        }

        logger.info(f"Response Cache initialized (max_size={max_size}, ttl={default_ttl}s)")

    def get(self, question: str) -> Optional[str]:
        """Get cached response for question"""
        # Try exact match first
        cache_key = self._generate_key(question)

        if cache_key in self.cache:
            entry = self.cache[cache_key]

            # Check expiration
            if self._is_expired(entry):
                self._remove(cache_key)
                self.stats["expirations"] += 1
                self.stats["misses"] += 1
                return None

            # Update access metadata
            entry.accessed_at = time.time()
            entry.access_count += 1

            # Move to end (LRU)
            self.cache.move_to_end(cache_key)

            self.stats["hits"] += 1
            logger.debug(f"Cache hit: {question[:50]}...")
            return entry.answer

        # Try fuzzy match
        fuzzy_answer = self._fuzzy_match(question)
        if fuzzy_answer:
            self.stats["hits"] += 1
            self.stats["fuzzy_matches"] += 1
            logger.debug(f"Fuzzy cache hit: {question[:50]}...")
            return fuzzy_answer

        self.stats["misses"] += 1
        return None

    def set(
        self,
        question: str,
        answer: str,
        ttl: Optional[int] = None,
        confidence: float = 1.0
    ):
        """Cache question-answer pair"""
        cache_key = self._generate_key(question)
        ttl = ttl if ttl is not None else self.default_ttl

        # Check if eviction needed
        if len(self.cache) >= self.max_size and cache_key not in self.cache:
            self._evict_lru()

        # Create entry
        entry = CachedResponse(
            question=question,
            answer=answer,
            created_at=time.time(),
            accessed_at=time.time(),
            access_count=1,
            ttl=ttl,
            confidence=confidence
        )

        self.cache[cache_key] = entry

        # Update question index
        self._index_question(question, cache_key)

        logger.debug(f"Cached response: {question[:50]}...")

    def _generate_key(self, question: str) -> str:
        """Generate cache key from question"""
        # 1. Basic normalization
        normalized = question.lower().strip()
        # 2. Remove punctuation but keep spaces
        normalized = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in normalized)
        # 3. Tokenize and remove stop words
        words = normalized.split()
        stop_words = {'ve', 'veya', 'ile', 'için', 'bir', 'bu', 'şu', 'o',
                      'and', 'or', 'the', 'a', 'an', 'is', 'are', 'was', 'were',
                      'mı', 'mi', 'mu', 'mü', 'lütfen', 'please', 'can', 'you'}
        tokens = [w for w in words if w not in stop_words and len(w) > 1]
        
        # 4. Sort tokens to handle word order variations (Semantic Hit Improvement)
        tokens.sort()
        normalized_query = " ".join(tokens)
        
        # 5. Hash for consistent key
        return hashlib.sha256(normalized_query.encode()).hexdigest()

    def _is_expired(self, entry: CachedResponse) -> bool:
        """Check if cache entry is expired"""
        if entry.ttl == 0:  # No expiration
            return False
        return time.time() - entry.created_at > entry.ttl

    def _evict_lru(self):
        """Evict least recently used entry"""
        if self.cache:
            cache_key, entry = self.cache.popitem(last=False)
            self._remove_from_index(entry.question, cache_key)
            self.stats["evictions"] += 1
            logger.debug(f"Evicted LRU entry: {entry.question[:50]}...")

    def _remove(self, cache_key: str):
        """Remove entry from cache"""
        if cache_key in self.cache:
            entry = self.cache.pop(cache_key)
            self._remove_from_index(entry.question, cache_key)

    def _index_question(self, question: str, cache_key: str):
        """Index question for fuzzy matching"""
        # Extract keywords (simple word tokenization)
        keywords = self._extract_keywords(question)

        for keyword in keywords:
            if keyword not in self.question_index:
                self.question_index[keyword] = []
            if cache_key not in self.question_index[keyword]:
                self.question_index[keyword].append(cache_key)

    def _remove_from_index(self, question: str, cache_key: str):
        """Remove question from index"""
        keywords = self._extract_keywords(question)

        for keyword in keywords:
            if keyword in self.question_index:
                if cache_key in self.question_index[keyword]:
                    self.question_index[keyword].remove(cache_key)
                if not self.question_index[keyword]:
                    del self.question_index[keyword]

    def _extract_keywords(self, question: str) -> List[str]:
        """Extract keywords from question"""
        # Normalize
        text = question.lower().strip()
        # Remove punctuation
        text = ''.join(c if c.isalnum() or c.isspace() else ' ' for c in text)
        # Split into words
        words = text.split()
        # Filter short words and common words
        stop_words = {'ve', 'veya', 'ile', 'için', 'bir', 'bu', 'şu', 'o',
                      'and', 'or', 'the', 'a', 'an', 'is', 'are', 'was', 'were'}
        keywords = [w for w in words if len(w) > 2 and w not in stop_words]
        return keywords

    def _fuzzy_match(self, question: str) -> Optional[str]:
        """Find similar cached question"""
        keywords = self._extract_keywords(question)

        if not keywords:
            return None

        # Find candidates with matching keywords
        candidates = {}
        for keyword in keywords:
            if keyword in self.question_index:
                for cache_key in self.question_index[keyword]:
                    if cache_key in self.cache:
                        candidates[cache_key] = candidates.get(cache_key, 0) + 1

        if not candidates:
            return None

        # Find best match
        best_key = None
        best_score = 0

        for cache_key, keyword_matches in candidates.items():
            entry = self.cache[cache_key]

            # Check expiration
            if self._is_expired(entry):
                continue

            # Calculate similarity score
            entry_keywords = self._extract_keywords(entry.question)
            if not entry_keywords:
                continue

            # Jaccard similarity
            similarity = len(set(keywords) & set(entry_keywords)) / len(set(keywords) | set(entry_keywords))

            if similarity > best_score:
                best_score = similarity
                best_key = cache_key

        # Return if similarity is above threshold
        if best_key and best_score >= self.similarity_threshold:
            entry = self.cache[best_key]
            entry.accessed_at = time.time()
            entry.access_count += 1
            self.cache.move_to_end(best_key)
            return entry.answer

        return None

    def clear(self):
        """Clear cache"""
        self.cache.clear()
        self.question_index.clear()
        logger.info("Response cache cleared")

    def get_popular_questions(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most frequently accessed questions"""
        entries = list(self.cache.values())
        entries.sort(key=lambda e: e.access_count, reverse=True)

        return [
            {
                "question": entry.question,
                "access_count": entry.access_count,
                "confidence": entry.confidence
            }
            for entry in entries[:limit]
        ]

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        total_requests = self.stats["hits"] + self.stats["misses"]
        hit_rate = (self.stats["hits"] / total_requests * 100) if total_requests > 0 else 0

        fuzzy_rate = (
            self.stats["fuzzy_matches"] / self.stats["hits"] * 100
            if self.stats["hits"] > 0
            else 0
        )

        return {
            "cache_size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.stats["hits"],
            "misses": self.stats["misses"],
            "hit_rate": f"{hit_rate:.1f}%",
            "fuzzy_matches": self.stats["fuzzy_matches"],
            "fuzzy_rate": f"{fuzzy_rate:.1f}%",
            "evictions": self.stats["evictions"],
            "expirations": self.stats["expirations"],
            "indexed_keywords": len(self.question_index)
        }


# Global instance
_response_cache: Optional[ResponseCache] = None


def get_response_cache() -> ResponseCache:
    """Get or create global response cache"""
    global _response_cache
    if _response_cache is None:
        _response_cache = ResponseCache()
    return _response_cache
