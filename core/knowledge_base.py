"""
core/knowledge_base.py
─────────────────────────────────────────────────────────────────────────────
Persistent experience store for Elyan. Stores successful problem-solving 
patterns discovered during self-healing or complex tasks.
"""

from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("knowledge_base")

KNOWLEDGE_FILE = Path.home() / ".elyan" / "knowledge_base.json"

class ExperienceRecord:
    def __init__(self, task_type: str, problem: str, solution: Dict[str, Any], context: Dict[str, Any]):
        self.task_type = task_type  # e.g., "write_word", "permission_issue"
        self.problem = problem      # short description of the error/challenge
        self.solution = solution    # the parameters or steps that worked
        self.context = context      # metadata like platform, stack
        self.success_count = 1
        self.created_at = time.time()
        self.last_used = self.created_at

class KnowledgeBase:
    def __init__(self):
        self.db_path = KNOWLEDGE_FILE
        self._records: List[Dict[str, Any]] = []
        self._load()

    def _load(self):
        try:
            if self.db_path.exists():
                self._records = json.loads(self.db_path.read_text(encoding="utf-8"))
            else:
                self._records = []
        except Exception as e:
            logger.error(f"Failed to load KB: {e}")
            self._records = []

    def _save(self):
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self.db_path.write_text(json.dumps(self._records, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            logger.error(f"Failed to save KB: {e}")

    def record_success(self, task_type: str, problem: str, solution: Dict[str, Any], context: Dict[str, Any]):
        """Yeni bir başarı deneyimini kaydeder veya mevcut olanı günceller."""
        # Basit bir deduplication (aynı problem/çözüm varsa sayacı artır)
        for rec in self._records:
            if rec["task_type"] == task_type and rec["problem"] == problem:
                rec["success_count"] += 1
                rec["last_used"] = time.time()
                self._save()
                return

        new_rec = {
            "task_type": task_type,
            "problem": problem,
            "solution": solution,
            "context": context,
            "success_count": 1,
            "created_at": time.time(),
            "last_used": time.time()
        }
        self._records.append(new_rec)
        self._save()
        logger.info(f"New experience recorded in KB: {problem} -> {task_type}")

    def find_solution(self, task_type: str, problem_hint: str) -> Optional[Dict[str, Any]]:
        """Benzer bir problem için geçmişte işe yaramış çözümü arar."""
        # Basit string matching (ileride embedding/vector search olabilir)
        for rec in sorted(self._records, key=lambda x: x["success_count"], reverse=True):
            if rec["task_type"] == task_type:
                if problem_hint.lower() in rec["problem"].lower() or rec["problem"].lower() in problem_hint.lower():
                    return rec["solution"]
        return None

    def list_experiences(self) -> List[Dict[str, Any]]:
        return self._records

_kb = KnowledgeBase()

def get_knowledge_base() -> KnowledgeBase:
    return _kb
