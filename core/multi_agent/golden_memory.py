"""
core/multi_agent/golden_memory.py
─────────────────────────────────────────────────────────────────────────────
Vector-based semantic memory for the Neural Router.
Stores highly successful completions as "Golden Recipes".
"""

import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from config.settings import ELYAN_DIR
from utils.logger import get_logger

logger = get_logger("golden_memory")

@dataclass
class GoldenRecipe:
    intent: str
    template_id: str
    embedding: List[float]
    audit_zip: str
    duration_s: float
    
class GoldenMemory:
    def __init__(self):
        self.db_path = ELYAN_DIR / "memory" / "golden_recipes.db"
        self._init_db()
        
    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS recipes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    intent TEXT,
                    template_id TEXT,
                    embedding TEXT,
                    audit_zip TEXT,
                    duration_s REAL
                )
            """)
            conn.commit()

    async def _get_embedding(self, text: str, agent=None) -> List[float]:
        if not agent:
            # Fallback mock for testing without agent context
            return [0.0] * 1536
        try:
            return await agent.llm.get_embedding(text)
        except:
            return [0.0] * 1536

    def _cosine_similarity(self, v1: List[float], v2: List[float]) -> float:
        if not v1 or not v2 or len(v1) != len(v2): return 0.0
        dot = sum(a*b for a,b in zip(v1, v2))
        norm1 = sum(a*a for a in v1) ** 0.5
        norm2 = sum(b*b for b in v2) ** 0.5
        if norm1 == 0 or norm2 == 0: return 0.0
        return dot / (norm1 * norm2)

    async def save_recipe(self, intent: str, template_id: str, audit_zip: str, duration_s: float, agent=None):
        """Saves a successfully completed job as a Golden Recipe."""
        emb = await self._get_embedding(intent, agent)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO recipes (intent, template_id, embedding, audit_zip, duration_s) VALUES (?, ?, ?, ?, ?)",
                (intent, template_id, json.dumps(emb), audit_zip, duration_s)
            )
            conn.commit()
            logger.info(f"💾 Saved Golden Recipe for '{template_id}' -> '{intent[:30]}...'")

    async def find_closest_template(self, query: str, agent=None, threshold: float = 0.82) -> Optional[str]:
        """Finds the semantically closest template based on past successes."""
        query_emb = await self._get_embedding(query, agent)
        best_match = None
        best_score = -1.0
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT template_id, embedding FROM recipes")
            for row in cursor:
                tid = row[0]
                emb = json.loads(row[1])
                score = self._cosine_similarity(query_emb, emb)
                if score > best_score:
                    best_score = score
                    best_match = tid
                    
        if best_match and best_score >= threshold:
            logger.info(f"🧠 Semantic routing matched {best_match} (score: {best_score:.3f})")
            return best_match
        return None

golden_memory = GoldenMemory()
