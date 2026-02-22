"""
Elyan Failure Clustering — Hata Kodları + Auto-Patch Playbooks

Random öğrenme değil, mühendislik:
1. Her fail'de "failed_check_code" üret
2. Failure clustering → en sık hatalar
3. Her hata için "auto-patch playbook"
"""

import json
import time
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from utils.logger import get_logger

logger = get_logger("failure_clustering")

_DB_PATH = Path.home() / ".elyan" / "failures.db"


# ── Failure Codes ─────────────────────────────────────────────

class FailureCode:
    """Standart hata kodları."""
    # Tool failures
    TOOL_WRITE_EMPTY = "TOOL_WRITE_EMPTY"
    TOOL_WRITE_FAILED = "TOOL_WRITE_FAILED"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_PERMISSION = "TOOL_PERMISSION"

    # Content failures
    HTML_BAD_STRUCTURE = "HTML_BAD_STRUCTURE"
    HTML_MISSING_CLOSING_TAG = "HTML_MISSING_CLOSING_TAG"
    CSS_EMPTY = "CSS_EMPTY"
    JS_SYNTAX_ERROR = "JS_SYNTAX_ERROR"
    CODE_SYNTAX_ERROR = "CODE_SYNTAX_ERROR"

    # Delivery failures
    DELIVERY_NO_EVIDENCE = "DELIVERY_NO_EVIDENCE"
    DELIVERY_FALSE_CLAIM = "DELIVERY_FALSE_CLAIM"
    CONTRACT_ARTIFACT_MISSING = "CONTRACT_ARTIFACT_MISSING"
    CONTRACT_QA_FAILED = "CONTRACT_QA_FAILED"

    # Research failures
    SOURCES_MISSING = "SOURCES_MISSING"
    CLAIM_UNSUPPORTED = "CLAIM_UNSUPPORTED"

    # LLM failures
    LLM_HALLUCINATION = "LLM_HALLUCINATION"
    LLM_EMPTY_RESPONSE = "LLM_EMPTY_RESPONSE"
    LLM_WRONG_LANGUAGE = "LLM_WRONG_LANGUAGE"


# ── Auto-Patch Playbooks ──────────────────────────────────────

AUTO_PATCH_PLAYBOOKS: Dict[str, Dict[str, Any]] = {
    FailureCode.TOOL_WRITE_EMPTY: {
        "description": "write_file sonrası dosya boş",
        "strategy": "retry_with_validation",
        "steps": [
            "write_file sonrası size > 0 doğrula",
            "Boşsa → farklı strateji ile retry",
            "Content minimum 50 byte olmalı",
        ],
        "validation": "os.path.getsize(path) > 50",
    },
    FailureCode.HTML_BAD_STRUCTURE: {
        "description": "HTML dosyası geçersiz yapıda",
        "strategy": "template_enforce",
        "steps": [
            "HTML5 boilerplate template uygula",
            "<!DOCTYPE html>, <html>, <head>, <body> var mı kontrol",
            "Yoksa template'ten yeniden oluştur",
        ],
        "validation": "'<html' in content.lower() and '</html>' in content.lower()",
    },
    FailureCode.SOURCES_MISSING: {
        "description": "Araştırma raporunda kaynak yok",
        "strategy": "enforce_citations",
        "steps": [
            "Kaynak claim'leri zorunlu kıl",
            "Kaynaksız claim'leri sil veya '[kaynak gerekli]' işaretle",
            "Minimum 3 kaynak referansı zorunlu",
        ],
        "validation": "response.count('http') >= 3 or response.count('[kaynak]') >= 3",
    },
    FailureCode.DELIVERY_NO_EVIDENCE: {
        "description": "Teslim iddiası var ama kanıt yok",
        "strategy": "block_delivery",
        "steps": [
            "Evidence Gate ile iddiayı blokla",
            "Tool'u tekrar çağır",
            "Sonucu doğrula",
        ],
        "validation": "len(tool_results) > 0 and any(r.get('success') for r in tool_results)",
    },
    FailureCode.CODE_SYNTAX_ERROR: {
        "description": "Üretilen kod syntax hatası içeriyor",
        "strategy": "lint_and_fix",
        "steps": [
            "Kodu lint/compile ile kontrol et",
            "Hata satırlarını çıkar",
            "Sadece hatalı bloğu düzelt (patch repair)",
        ],
        "validation": "lint_exit_code == 0",
    },
    FailureCode.LLM_EMPTY_RESPONSE: {
        "description": "LLM boş yanıt döndü",
        "strategy": "retry_with_simpler_prompt",
        "steps": [
            "Prompt'u sadeleştir",
            "Temperature artır",
            "Fallback modele geç",
        ],
        "validation": "len(response.strip()) >= 20",
    },
    FailureCode.CONTRACT_ARTIFACT_MISSING: {
        "description": "Contract'ta beklenen dosya disk'te yok",
        "strategy": "retry_missing_only",
        "steps": [
            "Eksik artifact'ı tespit et",
            "Sadece o artifact'ı üretecek node'u tekrar çalıştır",
            "DAG'da sadece ilgili dalı retry et",
        ],
        "validation": "os.path.exists(artifact_path)",
    },
}


class FailureClustering:
    """Hata kodu izleme ve clustering."""

    def __init__(self):
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()
        self._cache: Counter = Counter()

    def _init_db(self):
        try:
            with sqlite3.connect(_DB_PATH) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS failures (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp REAL NOT NULL,
                        code TEXT NOT NULL,
                        job_type TEXT,
                        context TEXT,
                        resolved INTEGER DEFAULT 0
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_code ON failures (code)")
                conn.commit()
        except Exception as e:
            logger.error(f"Failure DB init failed: {e}")

    def record(self, code: str, job_type: str = "", context: str = ""):
        """Hata kaydı."""
        self._cache[code] += 1
        try:
            with sqlite3.connect(_DB_PATH) as conn:
                conn.execute(
                    "INSERT INTO failures (timestamp, code, job_type, context) VALUES (?, ?, ?, ?)",
                    (time.time(), code, job_type, context[:500])
                )
                conn.commit()
        except Exception as e:
            logger.error(f"Failure record failed: {e}")

    def get_top_failures(self, limit: int = 10, days: int = 30) -> List[Tuple[str, int]]:
        """En sık hata kodları."""
        try:
            cutoff = time.time() - (days * 86400)
            with sqlite3.connect(_DB_PATH) as conn:
                rows = conn.execute(
                    "SELECT code, COUNT(*) as cnt FROM failures WHERE timestamp > ? GROUP BY code ORDER BY cnt DESC LIMIT ?",
                    (cutoff, limit)
                ).fetchall()
            return [(row[0], row[1]) for row in rows]
        except Exception:
            return list(self._cache.most_common(limit))

    def get_playbook(self, code: str) -> Optional[Dict[str, Any]]:
        """Hata kodu için auto-patch playbook."""
        return AUTO_PATCH_PLAYBOOKS.get(code)

    def suggest_fix(self, code: str) -> str:
        """Hata kodu için düzeltme önerisi."""
        playbook = self.get_playbook(code)
        if not playbook:
            return f"Bilinmeyen hata kodu: {code}"

        steps = "\n".join(f"  {i+1}. {s}" for i, s in enumerate(playbook["steps"]))
        return f"🔧 {playbook['description']}\nStrateji: {playbook['strategy']}\n{steps}"

    def get_stats(self) -> Dict[str, Any]:
        """Hata istatistikleri."""
        top = self.get_top_failures(10)
        total = sum(c for _, c in top)
        return {
            "total_failures": total,
            "top_10": [{"code": code, "count": count, "has_playbook": code in AUTO_PATCH_PLAYBOOKS}
                       for code, count in top],
            "playbook_coverage": f"{sum(1 for c, _ in top if c in AUTO_PATCH_PLAYBOOKS)}/{len(top)}",
        }

    def detect_failure_code(self, error_msg: str, tool_name: str = "",
                           response: str = "") -> str:
        """Hata mesajından otomatik failure code çıkar."""
        err_low = error_msg.lower()
        resp_low = response.lower()

        if "timeout" in err_low:
            return FailureCode.TOOL_TIMEOUT
        if "permission" in err_low or "denied" in err_low:
            return FailureCode.TOOL_PERMISSION
        if "not found" in err_low and "tool" in err_low:
            return FailureCode.TOOL_NOT_FOUND
        if "empty" in err_low or "size 0" in err_low:
            return FailureCode.TOOL_WRITE_EMPTY
        if "syntax" in err_low:
            return FailureCode.CODE_SYNTAX_ERROR
        if "html" in err_low and ("invalid" in err_low or "missing" in err_low):
            return FailureCode.HTML_BAD_STRUCTURE
        if not response.strip():
            return FailureCode.LLM_EMPTY_RESPONSE

        # Evidence-related
        from core.evidence_gate import evidence_gate
        if evidence_gate.has_delivery_claims(response):
            return FailureCode.DELIVERY_FALSE_CLAIM

        return FailureCode.TOOL_WRITE_FAILED  # Default


# Global instance
failure_clustering = FailureClustering()
