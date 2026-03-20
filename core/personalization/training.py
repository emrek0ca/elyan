from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

from .adapters import AdapterArtifactStore
from .memory import PersonalMemoryStore
from .reward import RewardService

logger = get_logger("personalization.training")


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class AdapterTrainer:
    def __init__(
        self,
        *,
        memory_store: PersonalMemoryStore,
        reward_service: RewardService,
        artifact_store: AdapterArtifactStore,
        replay_window: int = 1000,
    ):
        self.memory_store = memory_store
        self.reward_service = reward_service
        self.artifact_store = artifact_store
        self.replay_window = max(32, int(replay_window or 1000))

    def train_user_adapter(self, job_id: str, user_id: str, base_model_id: str, strategy: str) -> dict[str, Any]:
        interactions = self.memory_store.recent_interactions(user_id, limit=self.replay_window)
        feedback = self.reward_service.aggregate_user_feedback(user_id)
        metrics = {
            "interaction_count": self.memory_store.interaction_count(user_id),
            "feedback_events": int(feedback.get("feedback_events", 0) or 0),
            "preference_pairs": int(feedback.get("preference_pairs", 0) or 0),
            "avg_reward": float(feedback.get("avg_reward", 0.0) or 0.0),
            "replay_buffer_size": len(interactions),
        }
        quality_metrics = {
            "catastrophic_forgetting_guard": "replay_buffer",
            "reference_regularization": "kl",
            "evaluation_gate": True,
            "replay_sample_size": len(interactions),
        }
        return self.artifact_store.create_candidate_adapter(
            user_id=user_id,
            base_model_id=base_model_id,
            strategy=str(strategy or "hybrid"),
            metrics=metrics,
            training_step=int(metrics["interaction_count"]),
            quality_metrics=quality_metrics,
            metadata={"job_id": str(job_id or ""), "optimizer": str(strategy or "hybrid")},
        )


class AdapterEvaluator:
    def __init__(
        self,
        *,
        memory_store: PersonalMemoryStore,
        reward_service: RewardService,
        min_examples: int = 50,
        min_feedback_events: int = 1,
        min_avg_reward: float = -0.2,
    ):
        self.memory_store = memory_store
        self.reward_service = reward_service
        self.min_examples = max(1, int(min_examples or 50))
        self.min_feedback_events = max(0, int(min_feedback_events or 1))
        self.min_avg_reward = float(min_avg_reward)

    def evaluate_candidate(
        self,
        *,
        user_id: str,
        base_model_id: str,
        candidate_manifest: dict[str, Any],
    ) -> dict[str, Any]:
        interactions = self.memory_store.interaction_count(user_id)
        feedback = self.reward_service.aggregate_user_feedback(user_id)
        avg_reward = float(feedback.get("avg_reward", 0.0) or 0.0)
        feedback_events = int(feedback.get("feedback_events", 0) or 0)
        preference_pairs = int(feedback.get("preference_pairs", 0) or 0)
        eligible = interactions >= self.min_examples and feedback_events >= self.min_feedback_events
        promote = eligible and avg_reward >= self.min_avg_reward
        reason = "accepted" if promote else "insufficient_signal"
        if eligible and avg_reward < self.min_avg_reward:
            reason = "reward_below_threshold"
        elif interactions < self.min_examples:
            reason = "below_min_examples"
        elif feedback_events < self.min_feedback_events:
            reason = "insufficient_feedback"
        return {
            "user_id": str(user_id or "local"),
            "base_model_id": str(base_model_id or ""),
            "candidate_adapter_version": str(candidate_manifest.get("adapter_version") or ""),
            "promote": bool(promote),
            "reject": not bool(promote),
            "reason": reason,
            "eval_metrics": {
                "interaction_count": interactions,
                "feedback_events": feedback_events,
                "preference_pairs": preference_pairs,
                "avg_reward": avg_reward,
            },
        }


class TrainerQueue:
    def __init__(
        self,
        *,
        memory_store: PersonalMemoryStore,
        reward_service: RewardService,
        artifact_store: AdapterArtifactStore,
        trainer: AdapterTrainer,
        evaluator: AdapterEvaluator,
        storage_root: Path | None = None,
        min_examples: int = 50,
        cooldown_minutes: int = 60,
    ):
        self.memory_store = memory_store
        self.reward_service = reward_service
        self.artifact_store = artifact_store
        self.trainer = trainer
        self.evaluator = evaluator
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "personalization" / "training")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_root / "trainer_queue.sqlite3"
        self.min_examples = max(1, int(min_examples or 50))
        self.cooldown_minutes = max(0, int(cooldown_minutes or 0))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS training_jobs (
                    job_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    base_model_id TEXT NOT NULL,
                    strategy TEXT NOT NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    started_at REAL,
                    finished_at REAL
                );
                CREATE INDEX IF NOT EXISTS idx_training_jobs_user_time
                    ON training_jobs(user_id, created_at DESC);
                """
            )
            conn.commit()

    def _last_finished_at(self, user_id: str, base_model_id: str) -> float:
        versions = self.artifact_store.list_versions(user_id, base_model_id)
        latest_manifest = versions[0] if versions else {}
        manifest_ts = float(latest_manifest.get("last_trained_at", 0.0) or 0.0)
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT MAX(COALESCE(finished_at, created_at)) AS ts
                FROM training_jobs
                WHERE user_id = ? AND base_model_id = ? AND status IN ('completed', 'promoted')
                """,
                (str(user_id or "local"), str(base_model_id or "")),
            ).fetchone()
        queue_ts = float((row["ts"] if row else 0.0) or 0.0)
        return max(manifest_ts, queue_ts)

    def preview_training_decision(
        self,
        user_id: str,
        base_model_id: str,
        *,
        interaction_count: int | None = None,
        feedback_summary: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        interactions = int(interaction_count if interaction_count is not None else self.memory_store.interaction_count(user_id))
        feedback = dict(feedback_summary or self.reward_service.aggregate_user_feedback(user_id))
        feedback_events = int(feedback.get("feedback_events", 0) or 0)
        preference_pairs = int(feedback.get("preference_pairs", 0) or 0)
        last_finished_at = self._last_finished_at(user_id, base_model_id)
        cooldown_active = False
        remaining_seconds = 0
        if self.cooldown_minutes > 0 and last_finished_at > 0:
            elapsed = _now() - last_finished_at
            threshold = float(self.cooldown_minutes * 60)
            if elapsed < threshold:
                cooldown_active = True
                remaining_seconds = int(max(0.0, threshold - elapsed))
        eligible = interactions >= self.min_examples and feedback_events >= 1 and not cooldown_active
        strategy = "dpo" if preference_pairs > 0 else "ppo"
        reason = "ready" if eligible else "below_min_examples"
        if interactions >= self.min_examples and feedback_events < 1:
            reason = "insufficient_feedback"
        if cooldown_active:
            reason = "cooldown_active"
        return {
            "eligible": bool(eligible),
            "reason": reason,
            "strategy": strategy,
            "interaction_count": interactions,
            "feedback_events": feedback_events,
            "preference_pairs": preference_pairs,
            "cooldown_remaining_seconds": remaining_seconds,
        }

    def enqueue_user_update(
        self,
        *,
        user_id: str,
        base_model_id: str,
        strategy: str = "hybrid",
        force: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        decision = self.preview_training_decision(user_id, base_model_id)
        if not force and not decision.get("eligible"):
            return {"queued": False, "decision": decision}
        job_id = str(uuid.uuid4())
        job_type = "preference_optimization_batch" if decision.get("strategy") == "dpo" else "adapter_finetune_batch"
        payload = {
            "metadata": dict(metadata or {}),
            "decision": decision,
        }
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO training_jobs(job_id, user_id, base_model_id, strategy, job_type, status, payload_json, result_json, created_at)
                VALUES(?, ?, ?, ?, ?, 'pending', ?, '{}', ?)
                """,
                (
                    job_id,
                    str(user_id or "local"),
                    str(base_model_id or ""),
                    str(strategy or "hybrid"),
                    job_type,
                    _safe_json(payload),
                    _now(),
                ),
            )
            conn.commit()
        return {
            "queued": True,
            "job_id": job_id,
            "job_type": job_type,
            "decision": decision,
        }

    def _load_job(self, row: sqlite3.Row) -> dict[str, Any]:
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except Exception:
            payload = {}
        try:
            result = json.loads(str(row["result_json"] or "{}"))
        except Exception:
            result = {}
        return {
            "job_id": str(row["job_id"]),
            "user_id": str(row["user_id"]),
            "base_model_id": str(row["base_model_id"]),
            "strategy": str(row["strategy"]),
            "job_type": str(row["job_type"]),
            "status": str(row["status"]),
            "payload": payload,
            "result": result,
            "created_at": float(row["created_at"] or 0.0),
        }

    def run_once(self) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM training_jobs
                WHERE status = 'pending'
                ORDER BY created_at ASC
                LIMIT 1
                """
            ).fetchone()
            if row is None:
                return {"ran": False, "reason": "empty_queue"}
            conn.execute(
                "UPDATE training_jobs SET status = 'running', started_at = ? WHERE job_id = ?",
                (_now(), str(row["job_id"])),
            )
            conn.commit()

        job = self._load_job(row)
        try:
            candidate = self.trainer.train_user_adapter(
                job["job_id"],
                job["user_id"],
                job["base_model_id"],
                job["strategy"],
            )
            evaluation = self.evaluator.evaluate_candidate(
                user_id=job["user_id"],
                base_model_id=job["base_model_id"],
                candidate_manifest=candidate,
            )
            promoted_manifest = None
            status = "completed"
            if evaluation.get("promote"):
                promoted_manifest = self.artifact_store.promote_version(
                    job["user_id"],
                    job["base_model_id"],
                    str(candidate.get("adapter_version") or ""),
                )
                status = "promoted"
            result = {
                "candidate": candidate,
                "evaluation": evaluation,
                "promoted_manifest": promoted_manifest,
            }
        except Exception as exc:
            logger.exception("Training job failed: %s", exc)
            status = "failed"
            result = {"error": str(exc)}

        with self._connect() as conn:
            conn.execute(
                """
                UPDATE training_jobs
                SET status = ?, result_json = ?, finished_at = ?
                WHERE job_id = ?
                """,
                (status, _safe_json(result), _now(), job["job_id"]),
            )
            conn.commit()
        return {"ran": True, "status": status, "job": job, "result": result}

    def list_jobs(self, user_id: str | None = None, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if user_id:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM training_jobs
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (str(user_id), max(1, int(limit or 20))),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT *
                    FROM training_jobs
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (max(1, int(limit or 20)),),
                ).fetchall()
        return [self._load_job(row) for row in rows]

    def delete_user(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM training_jobs WHERE user_id = ?", (uid,)).fetchone()
            conn.execute("DELETE FROM training_jobs WHERE user_id = ?", (uid,))
            conn.commit()
        return {"user_id": uid, "deleted_jobs": int((row["cnt"] if row else 0) or 0)}

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) AS cnt FROM training_jobs").fetchone()
            pending = conn.execute("SELECT COUNT(*) AS cnt FROM training_jobs WHERE status = 'pending'").fetchone()
            promoted = conn.execute("SELECT COUNT(*) AS cnt FROM training_jobs WHERE status = 'promoted'").fetchone()
        return {
            "db_path": str(self.db_path),
            "jobs_total": int((total["cnt"] if total else 0) or 0),
            "jobs_pending": int((pending["cnt"] if pending else 0) or 0),
            "jobs_promoted": int((promoted["cnt"] if promoted else 0) or 0),
            "min_examples": self.min_examples,
            "cooldown_minutes": self.cooldown_minutes,
        }


class AdapterPromoter:
    def __init__(self, artifact_store: AdapterArtifactStore):
        self.artifact_store = artifact_store

    def promote(self, user_id: str, base_model_id: str, adapter_version: str) -> dict[str, Any] | None:
        return self.artifact_store.promote_version(user_id, base_model_id, adapter_version)


AdapterTrainingQueue = TrainerQueue
