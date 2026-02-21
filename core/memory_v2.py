"""
core/memory_v2.py
─────────────────────────────────────────────────────────────────────────────
Tiered Memory System: Profile, Episodic, Working.
Optimized for low footprint and high relevance.
"""

import json
import time
import sqlite3
from pathlib import Path
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, asdict
from config.settings import ELYAN_DIR

@dataclass
class UserProfile:
    name: str = "User"
    stack: List[str] = None
    preferences: Dict[str, Any] = None
    goals: List[str] = None
    strict_rules: List[str] = None # Permanent constraints like "No jQuery" or "Always use dark mode"
    last_updated: float = 0.0

    def to_json(self):
        return json.dumps(asdict(self), indent=2, ensure_ascii=False)

class ElyanMemory:
    def __init__(self):
        self.base_dir = ELYAN_DIR / "memory"
        self.base_dir.mkdir(parents=True, exist_ok=True)
        
        self.profile_path = self.base_dir / "profile.json"
        self.episodic_db = self.base_dir / "episodic.db"
        
        self._init_db()
        self.profile = self._load_profile()

    def _init_db(self):
        with sqlite3.connect(self.episodic_db) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS episodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    intent TEXT,
                    summary TEXT,
                    highlights TEXT,
                    job_id TEXT,
                    score REAL DEFAULT 0.0
                )
            """)
            conn.commit()

    def _load_profile(self) -> UserProfile:
        if self.profile_path.exists():
            try:
                data = json.loads(self.profile_path.read_text(encoding="utf-8"))
                return UserProfile(**data)
            except:
                pass
        return UserProfile(stack=[], preferences={}, goals=[], strict_rules=[])

    def save_profile(self):
        self.profile.last_updated = time.time()
        if self.profile.strict_rules is None:
            self.profile.strict_rules = []
        self.profile_path.write_text(self.profile.to_json(), encoding="utf-8")

    def _calculate_memory_score(self, fact: str, confidence: float = 0.5, is_preference: bool = False) -> float:
        """
        Scoring engine (persistence, confidence, frequency).
        High score (> 0.8) -> Strict Rule.
        Medium score -> Episodic Memory.
        """
        score = confidence
        if is_preference:
            score += 0.4
        if "her zaman" in fact.lower() or "asla" in fact.lower() or "always" in fact.lower():
            score += 0.3
        return min(score, 1.0)

    def evaluate_and_store_memory(self, fact: str, intent: str, job_id: str = None, is_preference: bool = False):
        """Routing memory based on score"""
        score = self._calculate_memory_score(fact, is_preference=is_preference)
        if score > 0.8:
            self.add_strict_rule(fact)
        else:
            self.add_episode(intent, summary="Learned fact", highlights=[fact], job_id=job_id, score=score)

    def add_strict_rule(self, rule: str):
        if self.profile.strict_rules is None:
            self.profile.strict_rules = []
        if rule not in self.profile.strict_rules:
            self.profile.strict_rules.append(rule)
            self.save_profile()

    def add_episode(self, intent: str, summary: str, highlights: List[str], job_id: str = None, score: float = 0.5):
        """Kısa vadeli hafızaya kanonik kayıt ekler. (Max 3 lesson compression)"""
        # Compress episodic highlights (max 3 items)
        compressed_highlights = highlights[:3] if highlights else []
        
        with sqlite3.connect(self.episodic_db) as conn:
            conn.execute(
                "INSERT INTO episodes (timestamp, intent, summary, highlights, job_id, score) VALUES (?, ?, ?, ?, ?, ?)",
                (time.time(), intent, summary, json.dumps(compressed_highlights), job_id, score)
            )
            # 30 günden eski veya skoru çok düşük olanları sil (Retention Policy)
            cutoff = time.time() - (30 * 86400)
            conn.execute("DELETE FROM episodes WHERE timestamp < ? AND score < 0.8", (cutoff,))
            conn.commit()

    def get_context_for_intent(self, intent: str) -> str:
        """İlgili intent'e göre optimize edilmiş context (Max 5-7 lines)"""
        lines = []
        
        # 1. Start with strict rules (highest priority) -> Rules Engine Segregation
        if self.profile.strict_rules:
            lines.append("STRICT RULES:")
            lines.extend([f"- {rule}" for rule in self.profile.strict_rules[:3]])  # top 3 rules

        # 2. Add relevant episodic memory (max 3-4 lines)
        with sqlite3.connect(self.episodic_db) as conn:
            limit = 7 - len(lines)
            if limit > 0:
                cursor = conn.execute(
                    "SELECT summary, highlights FROM episodes WHERE intent = ? OR ? LIKE '%' || intent || '%' ORDER BY score DESC, timestamp DESC LIMIT ?",
                    (intent, intent, 3) # Max 3 episodes
                )
                rows = cursor.fetchall()
                if rows:
                    lines.append("RECENT LESSONS:")
                    for r in rows:
                        if len(lines) >= 7: break
                        hl = json.loads(r[1]) if r[1] else []
                        hl_text = "; ".join(hl)
                        lines.append(f"- {r[0]} ({hl_text})"[:100])

        return "\n".join(lines)

# Singleton instance
memory_v2 = ElyanMemory()
