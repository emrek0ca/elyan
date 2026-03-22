from typing import Any, Dict, List, Optional
from core.memory.pinned import pinned_memory
from core.memory.hybrid import hybrid_memory
from core.memory.compactor import transcript_compactor
from core.observability.logger import get_structured_logger

slog = get_structured_logger("retrieval_pipeline")

class RetrievalPipeline:
    """
    Coordinates context assembly for a run.
    Combines pinned, project, and session history into a single prompt block.
    """
    async def assemble_context(
        self, 
        user_id: str, 
        session_id: str, 
        project_id: Optional[str] = None,
        raw_history: List[Dict[str, Any]] = None
    ) -> str:
        slog.log_event("retrieval_started", {"session_id": session_id, "project_id": project_id})
        
        blocks = []

        # 1. Pinned Context (System rules, constant facts)
        pinned = pinned_memory.get_all_pinned_content()
        if pinned:
            blocks.append(pinned)

        # 2. Project Memory (If applicable)
        if project_id:
            project_mem = await hybrid_memory.read_project_memory(project_id)
            if project_mem:
                blocks.append(f"### PROJECT MEMORY ({project_id})\n{project_mem}")

        # 3. Session Transcript (Compact if needed)
        if raw_history:
            compacted = await transcript_compactor.compact_if_needed(raw_history)
            blocks.append("### RECENT CONVERSATION")
            for msg in compacted:
                role = str(msg.get("role", "user")).upper()
                content = msg.get("content", "")
                blocks.append(f"{role}: {content}")

        final_context = "\n\n".join(blocks)
        
        slog.log_event("retrieval_finished", {
            "session_id": session_id, 
            "context_size": len(final_context),
            "blocks_count": len(blocks)
        })
        
        return final_context

# Global instance
retrieval_pipeline = RetrievalPipeline()
