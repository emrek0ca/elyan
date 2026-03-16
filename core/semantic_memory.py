import json
import logging
from typing import List, Dict, Any
from datetime import datetime
from pathlib import Path

from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import existing_text_path, preferred_text_path
from utils.logger import get_logger

logger = get_logger("semantic_memory")

class SemanticMemory:
    def __init__(self):
        memory_dir = resolve_elyan_data_dir() / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = preferred_text_path(memory_dir / "history.txt")
        self.patterns_path = preferred_text_path(memory_dir / "patterns.txt")

    async def add_entry(self, user_id: str, content: str, metadata: Dict[str, Any] = None):
        """Add a new entry to the semantic memory."""
        timestamp = datetime.now().isoformat()
        entry = {
            "user_id": user_id,
            "timestamp": timestamp,
            "content": content,
            "metadata": metadata or {}
        }
        
        try:
            self.patterns_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.patterns_path, "a", encoding="utf-8") as f:
                f.write(f"\n### Entry: {timestamp}\n- User: {user_id}\n- Content: {content}\n- Metadata: {json.dumps(metadata)}\n")
        except Exception as e:
            logger.error(f"Failed to add semantic entry: {e}")

    async def search(self, user_id: str, query: str, limit: int = 5) -> List[Dict]:
        """Search for relevant entries in semantic memory."""
        source_path = existing_text_path(self.patterns_path)
        if not source_path.exists():
            return []
            
        try:
            content = source_path.read_text(encoding="utf-8")
            entries = []
            parts = content.split("### Entry:")
            for p in parts[1:]:
                if f"- User: {user_id}" in p:
                    # Basic keyword matching
                    if any(word.lower() in p.lower() for word in query.lower().split()):
                        entries.append({"content": p.strip()})
            
            return entries[:limit]
        except Exception as e:
            logger.error(f"Semantic search error: {e}")
            return []

    async def record_success(self, task: str, plan_json: str):
        """Legacy compatibility: record success."""
        await self.add_entry("system", f"Success Task: {task}\nPlan: {plan_json}")

    async def get_relevant_examples(self, user_input: str) -> str:
        """Legacy compatibility: get examples."""
        entries = await self.search("system", user_input, limit=2)
        if not entries: return ""
        return "\nGeçmiş Örnekler:\n" + "\n".join([e["content"] for e in entries])

    async def clear_user(self, user_id: str):
        """Wipe user data (Stub: requires file rewrite for simple text storage)."""
        logger.warning(f"Semantic clear_user called for {user_id} - text file wipe not fully implemented.")

# Global instance
_semantic_memory = None

def get_semantic_memory():
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory()
    return _semantic_memory

semantic_memory = get_semantic_memory()
