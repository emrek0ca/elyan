from __future__ import annotations

import json
import math
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("personalization.policy_learning")


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


@dataclass
class LearningSignal:
    user_id: str
    task_type: str
    outcome: str
    latency_ms: float
    source: str
    action: str = ""
    agent_id: str = ""
    reward: Optional[float] = None
    retry_count: int = 0
    approval_required: bool = False
    approval_granted: bool = True
    metadata: dict[str, Any] = field(default_factory=dict)


class PolicyLearningStore:
    """
    User-scoped policy learner (Q + UCB).
    Stores raw learning signals (long retention by default) and keeps
    aggregate policy tables for fast online routing decisions.
    """

    def __init__(
        self,
        db_path: Path | None = None,
        *,
        alpha: float = 0.2,
        explore_c: float = 0.35,
    ) -> None:
        root = resolve_elyan_data_dir() / "personalization"
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path or (root / "policy_learning.sqlite3")).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.alpha = max(0.01, min(0.9, float(alpha)))
        self.explore_c = max(0.01, min(3.0, float(explore_c)))
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS user_policy (
                    user_id TEXT PRIMARY KEY,
                    learning_mode TEXT NOT NULL DEFAULT 'hybrid',
                    retention_policy TEXT NOT NULL DEFAULT 'long',
                    paused INTEGER NOT NULL DEFAULT 0,
                    opt_out INTEGER NOT NULL DEFAULT 0,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS learning_signals (
                    signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    latency_ms REAL NOT NULL,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    approval_required INTEGER NOT NULL DEFAULT 0,
                    approval_granted INTEGER NOT NULL DEFAULT 1,
                    reward REAL NOT NULL,
                    source TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_learning_signals_user_time
                    ON learning_signals(user_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_learning_signals_user_task
                    ON learning_signals(user_id, task_type, action, created_at DESC);

                CREATE TABLE IF NOT EXISTS action_policy (
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    action TEXT NOT NULL,
                    q_value REAL NOT NULL DEFAULT 0.0,
                    pulls INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    avg_latency_ms REAL NOT NULL DEFAULT 0.0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, task_type, action)
                );

                CREATE TABLE IF NOT EXISTS agent_policy (
                    user_id TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    agent_id TEXT NOT NULL,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    successes INTEGER NOT NULL DEFAULT 0,
                    avg_latency_ms REAL NOT NULL DEFAULT 0.0,
                    stability REAL NOT NULL DEFAULT 0.8,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, task_type, agent_id)
                );
                """
            )
            conn.commit()

    @staticmethod
    def _normalize_user_id(user_id: str) -> str:
        uid = str(user_id or "local").strip()
        return uid or "local"

    def _ensure_user_policy(self, user_id: str) -> None:
        uid = self._normalize_user_id(user_id)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_policy(user_id, learning_mode, retention_policy, paused, opt_out, updated_at)
                VALUES(?, 'hybrid', 'long', 0, 0, ?)
                ON CONFLICT(user_id) DO NOTHING
                """,
                (uid, _now()),
            )
            conn.commit()

    def get_user_policy(self, user_id: str) -> dict[str, Any]:
        uid = self._normalize_user_id(user_id)
        self._ensure_user_policy(uid)
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM user_policy WHERE user_id = ?", (uid,)).fetchone()
        if not row:
            return {
                "user_id": uid,
                "learning_mode": "hybrid",
                "retention_policy": "long",
                "paused": False,
                "opt_out": False,
            }
        return {
            "user_id": uid,
            "learning_mode": str(row["learning_mode"] or "hybrid"),
            "retention_policy": str(row["retention_policy"] or "long"),
            "paused": bool(int(row["paused"] or 0)),
            "opt_out": bool(int(row["opt_out"] or 0)),
            "updated_at": float(row["updated_at"] or 0.0),
        }

    def set_user_policy(
        self,
        user_id: str,
        *,
        learning_mode: Optional[str] = None,
        retention_policy: Optional[str] = None,
        paused: Optional[bool] = None,
        opt_out: Optional[bool] = None,
    ) -> dict[str, Any]:
        uid = self._normalize_user_id(user_id)
        current = self.get_user_policy(uid)
        lm = str(learning_mode or current.get("learning_mode") or "hybrid").strip().lower()
        if lm not in {"hybrid", "explicit"}:
            lm = "hybrid"
        rp = str(retention_policy or current.get("retention_policy") or "long").strip().lower()
        if rp not in {"long", "short", "aggregate"}:
            rp = "long"
        pz = bool(current.get("paused")) if paused is None else bool(paused)
        oo = bool(current.get("opt_out")) if opt_out is None else bool(opt_out)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO user_policy(user_id, learning_mode, retention_policy, paused, opt_out, updated_at)
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    learning_mode = excluded.learning_mode,
                    retention_policy = excluded.retention_policy,
                    paused = excluded.paused,
                    opt_out = excluded.opt_out,
                    updated_at = excluded.updated_at
                """,
                (uid, lm, rp, int(pz), int(oo), _now()),
            )
            conn.commit()
        if rp == "short":
            self._prune_old_signals(uid, days=30)
        elif rp == "aggregate":
            self._drop_raw_signals(uid)
        return self.get_user_policy(uid)

    def _prune_old_signals(self, user_id: str, *, days: int) -> None:
        cutoff = _now() - (max(1, int(days)) * 86400)
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM learning_signals WHERE user_id = ? AND created_at < ?",
                (self._normalize_user_id(user_id), cutoff),
            )
            conn.commit()

    def _drop_raw_signals(self, user_id: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "DELETE FROM learning_signals WHERE user_id = ?",
                (self._normalize_user_id(user_id),),
            )
            conn.commit()

    def is_learning_enabled(self, user_id: str) -> bool:
        policy = self.get_user_policy(user_id)
        return not bool(policy.get("paused")) and not bool(policy.get("opt_out"))

    @staticmethod
    def _derive_reward(signal: LearningSignal) -> float:
        base = 1.0 if str(signal.outcome).lower() in {"success", "ok", "passed"} else -1.0
        latency_penalty = min(0.7, max(0.0, float(signal.latency_ms or 0.0) / 5000.0))
        retry_penalty = min(0.5, max(0, int(signal.retry_count or 0)) * 0.1)
        approval_penalty = 0.2 if bool(signal.approval_required) and not bool(signal.approval_granted) else 0.0
        reward = base - latency_penalty - retry_penalty - approval_penalty
        return max(-1.0, min(1.0, reward))

    def record_signal(self, signal: LearningSignal) -> dict[str, Any]:
        uid = self._normalize_user_id(signal.user_id)
        if not self.is_learning_enabled(uid):
            return {"success": False, "skipped": "learning_paused_or_opt_out", "user_id": uid}

        reward = float(signal.reward) if signal.reward is not None else self._derive_reward(signal)
        task_type = str(signal.task_type or "general").strip().lower() or "general"
        action = str(signal.action or "unknown").strip().lower() or "unknown"
        agent_id = str(signal.agent_id or "unknown").strip().lower() or "unknown"
        outcome_success = str(signal.outcome or "").strip().lower() in {"success", "ok", "passed"}
        latency_ms = max(0.0, float(signal.latency_ms or 0.0))

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO learning_signals(
                    user_id, task_type, action, agent_id, outcome, latency_ms, retry_count,
                    approval_required, approval_granted, reward, source, metadata_json, created_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    uid,
                    task_type,
                    action,
                    agent_id,
                    "success" if outcome_success else "failed",
                    latency_ms,
                    int(signal.retry_count or 0),
                    int(bool(signal.approval_required)),
                    int(bool(signal.approval_granted)),
                    reward,
                    str(signal.source or "implicit"),
                    _safe_json(dict(signal.metadata or {})),
                    _now(),
                ),
            )

            arow = conn.execute(
                """
                SELECT q_value, pulls, success_count, avg_latency_ms
                FROM action_policy
                WHERE user_id = ? AND task_type = ? AND action = ?
                """,
                (uid, task_type, action),
            ).fetchone()
            if arow:
                old_q = float(arow["q_value"] or 0.0)
                pulls = int(arow["pulls"] or 0)
                success_count = int(arow["success_count"] or 0)
                avg_latency = float(arow["avg_latency_ms"] or 0.0)
            else:
                old_q = 0.0
                pulls = 0
                success_count = 0
                avg_latency = 0.0
            new_pulls = pulls + 1
            new_success_count = success_count + (1 if outcome_success else 0)
            new_avg_latency = ((avg_latency * pulls) + latency_ms) / max(1, new_pulls)
            new_q = ((1.0 - self.alpha) * old_q) + (self.alpha * reward)
            conn.execute(
                """
                INSERT INTO action_policy(
                    user_id, task_type, action, q_value, pulls, success_count, avg_latency_ms, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, task_type, action) DO UPDATE SET
                    q_value = excluded.q_value,
                    pulls = excluded.pulls,
                    success_count = excluded.success_count,
                    avg_latency_ms = excluded.avg_latency_ms,
                    updated_at = excluded.updated_at
                """,
                (uid, task_type, action, new_q, new_pulls, new_success_count, new_avg_latency, _now()),
            )

            grow = conn.execute(
                """
                SELECT attempts, successes, avg_latency_ms, stability
                FROM agent_policy
                WHERE user_id = ? AND task_type = ? AND agent_id = ?
                """,
                (uid, task_type, agent_id),
            ).fetchone()
            if grow:
                attempts = int(grow["attempts"] or 0)
                successes = int(grow["successes"] or 0)
                g_latency = float(grow["avg_latency_ms"] or 0.0)
            else:
                attempts = 0
                successes = 0
                g_latency = 0.0
            new_attempts = attempts + 1
            new_successes = successes + (1 if outcome_success else 0)
            success_rate = new_successes / max(1, new_attempts)
            new_g_latency = ((g_latency * attempts) + latency_ms) / max(1, new_attempts)
            stability = max(
                0.05,
                min(
                    1.0,
                    (0.7 * success_rate) + (0.3 * (1.0 - min(1.0, (new_g_latency / 5000.0)))),
                ),
            )
            conn.execute(
                """
                INSERT INTO agent_policy(
                    user_id, task_type, agent_id, attempts, successes, avg_latency_ms, stability, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id, task_type, agent_id) DO UPDATE SET
                    attempts = excluded.attempts,
                    successes = excluded.successes,
                    avg_latency_ms = excluded.avg_latency_ms,
                    stability = excluded.stability,
                    updated_at = excluded.updated_at
                """,
                (uid, task_type, agent_id, new_attempts, new_successes, new_g_latency, stability, _now()),
            )
            conn.commit()
        return {
            "success": True,
            "user_id": uid,
            "task_type": task_type,
            "action": action,
            "agent_id": agent_id,
            "reward": reward,
            "q_value": new_q,
            "pulls": new_pulls,
        }

    def get_action_rankings_ucb(
        self,
        user_id: str,
        task_type: str,
        actions: list[str],
        *,
        explore_c: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        uid = self._normalize_user_id(user_id)
        ttype = str(task_type or "general").strip().lower() or "general"
        normalized_actions = [str(a or "").strip().lower() for a in actions if str(a or "").strip()]
        if not normalized_actions:
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT action, q_value, pulls, success_count, avg_latency_ms
                FROM action_policy
                WHERE user_id = ? AND task_type = ? AND action IN ({})
                """.format(",".join("?" * len(normalized_actions))),
                (uid, ttype, *normalized_actions),
            ).fetchall()
        row_map = {str(r["action"]): r for r in rows}
        c = self.explore_c if explore_c is None else max(0.01, float(explore_c))
        total_pulls = 0
        for action in normalized_actions:
            row = row_map.get(action)
            if row is not None:
                total_pulls += int(row["pulls"] or 0)
        total_pulls = max(1, total_pulls)
        rankings: list[dict[str, Any]] = []
        for action in normalized_actions:
            row = row_map.get(action)
            if row is None:
                score = 1.0 + c * math.sqrt(math.log(total_pulls + 1.0))
                rankings.append({"action": action, "score": score, "q_value": 0.0, "pulls": 0})
                continue
            pulls = max(1, int(row["pulls"] or 0))
            q_value = float(row["q_value"] or 0.0)
            bonus = c * math.sqrt(math.log(total_pulls + 1.0) / pulls)
            score = q_value + bonus
            rankings.append({"action": action, "score": score, "q_value": q_value, "pulls": pulls})
        rankings.sort(key=lambda item: (float(item.get("score", 0.0)), float(item.get("q_value", 0.0))), reverse=True)
        return rankings

    def select_action_ucb(
        self,
        user_id: str,
        task_type: str,
        actions: list[str],
        *,
        explore_c: Optional[float] = None,
    ) -> Optional[str]:
        rankings = self.get_action_rankings_ucb(user_id, task_type, actions, explore_c=explore_c)
        if not rankings:
            return None
        return str(rankings[0].get("action") or "")

    def get_agent_metrics(self, user_id: str, task_type: str, agent_id: str) -> dict[str, float]:
        uid = self._normalize_user_id(user_id)
        ttype = str(task_type or "general").strip().lower() or "general"
        aid = str(agent_id or "unknown").strip().lower() or "unknown"
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT attempts, successes, avg_latency_ms, stability
                FROM agent_policy
                WHERE user_id = ? AND task_type = ? AND agent_id = ?
                """,
                (uid, ttype, aid),
            ).fetchone()
        if not row:
            return {"success_rate": 0.7, "latency_score": 0.7, "stability": 0.8}
        attempts = max(1, int(row["attempts"] or 0))
        success_rate = float(row["successes"] or 0) / attempts
        avg_latency_ms = float(row["avg_latency_ms"] or 0.0)
        latency_score = max(0.05, min(1.0, 1.0 - min(1.0, avg_latency_ms / 5000.0)))
        stability = max(0.05, min(1.0, float(row["stability"] or 0.8)))
        return {
            "success_rate": success_rate,
            "latency_score": latency_score,
            "stability": stability,
        }

    def get_learning_score(self, user_id: str = "") -> float:
        uid = self._normalize_user_id(user_id) if str(user_id or "").strip() else ""
        with self._connect() as conn:
            if uid:
                row = conn.execute(
                    "SELECT AVG(q_value) AS q FROM action_policy WHERE user_id = ?",
                    (uid,),
                ).fetchone()
            else:
                row = conn.execute("SELECT AVG(q_value) AS q FROM action_policy").fetchone()
        q = float((row["q"] if row else 0.0) or 0.0)
        return round((q + 1.0) * 50.0, 2)

    def delete_user_data(self, user_id: str) -> dict[str, Any]:
        uid = self._normalize_user_id(user_id)
        with self._connect() as conn:
            deleted = {}
            for table in ("learning_signals", "action_policy", "agent_policy", "user_policy"):
                cursor = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (uid,))
                deleted[table] = int(cursor.rowcount or 0)
            conn.commit()
        return {"user_id": uid, "deleted": deleted}

    def get_status(self, user_id: str = "") -> dict[str, Any]:
        uid = self._normalize_user_id(user_id) if str(user_id or "").strip() else ""
        with self._connect() as conn:
            if uid:
                sig = conn.execute("SELECT COUNT(*) AS c FROM learning_signals WHERE user_id = ?", (uid,)).fetchone()
                act = conn.execute("SELECT COUNT(*) AS c FROM action_policy WHERE user_id = ?", (uid,)).fetchone()
                ag = conn.execute("SELECT COUNT(*) AS c FROM agent_policy WHERE user_id = ?", (uid,)).fetchone()
            else:
                sig = conn.execute("SELECT COUNT(*) AS c FROM learning_signals").fetchone()
                act = conn.execute("SELECT COUNT(*) AS c FROM action_policy").fetchone()
                ag = conn.execute("SELECT COUNT(*) AS c FROM agent_policy").fetchone()
        return {
            "db_path": str(self.db_path),
            "user_id": uid or None,
            "signals": int((sig["c"] if sig else 0) or 0),
            "actions": int((act["c"] if act else 0) or 0),
            "agents": int((ag["c"] if ag else 0) or 0),
            "learning_score": self.get_learning_score(uid),
            "user_policy": self.get_user_policy(uid or "local"),
        }


_policy_store: PolicyLearningStore | None = None


def get_policy_learning_store() -> PolicyLearningStore:
    global _policy_store
    if _policy_store is None:
        _policy_store = PolicyLearningStore()
    return _policy_store
