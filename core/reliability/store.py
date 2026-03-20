from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from core.ml.types import DecisionRecord, OutcomeRecord
from core.storage_paths import resolve_elyan_data_dir


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class OutcomeStore:
    def __init__(self, storage_root: Path | None = None):
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "reliability")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_root / "outcomes.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS decisions (
                    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    selected TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    raw_confidence REAL NOT NULL,
                    channel TEXT NOT NULL,
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    outcome_status TEXT NOT NULL DEFAULT '',
                    success_label INTEGER,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reliability_decisions_req
                    ON decisions(request_id, user_id, kind);
                CREATE INDEX IF NOT EXISTS idx_reliability_decisions_kind
                    ON decisions(kind, selected, created_at DESC);

                CREATE TABLE IF NOT EXISTS outcomes (
                    outcome_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    request_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    final_outcome TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    verification_json TEXT NOT NULL,
                    user_feedback_json TEXT NOT NULL,
                    decision_trace_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_reliability_outcomes_req
                    ON outcomes(request_id, user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_reliability_outcomes_user
                    ON outcomes(user_id, created_at DESC);
                """
            )
            conn.commit()

    def record_decision(
        self,
        *,
        request_id: str,
        user_id: str,
        kind: str,
        selected: str,
        confidence: float,
        raw_confidence: float = 0.0,
        channel: str = "",
        source: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = DecisionRecord(
            request_id=str(request_id or ""),
            user_id=str(user_id or "local"),
            kind=str(kind or "unknown"),
            selected=str(selected or "unknown"),
            confidence=float(confidence or 0.0),
            raw_confidence=float(raw_confidence or 0.0),
            channel=str(channel or ""),
            source=str(source or ""),
            metadata=dict(metadata or {}),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO decisions(
                    request_id, user_id, kind, selected, confidence, raw_confidence,
                    channel, source, metadata_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.request_id,
                    record.user_id,
                    record.kind,
                    record.selected,
                    record.confidence,
                    record.raw_confidence,
                    record.channel,
                    record.source,
                    _safe_json(record.metadata),
                    record.created_at,
                ),
            )
            conn.commit()
        return record.to_dict()

    def record_outcome(
        self,
        *,
        request_id: str,
        user_id: str,
        action: str,
        channel: str,
        final_outcome: str,
        success: bool,
        verification_result: dict[str, Any] | None = None,
        user_feedback: dict[str, Any] | None = None,
        decision_trace: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        record = OutcomeRecord(
            request_id=str(request_id or ""),
            user_id=str(user_id or "local"),
            action=str(action or ""),
            channel=str(channel or ""),
            final_outcome=str(final_outcome or ""),
            success=bool(success),
            verification_result=dict(verification_result or {}),
            user_feedback=dict(user_feedback or {}),
            decision_trace=dict(decision_trace or {}),
            metadata=dict(metadata or {}),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO outcomes(
                    request_id, user_id, action_name, channel, final_outcome, success,
                    verification_json, user_feedback_json, decision_trace_json, metadata_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.request_id,
                    record.user_id,
                    record.action,
                    record.channel,
                    record.final_outcome,
                    1 if record.success else 0,
                    _safe_json(record.verification_result),
                    _safe_json(record.user_feedback),
                    _safe_json(record.decision_trace),
                    _safe_json(record.metadata),
                    record.created_at,
                ),
            )
            if record.request_id:
                conn.execute(
                    """
                    UPDATE decisions
                    SET outcome_status = ?, success_label = ?
                    WHERE request_id = ? AND user_id = ?
                    """,
                    (
                        record.final_outcome,
                        1 if record.success else 0,
                        record.request_id,
                        record.user_id,
                    ),
                )
            conn.commit()
        return record.to_dict()

    def decisions_for_request(self, request_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT *
                FROM decisions
                WHERE request_id = ?
                ORDER BY created_at ASC, decision_id ASC
                """,
                (str(request_id or ""),),
            ).fetchall()
        return [self._load_decision(row) for row in rows]

    def recent_outcomes(
        self,
        user_id: str | None = None,
        *,
        limit: int = 50,
        only_failures: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        where: list[str] = []
        if user_id:
            where.append("user_id = ?")
            params.append(str(user_id))
        if only_failures:
            where.append("success = 0")
        query = "SELECT * FROM outcomes"
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(max(1, int(limit or 50)))
        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._load_outcome(row) for row in rows]

    def decision_performance(self, kind: str, selected: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS sample_count,
                    AVG(CASE WHEN success_label IS NULL THEN NULL ELSE success_label END) AS success_rate
                FROM decisions
                WHERE kind = ? AND selected = ?
                """,
                (str(kind or ""), str(selected or "")),
            ).fetchone()
        return {
            "sample_count": int((row["sample_count"] if row else 0) or 0),
            "success_rate": float((row["success_rate"] if row and row["success_rate"] is not None else 0.0) or 0.0),
        }

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            dec = conn.execute("SELECT COUNT(*) AS cnt FROM decisions").fetchone()
            out = conn.execute("SELECT COUNT(*) AS cnt FROM outcomes").fetchone()
            succ = conn.execute("SELECT COUNT(*) AS cnt FROM outcomes WHERE success = 1").fetchone()
        total_outcomes = int((out["cnt"] if out else 0) or 0)
        success_count = int((succ["cnt"] if succ else 0) or 0)
        return {
            "db_path": str(self.db_path),
            "decisions": int((dec["cnt"] if dec else 0) or 0),
            "outcomes": total_outcomes,
            "success_rate": round(success_count / total_outcomes, 4) if total_outcomes else 0.0,
        }

    def delete_user(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        with self._connect() as conn:
            dec = conn.execute("SELECT COUNT(*) AS cnt FROM decisions WHERE user_id = ?", (uid,)).fetchone()
            out = conn.execute("SELECT COUNT(*) AS cnt FROM outcomes WHERE user_id = ?", (uid,)).fetchone()
            conn.execute("DELETE FROM decisions WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM outcomes WHERE user_id = ?", (uid,))
            conn.commit()
        return {
            "user_id": uid,
            "deleted_decisions": int((dec["cnt"] if dec else 0) or 0),
            "deleted_outcomes": int((out["cnt"] if out else 0) or 0),
        }

    @staticmethod
    def _load_decision(row: sqlite3.Row) -> dict[str, Any]:
        try:
            metadata = json.loads(str(row["metadata_json"] or "{}"))
        except Exception:
            metadata = {}
        return {
            "request_id": str(row["request_id"] or ""),
            "user_id": str(row["user_id"] or ""),
            "kind": str(row["kind"] or ""),
            "selected": str(row["selected"] or ""),
            "confidence": float(row["confidence"] or 0.0),
            "raw_confidence": float(row["raw_confidence"] or 0.0),
            "channel": str(row["channel"] or ""),
            "source": str(row["source"] or ""),
            "metadata": metadata,
            "outcome_status": str(row["outcome_status"] or ""),
            "success_label": None if row["success_label"] is None else bool(int(row["success_label"] or 0)),
            "created_at": float(row["created_at"] or 0.0),
        }

    @staticmethod
    def _load_outcome(row: sqlite3.Row) -> dict[str, Any]:
        def _parse(name: str) -> dict[str, Any]:
            try:
                value = json.loads(str(row[name] or "{}"))
            except Exception:
                value = {}
            return value if isinstance(value, dict) else {}

        return {
            "request_id": str(row["request_id"] or ""),
            "user_id": str(row["user_id"] or ""),
            "action": str(row["action_name"] or ""),
            "channel": str(row["channel"] or ""),
            "final_outcome": str(row["final_outcome"] or ""),
            "success": bool(int(row["success"] or 0)),
            "verification_result": _parse("verification_json"),
            "user_feedback": _parse("user_feedback_json"),
            "decision_trace": _parse("decision_trace_json"),
            "metadata": _parse("metadata_json"),
            "created_at": float(row["created_at"] or 0.0),
        }


class FailureClusterer:
    def __init__(self, store: OutcomeStore):
        self.store = store

    @staticmethod
    def _normalize(text: str) -> str:
        low = str(text or "").lower().strip()
        low = re.sub(r"/[^\\s]+", "/<path>", low)
        low = re.sub(r"\d+", "<n>", low)
        low = re.sub(r"\s+", " ", low)
        return low[:180]

    def cluster(self, outcomes: list[dict[str, Any]] | None = None, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = list(outcomes or self.store.recent_outcomes(limit=limit, only_failures=True))
        buckets: dict[str, dict[str, Any]] = {}
        for row in rows:
            meta = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
            verify = row.get("verification_result", {}) if isinstance(row.get("verification_result"), dict) else {}
            sample = " | ".join(
                item
                for item in (
                    str(row.get("action") or ""),
                    str(row.get("final_outcome") or ""),
                    str(meta.get("error") or meta.get("reason") or ""),
                    ", ".join(list(verify.get("reasons") or [])[:3]),
                )
                if item
            )
            fingerprint = self._normalize(sample or "unknown_failure")
            bucket = buckets.setdefault(
                fingerprint,
                {
                    "fingerprint": fingerprint,
                    "count": 0,
                    "actions": set(),
                    "sample_outcomes": [],
                },
            )
            bucket["count"] += 1
            if row.get("action"):
                bucket["actions"].add(str(row.get("action")))
            if len(bucket["sample_outcomes"]) < 3:
                bucket["sample_outcomes"].append(row)
        clusters = []
        for bucket in buckets.values():
            clusters.append(
                {
                    "fingerprint": bucket["fingerprint"],
                    "count": bucket["count"],
                    "actions": sorted(bucket["actions"]),
                    "sample_outcomes": bucket["sample_outcomes"],
                }
            )
        clusters.sort(key=lambda item: (-int(item["count"]), item["fingerprint"]))
        return clusters


class ConfidenceCalibrator:
    def __init__(self, store: OutcomeStore):
        self.store = store

    def calibrate(self, decision_kind: str, selected: str, raw_confidence: float) -> float:
        raw = max(0.0, min(1.0, float(raw_confidence or 0.0)))
        stats = self.store.decision_performance(decision_kind, selected)
        sample_count = int(stats.get("sample_count", 0) or 0)
        success_rate = float(stats.get("success_rate", 0.0) or 0.0)
        if sample_count < 5:
            return raw
        weight = min(0.35, 0.1 + (sample_count / 100.0))
        return max(0.0, min(1.0, (raw * (1.0 - weight)) + (success_rate * weight)))


class RegressionEvaluator:
    def __init__(self, store: OutcomeStore, clusterer: FailureClusterer):
        self.store = store
        self.clusterer = clusterer

    def run_offline_suite(self, model_or_adapter_id: str = "") -> dict[str, Any]:
        decisions = self.store.decisions_for_request("") if False else []
        outcomes = self.store.recent_outcomes(limit=500)
        failures = [row for row in outcomes if not bool(row.get("success"))]
        verification_rows = [
            row for row in outcomes
            if isinstance(row.get("verification_result"), dict) and row["verification_result"]
        ]
        clarify_count = 0
        route_decisions = 0
        route_success = 0
        intent_decisions = 0
        intent_success = 0

        with self.store._connect() as conn:  # noqa: SLF001
            decision_rows = conn.execute(
                "SELECT kind, selected, success_label FROM decisions ORDER BY created_at DESC LIMIT 1000"
            ).fetchall()
        for row in decision_rows:
            kind = str(row["kind"] or "")
            selected = str(row["selected"] or "")
            success_label = row["success_label"]
            if kind == "clarification_policy" and selected == "clarify":
                clarify_count += 1
            if kind == "route_choice":
                route_decisions += 1
                if success_label not in (None, 0):
                    route_success += 1
            if kind == "intent_prediction":
                intent_decisions += 1
                if success_label not in (None, 0):
                    intent_success += 1
        false_positive_count = 0
        for row in failures:
            meta = row.get("metadata", {}) if isinstance(row.get("metadata"), dict) else {}
            tool_call = meta.get("tool_call_result", {}) if isinstance(meta.get("tool_call_result"), dict) else {}
            if int(tool_call.get("tool_count", 0) or 0) > 0:
                false_positive_count += 1
        verification_pass = 0
        for row in verification_rows:
            verify = row.get("verification_result", {}) if isinstance(row.get("verification_result"), dict) else {}
            if bool(verify.get("ok")):
                verification_pass += 1
        clusters = self.clusterer.cluster(failures, limit=200)
        total_outcomes = len(outcomes)
        return {
            "model_or_adapter_id": str(model_or_adapter_id or ""),
            "sample_size": total_outcomes,
            "intent_accuracy_proxy": round(intent_success / intent_decisions, 4) if intent_decisions else 0.0,
            "route_selection_precision": round(route_success / route_decisions, 4) if route_decisions else 0.0,
            "false_positive_execution_rate": round(false_positive_count / max(1, len(failures)), 4) if failures else 0.0,
            "verification_pass_rate": round(verification_pass / len(verification_rows), 4) if verification_rows else 0.0,
            "clarification_rate": round(clarify_count / max(1, len(decision_rows)), 4) if decision_rows else 0.0,
            "failure_clusters": clusters[:5],
        }

    def summary(self) -> dict[str, Any]:
        suite = self.run_offline_suite()
        return {
            "sample_size": suite["sample_size"],
            "intent_accuracy_proxy": suite["intent_accuracy_proxy"],
            "route_selection_precision": suite["route_selection_precision"],
            "false_positive_execution_rate": suite["false_positive_execution_rate"],
            "verification_pass_rate": suite["verification_pass_rate"],
            "clarification_rate": suite["clarification_rate"],
            "top_failure_clusters": suite["failure_clusters"][:3],
        }


_store: OutcomeStore | None = None
_clusterer: FailureClusterer | None = None
_calibrator: ConfidenceCalibrator | None = None
_evaluator: RegressionEvaluator | None = None


def get_outcome_store() -> OutcomeStore:
    global _store
    if _store is None:
        _store = OutcomeStore()
    return _store


def get_failure_clusterer() -> FailureClusterer:
    global _clusterer
    if _clusterer is None:
        _clusterer = FailureClusterer(get_outcome_store())
    return _clusterer


def get_confidence_calibrator() -> ConfidenceCalibrator:
    global _calibrator
    if _calibrator is None:
        _calibrator = ConfidenceCalibrator(get_outcome_store())
    return _calibrator


def get_regression_evaluator() -> RegressionEvaluator:
    global _evaluator
    if _evaluator is None:
        _evaluator = RegressionEvaluator(get_outcome_store(), get_failure_clusterer())
    return _evaluator
