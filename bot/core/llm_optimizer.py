"""
LLM Optimizer
Smart and fast LLM calls with optimized prompting
"""

import time
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("llm_optimizer")


class QueryComplexity(Enum):
    """Query complexity levels"""
    TRIVIAL = "trivial"  # One-line answers
    SIMPLE = "simple"  # Short answers
    MODERATE = "moderate"  # Paragraph answers
    COMPLEX = "complex"  # Multi-paragraph
    ADVANCED = "advanced"  # Research-level


class ResponseMode(Enum):
    """Response generation modes"""
    FAST = "fast"  # Quick, concise
    BALANCED = "balanced"  # Medium quality/speed
    THOROUGH = "thorough"  # High quality, slower


@dataclass
class OptimizedPrompt:
    """Optimized prompt configuration"""
    prompt: str
    max_tokens: int
    temperature: float
    mode: ResponseMode
    estimated_time: float


class LLMOptimizer:
    """
    LLM Optimizer
    - Classify query complexity
    - Optimize prompt structure
    - Reduce token usage
    - Faster inference
    - Smart response modes
    """

    def __init__(self):
        # Complexity indicators
        self.trivial_indicators = [
            "ne", "nedir", "kim", "where", "when", "what is",
            "tanım", "definition", "kısaca", "briefly"
        ]

        self.simple_indicators = [
            "nasıl", "how to", "açıkla", "explain",
            "fark", "difference", "neden", "why"
        ]

        self.complex_indicators = [
            "analiz", "analysis", "karşılaştır", "compare",
            "detaylı", "detailed", "kapsamlı", "comprehensive"
        ]

        self.advanced_indicators = [
            "araştır", "research", "inceleme", "investigation",
            "rapor", "report", "derin", "deep dive"
        ]

        # Token limits by complexity
        self.token_limits = {
            QueryComplexity.TRIVIAL: 50,
            QueryComplexity.SIMPLE: 150,
            QueryComplexity.MODERATE: 300,
            QueryComplexity.COMPLEX: 500,
            QueryComplexity.ADVANCED: 1000
        }

        # Temperature settings
        self.temperatures = {
            QueryComplexity.TRIVIAL: 0.3,  # More deterministic
            QueryComplexity.SIMPLE: 0.5,
            QueryComplexity.MODERATE: 0.7,
            QueryComplexity.COMPLEX: 0.7,
            QueryComplexity.ADVANCED: 0.8  # More creative
        }

        # Stats
        self.stats = {
            "total_optimizations": 0,
            "tokens_saved": 0,
            "time_saved": 0.0,
            "by_complexity": {}
        }

        logger.info("LLM Optimizer initialized")

    def classify_complexity(self, query: str) -> QueryComplexity:
        """Classify query complexity"""
        query_lower = query.lower()
        query_length = len(query.split())

        # Check for advanced indicators
        if any(indicator in query_lower for indicator in self.advanced_indicators):
            return QueryComplexity.ADVANCED

        # Check for complex indicators
        if any(indicator in query_lower for indicator in self.complex_indicators):
            return QueryComplexity.COMPLEX

        # Check for simple indicators
        if any(indicator in query_lower for indicator in self.simple_indicators):
            return QueryComplexity.SIMPLE

        # Check for trivial indicators
        if any(indicator in query_lower for indicator in self.trivial_indicators):
            return QueryComplexity.TRIVIAL

        # Use length as fallback
        if query_length < 5:
            return QueryComplexity.TRIVIAL
        elif query_length < 15:
            return QueryComplexity.SIMPLE
        elif query_length < 30:
            return QueryComplexity.MODERATE
        else:
            return QueryComplexity.COMPLEX

    def optimize_prompt(
        self,
        query: str,
        mode: ResponseMode = ResponseMode.BALANCED,
        force_complexity: Optional[QueryComplexity] = None
    ) -> OptimizedPrompt:
        """Optimize prompt for faster LLM response"""
        start_time = time.time()

        # Classify complexity
        complexity = force_complexity or self.classify_complexity(query)

        # Get token limit
        max_tokens = self.token_limits[complexity]

        # Adjust for mode
        if mode == ResponseMode.FAST:
            max_tokens = int(max_tokens * 0.7)
        elif mode == ResponseMode.THOROUGH:
            max_tokens = int(max_tokens * 1.5)

        # Get temperature
        temperature = self.temperatures[complexity]

        # Build optimized prompt
        optimized_query = self._build_optimized_prompt(query, complexity, mode)

        # Estimate response time
        estimated_time = self._estimate_response_time(complexity, max_tokens)

        # Update stats
        self.stats["total_optimizations"] += 1
        self.stats["by_complexity"][complexity.value] = \
            self.stats["by_complexity"].get(complexity.value, 0) + 1

        # Calculate tokens saved (compared to default 500)
        tokens_saved = max(0, 500 - max_tokens)
        self.stats["tokens_saved"] += tokens_saved

        optimization_time = time.time() - start_time
        logger.info(
            f"Optimized prompt: {complexity.value}, "
            f"max_tokens={max_tokens}, "
            f"temp={temperature}, "
            f"saved={tokens_saved} tokens, "
            f"time={optimization_time*1000:.1f}ms"
        )

        return OptimizedPrompt(
            prompt=optimized_query,
            max_tokens=max_tokens,
            temperature=temperature,
            mode=mode,
            estimated_time=estimated_time
        )

    def _build_optimized_prompt(
        self,
        query: str,
        complexity: QueryComplexity,
        mode: ResponseMode
    ) -> str:
        """Build optimized prompt based on complexity and mode"""

        # Base query
        optimized = query

        # Add response length instruction
        if complexity == QueryComplexity.TRIVIAL:
            optimized += "\n\nKısa ve net cevap ver (1-2 cümle)."
        elif complexity == QueryComplexity.SIMPLE:
            optimized += "\n\nKısa açıklama yap (3-5 cümle)."
        elif complexity == QueryComplexity.MODERATE:
            optimized += "\n\nOrta uzunlukta açıklama yap (1 paragraf)."

        # Add mode-specific instructions
        if mode == ResponseMode.FAST:
            optimized += "\n\nMümkün olduğunca hızlı ve özet yanıt ver."
        elif mode == ResponseMode.THOROUGH:
            optimized += "\n\nDetaylı ve kapsamlı açıklama yap."

        return optimized

    def _estimate_response_time(self, complexity: QueryComplexity, max_tokens: int) -> float:
        """Estimate LLM response time"""
        # Base time per complexity
        base_times = {
            QueryComplexity.TRIVIAL: 0.5,
            QueryComplexity.SIMPLE: 1.0,
            QueryComplexity.MODERATE: 2.0,
            QueryComplexity.COMPLEX: 4.0,
            QueryComplexity.ADVANCED: 8.0
        }

        base_time = base_times[complexity]

        # Add token generation time (rough estimate: 50ms per 10 tokens)
        token_time = (max_tokens / 10) * 0.05

        return base_time + token_time

    def should_use_streaming(self, complexity: QueryComplexity) -> bool:
        """Determine if streaming should be used"""
        # Use streaming for longer responses
        return complexity in [QueryComplexity.COMPLEX, QueryComplexity.ADVANCED]

    def get_cache_key(self, query: str, complexity: QueryComplexity) -> str:
        """Generate cache key for query"""
        import hashlib
        # Normalize query
        normalized = query.lower().strip()
        # Add complexity to key
        key_string = f"{complexity.value}:{normalized}"
        # Hash for consistent key
        return hashlib.md5(key_string.encode()).hexdigest()

    def optimize_batch(self, queries: List[str]) -> List[OptimizedPrompt]:
        """Optimize multiple queries at once"""
        optimized = []

        for query in queries:
            opt_prompt = self.optimize_prompt(query)
            optimized.append(opt_prompt)

        return optimized

    def get_stats(self) -> Dict[str, Any]:
        """Get optimizer statistics"""
        return {
            "total_optimizations": self.stats["total_optimizations"],
            "tokens_saved": self.stats["tokens_saved"],
            "time_saved": f"{self.stats['time_saved']:.2f}s",
            "avg_tokens_saved": (
                self.stats["tokens_saved"] / self.stats["total_optimizations"]
                if self.stats["total_optimizations"] > 0
                else 0
            ),
            "by_complexity": self.stats["by_complexity"]
        }


# Global instance
_llm_optimizer: Optional[LLMOptimizer] = None


def get_llm_optimizer() -> LLMOptimizer:
    """Get or create global LLM optimizer"""
    global _llm_optimizer
    if _llm_optimizer is None:
        _llm_optimizer = LLMOptimizer()
    return _llm_optimizer
