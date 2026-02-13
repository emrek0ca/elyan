"""
Capability metrics tracker.
Persists domain-level success and latency stats for dashboard visibility.
"""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("capability_metrics")


class CapabilityMetrics:
    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            preferred = Path.home() / ".wiqo"
            fallback = Path(__file__).parent.parent / ".wiqo"
            target_dir = preferred
            try:
                preferred.mkdir(parents=True, exist_ok=True)
                probe = preferred / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except Exception:
                fallback.mkdir(parents=True, exist_ok=True)
                target_dir = fallback
            db_path = target_dir / "capability_metrics.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS capability_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    domain TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    duration_ms INTEGER NOT NULL,
                    objective TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capability_ts ON capability_events(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_capability_domain ON capability_events(domain)")
            conn.commit()

    def record(self, domain: str, success: bool, duration_ms: int, objective: str = ""):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO capability_events (ts, domain, success, duration_ms, objective)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (time.time(), str(domain or "general"), 1 if success else 0, int(duration_ms or 0), str(objective or "")),
                )
                conn.commit()
        except Exception as exc:
            logger.debug(f"capability_metrics record failed: {exc}")

    def summary(self, window_hours: int = 24) -> dict[str, Any]:
        cutoff = time.time() - (max(1, int(window_hours)) * 3600)
        result: dict[str, Any] = {
            "window_hours": window_hours,
            "total": 0,
            "success_rate": 0.0,
            "avg_duration_ms": 0,
            "top_domain": "general",
            "domains": {},
        }
        try:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    """
                    SELECT domain, COUNT(*) as total, SUM(success) as ok, AVG(duration_ms) as avg_ms
                    FROM capability_events
                    WHERE ts >= ?
                    GROUP BY domain
                    ORDER BY total DESC
                    """,
                    (cutoff,),
                )
                rows = cur.fetchall()
                total = 0
                ok = 0
                top_domain = "general"
                for idx, row in enumerate(rows):
                    domain = str(row[0] or "general")
                    d_total = int(row[1] or 0)
                    d_ok = int(row[2] or 0)
                    d_avg = int(float(row[3] or 0))
                    total += d_total
                    ok += d_ok
                    if idx == 0:
                        top_domain = domain
                    result["domains"][domain] = {
                        "total": d_total,
                        "success_rate": round((d_ok / d_total) * 100, 1) if d_total else 0.0,
                        "avg_duration_ms": d_avg,
                    }
                result["total"] = total
                result["success_rate"] = round((ok / total) * 100, 1) if total else 0.0
                result["top_domain"] = top_domain

                cur2 = conn.execute(
                    "SELECT AVG(duration_ms) FROM capability_events WHERE ts >= ?",
                    (cutoff,),
                )
                row = cur2.fetchone()
                result["avg_duration_ms"] = int(float(row[0] or 0))
        except Exception as exc:
            logger.debug(f"capability_metrics summary failed: {exc}")
        return result


_capability_metrics: CapabilityMetrics | None = None


def get_capability_metrics() -> CapabilityMetrics:
    global _capability_metrics
    if _capability_metrics is None:
        _capability_metrics = CapabilityMetrics()
    return _capability_metrics
