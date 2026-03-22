import time
from typing import Any, Dict, List, Optional
from core.observability.logger import get_structured_logger

slog = get_structured_logger("context_compactor")

class TranscriptCompactor:
    """
    Handles compaction of long transcripts into higher-level summaries.
    Ensures that Elyan retains the gist of old work without bloating the context.
    """
    def __init__(self, max_history_items: int = 15):
        self.max_history_items = max_history_items

    async def compact_if_needed(self, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        If history exceeds threshold, summarizes older items and returns a 
        shortened history with a leading summary block.
        """
        if len(history) <= self.max_history_items:
            return history

        # 1. Split into "to compact" and "to keep"
        keep_count = self.max_history_items // 3 # Keep the last 1/3 as raw
        to_compact = history[:-keep_count]
        to_keep = history[-keep_count:]

        # 2. Generate summary (In a real implementation, this would call a cheap LLM)
        summary_text = self._pseudo_summarize(to_compact)
        
        # 3. Create new history structure
        compacted_history = [
            {"role": "system", "content": f"### PREVIOUS CONVERSATION SUMMARY\n{summary_text}"},
            *to_keep
        ]
        
        slog.log_event("history_compacted", {
            "original_size": len(history),
            "new_size": len(compacted_history),
            "items_summarized": len(to_compact)
        })
        
        return compacted_history

    def _pseudo_summarize(self, items: List[Dict[str, Any]]) -> str:
        """Heuristic summary for Phase 1/2 until LLM summarizer is integrated."""
        count = len(items)
        first_item = items[0].get("content", "")[:50]
        last_item = items[-1].get("content", "")[:50]
        return f"Previously, there were {count} interactions starting with '{first_item}...' and ending with '{last_item}...'. Most of the context was about general operations."

# Global instance
transcript_compactor = TranscriptCompactor()
