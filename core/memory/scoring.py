from typing import Any, Dict, List, Optional, Tuple
from core.protocol.shared_types import MemoryType
from core.observability.logger import get_structured_logger

slog = get_structured_logger("memory_scoring")

class MemoryScorer:
    """
    Evaluates execution results to decide what should be saved to long-term memory.
    Ensures that only high-value, durable facts are promoted.
    """
    def score_candidate(self, content: str, context: Dict[str, Any]) -> Tuple[float, MemoryType]:
        """
        Returns (score, target_memory_level).
        Score range: 0.0 to 1.0
        """
        score = 0.5 # Baseline
        
        # Heuristics for scoring (In v2, this could be an LLM-based evaluator)
        
        # 1. Fact detection (Keywords that indicate durable info)
        fact_markers = ["remember", "always", "style", "prefer", "decision", "roadmap", "task", "project"]
        content_low = content.lower()
        for marker in fact_markers:
            if marker in content_low:
                score += 0.1
        
        # 2. Command/Decision detection
        if "adr-" in content_low or "decision" in content_low:
            return 0.9, MemoryType.PROJECT
            
        # 3. User preference detection
        if "i like" in content_low or "use " in content_low:
            return 0.8, MemoryType.PROFILE

        # Default to episodic if it seems useful
        if len(content) > 20:
            return 0.6, MemoryType.EPISODIC
            
        return 0.1, MemoryType.WORKING

    async def promote_if_worthy(self, content: str, context: Dict[str, Any], threshold: float = 0.7):
        """Scores and potentially writes back to hybrid memory."""
        score, level = self.score_candidate(content, context)
        
        if score >= threshold:
            from core.memory.hybrid import hybrid_memory
            
            if level == MemoryType.PROJECT:
                project_id = context.get("project_id", "default")
                await hybrid_memory.write_project_memory(project_id, content)
            elif level == MemoryType.EPISODIC:
                await hybrid_memory.write_daily_log(content)
            
            slog.log_event("memory_promoted", {"score": score, "level": level.value, "size": len(content)})
        else:
            slog.log_event("memory_discarded", {"score": score, "reason": "below_threshold"})

# Global instance
memory_scorer = MemoryScorer()
