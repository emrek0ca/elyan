"""
Elyan Context Window Optimizer — Smart management of LLM context.

Trims and ranks memory items to fit within token limits while preserving high-value context.
"""

from typing import Any, Dict, List
import time

class ContextOptimizer:
    """Optimizes retrieved memory blocks for the LLM prompt."""

    def __init__(self, max_tokens: int = 4096):
        self.max_tokens = max_tokens

    def optimize(self, memory_results: Dict[str, List[Dict]], query: str) -> str:
        """Ranks and formats memory results into a coherent prompt block."""
        
        # Simple heuristic: Prioritize conversation history, then episodic, then semantic.
        # In a more advanced version, we would use cross-encoding or embedding similarity.
        
        blocks = []
        
        # 1. Short-term Conversation
        if memory_results.get("conversation"):
            blocks.append("### RECENT CONVERSATION")
            for msg in memory_results["conversation"]:
                role = msg.get("role", "user").upper()
                text = msg.get("content", "")
                blocks.append(f"{role}: {text}")
        
        # 2. Episodic Milestones
        if memory_results.get("episodic"):
            blocks.append("\n### RECENT MILESTONES & EVENTS")
            for evt in memory_results["episodic"]:
                t_str = time.strftime("%Y-%m-%d %H:%M", time.localtime(evt["timestamp"]))
                blocks.append(f"- [{t_str}] {evt['content']}")
                
        # 3. Long-term Semantic context
        if memory_results.get("semantic"):
            blocks.append("\n### RELEVANT LONG-TERM KNOWLEDGE")
            for entry in memory_results["semantic"]:
                blocks.append(f"- {entry.get('content', '')}")

        final_context = "\n".join(blocks)
        
        # Simple token count estimation (4 chars per token roughly)
        if len(final_context) > self.max_tokens * 4:
            # Truncative fallback
            final_context = final_context[:self.max_tokens * 4] + "..."
            
        return final_context

# Global instance
context_optimizer = ContextOptimizer()
