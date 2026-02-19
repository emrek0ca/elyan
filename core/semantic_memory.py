import json
import logging
from typing import List, Dict, Any
from pathlib import Path
from datetime import datetime
from utils.logger import get_logger

logger = get_logger("semantic_memory")

class SemanticMemory:
    def __init__(self):
        self.memory_path = Path.home() / ".elyan" / "memory" / "history.md"
        self.patterns_path = Path.home() / ".elyan" / "memory" / "patterns.md"

    async def record_success(self, task: str, plan_json: str):
        """Başarılı bir görevi ve planını hafızaya kaydeder"""
        timestamp = datetime.now().isoformat()
        entry = f"\n### Task: {task}\n- Date: {timestamp}\n- Plan: {plan_json}\n"
        
        with open(self.patterns_path, "a", encoding="utf-8") as f:
            f.write(entry)

    async def get_relevant_examples(self, user_input: str) -> str:
        """Mevcut göreve benzer geçmiş örnekleri getirir (Basic keyword matching for now)"""
        if not self.patterns_path.exists():
            return ""
            
        try:
            content = self.patterns_path.read_text(encoding="utf-8")
            # Basit bir eşleşme mantığı (İleride embedding tabanlı olacak)
            relevant = []
            parts = content.split("### Task:")
            for p in parts[1:]:
                if any(word in p.lower() for word in user_input.lower().split()):
                    relevant.append(p.strip())
            
            if not relevant: return ""
            
            return "\nGeçmiş Örnekler:\n" + "\n".join(relevant[:2])
        except Exception as e:
            logger.error(f"Memory retrieval error: {e}")
            return ""

# Global instance
_semantic_memory = None

def get_semantic_memory():
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory()
    return _semantic_memory

semantic_memory = get_semantic_memory()
