"""
core/compliance/audit_engine.py
─────────────────────────────────────────────────────────────────────────────
Enterprise Audit & Compliance Engine (Phase 37).
Structured JSON audit logging of every AI action, rate limiting,
quota management, and GDPR/KVKK-compliant data retention.
"""

import json
import time
import asyncio
from pathlib import Path
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from utils.logger import get_logger

logger = get_logger("compliance")

@dataclass
class AuditEntry:
    timestamp: float
    action: str         # "tool_call", "llm_query", "file_access", "network_request"
    actor: str          # "user", "orchestrator", "plugin:name"
    target: str         # what was acted upon
    result: str         # "success", "denied", "error"
    metadata: Dict = field(default_factory=dict)

class AuditEngine:
    def __init__(self, audit_dir: str = None):
        self.audit_dir = Path(audit_dir or Path.home() / ".elyan" / "audit")
        self.audit_dir.mkdir(parents=True, exist_ok=True)
        self._buffer: List[AuditEntry] = []
        self._flush_interval = 30  # seconds
        self._running = False
    
    def log(self, action: str, actor: str, target: str, result: str, **metadata):
        """Log an auditable action."""
        entry = AuditEntry(
            timestamp=time.time(),
            action=action,
            actor=actor,
            target=target,
            result=result,
            metadata=metadata
        )
        self._buffer.append(entry)
        
        # Auto-flush if buffer is large
        if len(self._buffer) >= 50:
            self._flush_sync()
    
    def _flush_sync(self):
        """Write buffered entries to disk."""
        if not self._buffer:
            return
        
        today = time.strftime("%Y-%m-%d")
        log_file = self.audit_dir / f"audit_{today}.jsonl"
        
        with open(log_file, "a", encoding="utf-8") as f:
            for entry in self._buffer:
                line = json.dumps({
                    "ts": entry.timestamp,
                    "action": entry.action,
                    "actor": entry.actor,
                    "target": entry.target,
                    "result": entry.result,
                    **entry.metadata
                }, ensure_ascii=False)
                f.write(line + "\n")
        
        self._buffer.clear()
    
    async def _flush_loop(self):
        """Periodic flush of audit buffer."""
        self._running = True
        while self._running:
            self._flush_sync()
            await asyncio.sleep(self._flush_interval)
    
    def start(self):
        if not self._running:
            asyncio.create_task(self._flush_loop())
    
    def stop(self):
        self._running = False
        self._flush_sync()

class RateLimiter:
    """Token bucket rate limiter for API cost control."""
    
    def __init__(self):
        self._buckets: Dict[str, Dict] = {}
    
    def configure(self, key: str, max_calls: int, window_seconds: int):
        """Configure a rate limit for a specific key (e.g., 'llm.gemini')."""
        self._buckets[key] = {
            "max": max_calls,
            "window": window_seconds,
            "calls": [],
        }
    
    def check(self, key: str) -> bool:
        """Check if an action is allowed under the rate limit."""
        if key not in self._buckets:
            return True  # No limit configured
        
        bucket = self._buckets[key]
        now = time.time()
        
        # Prune old calls
        bucket["calls"] = [t for t in bucket["calls"] if now - t < bucket["window"]]
        
        if len(bucket["calls"]) >= bucket["max"]:
            logger.warning(f"🚫 Rate limit exceeded for '{key}': {len(bucket['calls'])}/{bucket['max']}")
            return False
        
        bucket["calls"].append(now)
        return True
    
    def get_remaining(self, key: str) -> int:
        if key not in self._buckets:
            return -1
        bucket = self._buckets[key]
        now = time.time()
        active = len([t for t in bucket["calls"] if now - t < bucket["window"]])
        return max(0, bucket["max"] - active)

class DataRetentionPolicy:
    """GDPR/KVKK-compliant data retention and purging."""
    
    DEFAULT_RETENTION_DAYS = 90
    
    def __init__(self, audit_dir: Path):
        self.audit_dir = audit_dir
    
    def purge_expired(self, retention_days: int = None):
        """Delete audit logs older than the retention period."""
        days = retention_days or self.DEFAULT_RETENTION_DAYS
        cutoff = time.time() - (days * 86400)
        purged = 0
        
        for log_file in self.audit_dir.glob("audit_*.jsonl"):
            if log_file.stat().st_mtime < cutoff:
                log_file.unlink()
                purged += 1
        
        if purged:
            logger.info(f"🗑️ Purged {purged} audit logs older than {days} days (KVKK compliance).")
    
    def export_user_data(self, user_id: str = "default") -> List[Dict]:
        """GDPR Article 20: Export all data associated with a user."""
        data = []
        for log_file in sorted(self.audit_dir.glob("audit_*.jsonl")):
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("actor") == user_id or user_id == "default":
                            data.append(entry)
                    except:
                        pass
        return data
    
    def erase_user_data(self, user_id: str):
        """GDPR Article 17: Right to erasure (right to be forgotten)."""
        for log_file in self.audit_dir.glob("audit_*.jsonl"):
            lines = []
            with open(log_file, encoding="utf-8") as f:
                for line in f:
                    try:
                        entry = json.loads(line)
                        if entry.get("actor") != user_id:
                            lines.append(line)
                    except:
                        lines.append(line)
            log_file.write_text("".join(lines), encoding="utf-8")
        
        logger.info(f"🗑️ All data for user '{user_id}' erased (GDPR Article 17).")

# Global singletons
audit = AuditEngine()
rate_limiter = RateLimiter()
retention = DataRetentionPolicy(audit.audit_dir)

# Default rate limits
rate_limiter.configure("llm.api", max_calls=100, window_seconds=3600)
rate_limiter.configure("network.external", max_calls=200, window_seconds=3600)
rate_limiter.configure("file.write", max_calls=500, window_seconds=3600)
