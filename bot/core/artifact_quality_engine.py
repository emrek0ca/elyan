"""
Artifact quality scoring and publish-ready gating.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("artifact_quality")


class ArtifactQualityEngine:
    def __init__(self, db_path: Path | None = None):
        if db_path is None:
            preferred = Path.home() / ".elyan"
            fallback = Path(__file__).parent.parent / ".elyan"
            target_dir = preferred
            try:
                preferred.mkdir(parents=True, exist_ok=True)
                probe = preferred / ".write_test"
                probe.write_text("ok", encoding="utf-8")
                probe.unlink(missing_ok=True)
            except Exception:
                fallback.mkdir(parents=True, exist_ok=True)
                target_dir = fallback
            db_path = target_dir / "artifact_quality.db"
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL NOT NULL,
                    domain TEXT NOT NULL,
                    pipeline_id TEXT,
                    overall_score REAL NOT NULL,
                    publish_ready INTEGER NOT NULL,
                    completeness REAL NOT NULL,
                    correctness REAL NOT NULL,
                    reproducibility REAL NOT NULL,
                    usability REAL NOT NULL,
                    checklist_coverage REAL NOT NULL,
                    task_total INTEGER NOT NULL,
                    task_failed INTEGER NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_ts ON quality_events(ts)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quality_domain ON quality_events(domain)")
            conn.commit()

    @staticmethod
    def _extract_artifact_paths(execution_result: dict[str, Any]) -> tuple[int, int]:
        total = 0
        existing = 0
        results = execution_result.get("data", {}).get("results", [])
        for row in results:
            payload = row.get("data") or {}
            candidates: list[str] = []
            for key in ("path", "file_path", "output_path", "filename"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    candidates.append(value.strip())
            for key in ("outputs", "files_created"):
                values = payload.get(key)
                if isinstance(values, list):
                    for item in values:
                        if isinstance(item, str) and item.strip():
                            candidates.append(item.strip())
            if not candidates:
                continue
            total += len(candidates)
            for candidate in candidates:
                try:
                    if Path(candidate).expanduser().exists():
                        existing += 1
                except Exception:
                    continue
        return total, existing

    @staticmethod
    def _checklist_coverage(
        checklist: list[str],
        execution_result: dict[str, Any],
        completeness: float,
        correctness: float,
        reproducibility: float,
        usability: float,
    ) -> float:
        if not checklist:
            return 100.0

        score_map = {
            "correctness": correctness,
            "clarity": usability,
            "completeness": completeness,
            "reproducibility": reproducibility,
            "testability": correctness,
            "readability": usability,
            "source_quality": correctness,
            "coverage": completeness,
            "traceability": reproducibility,
            "actionability": usability,
            "style_consistency": usability,
            "brand_alignment": usability,
            "professional_tone": usability,
            "conciseness": usability,
            "fidelity": correctness,
            "maintainable": correctness,
            "performant": correctness,
            "accessible": usability,
            "responsive": completeness,
        }
        checks = []
        payload_text = json.dumps(execution_result, ensure_ascii=False).lower()
        for item in checklist:
            key = str(item or "").strip().lower()
            if not key:
                continue
            if key in score_map:
                checks.append(score_map[key])
                continue
            if key in payload_text:
                checks.append(90.0)
            else:
                checks.append(65.0)
        return round(sum(checks) / len(checks), 1) if checks else 100.0

    def evaluate(
        self,
        *,
        domain: str,
        pipeline_id: str | None,
        task_contract: dict[str, Any],
        execution_result: dict[str, Any],
        tasks: list[Any],
        publish_threshold: float = 78.0,
    ) -> dict[str, Any]:
        total = max(1, len(tasks))
        failed = int(execution_result.get("failed", 0) or 0)
        succeeded = int(execution_result.get("succeeded", 0) or 0)

        completeness = max(0.0, min(100.0, (succeeded / total) * 100.0))
        correctness_penalty = min(100.0, failed * 35.0)
        correctness = max(0.0, 100.0 - correctness_penalty)

        artifact_total, artifact_existing = self._extract_artifact_paths(execution_result)
        if artifact_total > 0:
            reproducibility = max(35.0, min(100.0, (artifact_existing / artifact_total) * 100.0))
        else:
            reproducibility = 75.0 if failed == 0 else 55.0

        results = execution_result.get("data", {}).get("results", [])
        useful_messages = sum(1 for row in results if str(row.get("message", "")).strip())
        usability = max(
            45.0,
            min(
                100.0,
                60.0 + (useful_messages * 8.0) - (failed * 6.0),
            ),
        )

        checklist = task_contract.get("quality_checklist", []) if isinstance(task_contract, dict) else []
        checklist_coverage = self._checklist_coverage(
            checklist=checklist if isinstance(checklist, list) else [],
            execution_result=execution_result,
            completeness=completeness,
            correctness=correctness,
            reproducibility=reproducibility,
            usability=usability,
        )

        overall = (
            (completeness * 0.26)
            + (correctness * 0.30)
            + (reproducibility * 0.24)
            + (usability * 0.12)
            + (checklist_coverage * 0.08)
        )
        overall = round(max(0.0, min(100.0, overall)), 1)

        publish_ready = bool(
            failed == 0
            and completeness >= 85.0
            and checklist_coverage >= 70.0
            and overall >= float(publish_threshold)
        )

        report = {
            "domain": str(domain or "general"),
            "pipeline_id": pipeline_id,
            "overall_score": overall,
            "publish_ready": publish_ready,
            "threshold": float(publish_threshold),
            "dimensions": {
                "completeness": round(completeness, 1),
                "correctness": round(correctness, 1),
                "reproducibility": round(reproducibility, 1),
                "usability": round(usability, 1),
                "checklist_coverage": round(checklist_coverage, 1),
            },
            "task_total": total,
            "task_failed": failed,
        }
        self._record(report)
        return report

    def _record(self, report: dict[str, Any]):
        try:
            dims = report.get("dimensions", {})
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO quality_events (
                        ts, domain, pipeline_id, overall_score, publish_ready,
                        completeness, correctness, reproducibility, usability, checklist_coverage,
                        task_total, task_failed
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        time.time(),
                        str(report.get("domain", "general")),
                        str(report.get("pipeline_id") or ""),
                        float(report.get("overall_score", 0.0)),
                        1 if bool(report.get("publish_ready")) else 0,
                        float(dims.get("completeness", 0.0)),
                        float(dims.get("correctness", 0.0)),
                        float(dims.get("reproducibility", 0.0)),
                        float(dims.get("usability", 0.0)),
                        float(dims.get("checklist_coverage", 0.0)),
                        int(report.get("task_total", 0) or 0),
                        int(report.get("task_failed", 0) or 0),
                    ),
                )
                conn.commit()
        except Exception as exc:
            logger.debug(f"artifact_quality record failed: {exc}")

    def summary(self, window_hours: int = 24) -> dict[str, Any]:
        cutoff = time.time() - max(1, int(window_hours)) * 3600
        result: dict[str, Any] = {
            "window_hours": window_hours,
            "total": 0,
            "avg_quality_score": 0.0,
            "publish_ready_rate": 0.0,
            "top_domain": "general",
            "domains": {},
        }
        try:
            with sqlite3.connect(self.db_path) as conn:
                row = conn.execute(
                    "SELECT COUNT(*), AVG(overall_score), AVG(publish_ready) FROM quality_events WHERE ts >= ?",
                    (cutoff,),
                ).fetchone()
                total = int(row[0] or 0)
                avg_quality = float(row[1] or 0.0)
                publish_rate = float(row[2] or 0.0) * 100.0
                result["total"] = total
                result["avg_quality_score"] = round(avg_quality, 1)
                result["publish_ready_rate"] = round(publish_rate, 1)

                rows = conn.execute(
                    """
                    SELECT domain, COUNT(*), AVG(overall_score), AVG(publish_ready)
                    FROM quality_events
                    WHERE ts >= ?
                    GROUP BY domain
                    ORDER BY COUNT(*) DESC
                    """,
                    (cutoff,),
                ).fetchall()
                if rows:
                    result["top_domain"] = str(rows[0][0] or "general")
                for r in rows:
                    domain = str(r[0] or "general")
                    result["domains"][domain] = {
                        "total": int(r[1] or 0),
                        "avg_quality_score": round(float(r[2] or 0.0), 1),
                        "publish_ready_rate": round(float(r[3] or 0.0) * 100.0, 1),
                    }
        except Exception as exc:
            logger.debug(f"artifact_quality summary failed: {exc}")
        return result


_artifact_quality_engine: ArtifactQualityEngine | None = None


def get_artifact_quality_engine() -> ArtifactQualityEngine:
    global _artifact_quality_engine
    if _artifact_quality_engine is None:
        _artifact_quality_engine = ArtifactQualityEngine()
    return _artifact_quality_engine
