from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

from core.ml.types import PreferencePair, RewardEvent
from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("personalization.reward")

_ZERO_REWARD_EVENTS = {"delete", "short_dwell", "channel_close", "network_disconnect"}


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


class RewardService:
    def __init__(self, storage_root: Path | None = None):
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "personalization" / "reward")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_root / "reward.sqlite3"
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS feedback_events (
                    event_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    interaction_id TEXT,
                    event_type TEXT NOT NULL,
                    reward REAL NOT NULL,
                    strategy TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_events_user_time
                    ON feedback_events(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS preference_pairs (
                    pair_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    interaction_id TEXT,
                    chosen_response TEXT NOT NULL,
                    rejected_response TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                """
            )
            conn.commit()

    def normalize_feedback(
        self,
        *,
        event_type: str,
        score: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_type = str(event_type or "").strip().lower()
        meta = dict(metadata or {})
        reward = 0.0
        category = "neutral"
        strategy = "ppo"
        if raw_type in {"like", "thumbs_up", "positive"}:
            reward = 1.0
            category = "explicit_positive"
        elif raw_type in {"dislike", "thumbs_down", "negative"}:
            reward = -0.8
            category = "explicit_negative"
        elif raw_type == "rating":
            try:
                normalized = (float(score or 0.0) - 3.0) / 2.0
            except Exception:
                normalized = 0.0
            reward = max(-1.0, min(1.0, normalized))
            category = "explicit_rating"
        elif raw_type == "correction":
            reward = -0.9
            category = "explicit_correction"
        elif raw_type == "copy":
            reward = 0.35
            category = "implicit_safe_positive"
        elif raw_type == "keep":
            reward = 0.45
            category = "implicit_safe_positive"
        elif raw_type == "accepted_edit":
            distance = float(meta.get("edit_distance", 1.0) or 1.0)
            reward = 0.55 if distance <= 0.25 else 0.15
            category = "implicit_safe_positive"
        elif raw_type in {"latency", "latency_reward"}:
            latency_ms = float(meta.get("latency_ms", score or 0.0) or 0.0)
            target_ms = float(meta.get("target_ms", meta.get("budget_ms", 800.0)) or 800.0)
            if target_ms <= 0:
                target_ms = 800.0
            reward = max(-1.0, min(1.0, 1.0 - (latency_ms / target_ms)))
            category = "latency_reward"
        elif raw_type in _ZERO_REWARD_EVENTS:
            reward = 0.0
            category = "neutral_ignored"
        elif raw_type == "feedback_score":
            reward = max(-1.0, min(1.0, float(score or 0.0)))
            category = "explicit_scalar"

        chosen = str(meta.get("chosen_response") or "").strip()
        rejected = str(meta.get("rejected_response") or "").strip()
        if chosen and rejected and chosen != rejected:
            strategy = "dpo"
        return {
            "event_type": raw_type or "unknown",
            "reward": float(reward),
            "category": category,
            "strategy": strategy,
            "metadata": meta,
            "ignored_negative": raw_type in _ZERO_REWARD_EVENTS,
        }

    def record_feedback(
        self,
        *,
        user_id: str,
        interaction_id: str = "",
        event_type: str,
        score: float | int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        normalized = self.normalize_feedback(event_type=event_type, score=score, metadata=metadata)
        event_id = str(uuid.uuid4())
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO feedback_events(event_id, user_id, interaction_id, event_type, reward, strategy, metadata_json, created_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    uid,
                    str(interaction_id or ""),
                    str(normalized["event_type"]),
                    float(normalized["reward"]),
                    str(normalized["strategy"]),
                    _safe_json(normalized["metadata"]),
                    _now(),
                ),
            )
            if normalized["strategy"] == "dpo":
                pair_id = str(uuid.uuid4())
                conn.execute(
                    """
                    INSERT INTO preference_pairs(pair_id, user_id, interaction_id, chosen_response, rejected_response, metadata_json, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        pair_id,
                        uid,
                        str(interaction_id or ""),
                        str(normalized["metadata"].get("chosen_response") or ""),
                        str(normalized["metadata"].get("rejected_response") or ""),
                        _safe_json(normalized["metadata"]),
                        _now(),
                    ),
                )
            conn.commit()
        return {
            "event_id": event_id,
            **normalized,
        }

    def list_feedback(self, user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, interaction_id, event_type, reward, strategy, metadata_json, created_at
                FROM feedback_events
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (str(user_id or "local"), max(1, int(limit or 20))),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except Exception:
                metadata = {}
            out.append(
                {
                    "event_id": str(row["event_id"]),
                    "interaction_id": str(row["interaction_id"] or ""),
                    "event_type": str(row["event_type"] or ""),
                    "reward": float(row["reward"] or 0.0),
                    "strategy": str(row["strategy"] or "ppo"),
                    "metadata": metadata,
                    "created_at": float(row["created_at"] or 0.0),
                }
            )
        return out

    def aggregate_user_feedback(self, user_id: str) -> dict[str, Any]:
        events = self.list_feedback(user_id, limit=500)
        preference_pairs = 0
        explicit_events = 0
        safe_implicit_events = 0
        rewards = []
        for event in events:
            rewards.append(float(event.get("reward", 0.0) or 0.0))
            event_type = str(event.get("event_type") or "")
            if event_type in {"like", "thumbs_up", "positive", "dislike", "thumbs_down", "negative", "rating", "correction", "feedback_score"}:
                explicit_events += 1
            elif event_type in {"copy", "keep", "accepted_edit"}:
                safe_implicit_events += 1
            if str(event.get("strategy") or "") == "dpo":
                preference_pairs += 1
        return {
            "user_id": str(user_id or "local"),
            "feedback_events": len(events),
            "explicit_events": explicit_events,
            "safe_implicit_events": safe_implicit_events,
            "preference_pairs": preference_pairs,
            "avg_reward": round(sum(rewards) / len(rewards), 4) if rewards else 0.0,
        }

    def delete_user(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        with self._connect() as conn:
            ev_row = conn.execute("SELECT COUNT(*) AS cnt FROM feedback_events WHERE user_id = ?", (uid,)).fetchone()
            pair_row = conn.execute("SELECT COUNT(*) AS cnt FROM preference_pairs WHERE user_id = ?", (uid,)).fetchone()
            conn.execute("DELETE FROM feedback_events WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM preference_pairs WHERE user_id = ?", (uid,))
            conn.commit()
        return {
            "user_id": uid,
            "deleted_feedback_events": int((ev_row["cnt"] if ev_row else 0) or 0),
            "deleted_preference_pairs": int((pair_row["cnt"] if pair_row else 0) or 0),
        }

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            events = conn.execute("SELECT COUNT(*) AS cnt FROM feedback_events").fetchone()
            pairs = conn.execute("SELECT COUNT(*) AS cnt FROM preference_pairs").fetchone()
        return {
            "db_path": str(self.db_path),
            "feedback_events": int((events["cnt"] if events else 0) or 0),
            "preference_pairs": int((pairs["cnt"] if pairs else 0) or 0),
        }


class PreferencePairBuilder:
    def build(
        self,
        *,
        user_id: str,
        interaction_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> PreferencePair | None:
        meta = dict(metadata or {})
        chosen = str(meta.get("chosen_response") or "").strip()
        rejected = str(meta.get("rejected_response") or "").strip()
        if not chosen or not rejected or chosen == rejected:
            return None
        return PreferencePair(
            pair_id=str(uuid.uuid4()),
            user_id=str(user_id or "local"),
            interaction_id=str(interaction_id or ""),
            chosen_response=chosen,
            rejected_response=rejected,
            metadata=meta,
        )


class RewardEventStore:
    def __init__(self, reward_service: RewardService):
        self.reward_service = reward_service
        self.preference_pair_builder = PreferencePairBuilder()

    def record(self, *, user_id: str, interaction_id: str, event_type: str, score: float | int | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.reward_service.record_feedback(
            user_id=user_id,
            interaction_id=interaction_id,
            event_type=event_type,
            score=score,
            metadata=metadata,
        )
        event = RewardEvent(
            event_id=str(result.get("event_id") or ""),
            user_id=str(user_id or "local"),
            interaction_id=str(interaction_id or ""),
            event_type=str(result.get("event_type") or event_type or ""),
            reward=float(result.get("reward", 0.0) or 0.0),
            metadata=dict(result.get("metadata") or {}),
        )
        payload = dict(result)
        payload["event"] = event.to_dict()
        preference_pair = self.preference_pair_builder.build(
            user_id=str(user_id or "local"),
            interaction_id=str(interaction_id or ""),
            metadata=dict(result.get("metadata") or {}),
        )
        if preference_pair is not None:
            payload["preference_pair"] = preference_pair.to_dict()
        return payload

    def list(self, user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.reward_service.list_feedback(user_id, limit=limit)

    def stats(self) -> dict[str, Any]:
        return self.reward_service.get_stats()

    def delete_user(self, user_id: str) -> dict[str, Any]:
        return self.reward_service.delete_user(user_id)
