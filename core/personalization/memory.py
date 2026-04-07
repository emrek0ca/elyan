from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from core.i18n import detect_language
from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("personalization.memory")

_STOP_WORDS = {
    "ve",
    "ile",
    "ama",
    "bir",
    "bu",
    "şu",
    "the",
    "and",
    "for",
    "that",
    "with",
    "you",
    "your",
    "ben",
    "sen",
    "biraz",
    "çok",
    "daha",
}


def _now() -> float:
    return time.time()


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _keyword_candidates(*segments: str) -> list[str]:
    words: dict[str, int] = {}
    for segment in segments:
        for raw in str(segment or "").lower().replace("\n", " ").split():
            token = "".join(ch for ch in raw if ch.isalnum() or ch in {"_", "-"})
            if len(token) < 4 or token in _STOP_WORDS:
                continue
            words[token] = words.get(token, 0) + 1
    ranked = sorted(words.items(), key=lambda item: (-item[1], item[0]))
    return [token for token, _count in ranked[:8]]


class PersonalMemoryStore:
    def __init__(
        self,
        storage_root: Path | None = None,
        *,
        vector_backend: str = "lancedb",
        graph_backend: str = "sqlite",
    ):
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "personalization" / "memory")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_root / "personal_memory.sqlite3"
        self.vector_backend_requested = str(vector_backend or "lancedb")
        self.vector_backend_effective = "sqlite_fallback"
        self.graph_backend = str(graph_backend or "sqlite")
        self._lancedb = None
        self._lancedb_table = None
        self._init_db()
        self._init_vector_backend()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    user_input TEXT NOT NULL,
                    assistant_output TEXT NOT NULL,
                    intent TEXT,
                    action_name TEXT,
                    success INTEGER NOT NULL,
                    embedding_json TEXT NOT NULL,
                    reward_evidence_json TEXT NOT NULL,
                    privacy_flags_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_personal_interactions_user_time
                    ON interactions(user_id, created_at DESC);

                CREATE TABLE IF NOT EXISTS profile_entries (
                    user_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, key)
                );

                CREATE TABLE IF NOT EXISTS graph_edges (
                    user_id TEXT NOT NULL,
                    src TEXT NOT NULL,
                    relation TEXT NOT NULL,
                    dst TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY(user_id, src, relation, dst)
                );
                """
            )
            conn.commit()

    def _init_vector_backend(self) -> None:
        if sys.platform == "darwin" or self.vector_backend_requested.strip().lower() != "lancedb":
            self.vector_backend_effective = "sqlite_fallback"
            return
        try:
            import lancedb  # type: ignore

            lance_root = self.storage_root / "lancedb"
            lance_root.mkdir(parents=True, exist_ok=True)
            self._lancedb = lancedb.connect(str(lance_root))
            try:
                self._lancedb_table = self._lancedb.open_table("interaction_vectors")
            except Exception:
                self._lancedb_table = None
            self.vector_backend_effective = "lancedb" if self._lancedb is not None else "sqlite_fallback"
        except Exception as exc:
            logger.debug(f"LanceDB unavailable, sqlite fallback active: {exc}")
            self._lancedb = None
            self._lancedb_table = None
            self.vector_backend_effective = "sqlite_fallback"

    @staticmethod
    def _embed_text(text: str, dims: int = 32) -> list[float]:
        payload = str(text or "").encode("utf-8", errors="ignore")
        digest = hashlib.sha256(payload).digest()
        vector: list[float] = []
        while len(vector) < dims:
            digest = hashlib.sha256(digest).digest()
            for idx in range(0, len(digest), 4):
                chunk = digest[idx:idx + 4]
                if len(chunk) < 4:
                    break
                raw = int.from_bytes(chunk, byteorder="big", signed=False)
                value = (raw / 0xFFFFFFFF) * 2.0 - 1.0
                vector.append(value)
                if len(vector) >= dims:
                    break
        norm = math.sqrt(sum(item * item for item in vector)) or 1.0
        return [round(item / norm, 8) for item in vector]

    @staticmethod
    def _compact_text(text: str, *, token_budget: int) -> str:
        approx_chars = max(300, int(token_budget or 0) * 4)
        raw = str(text or "").strip()
        if len(raw) <= approx_chars:
            return raw
        return raw[: max(0, approx_chars - 1)].rstrip() + "…"

    def _load_profile(self, user_id: str) -> dict[str, Any]:
        profile: dict[str, Any] = {}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT key, value_json FROM profile_entries WHERE user_id = ?",
                (str(user_id or "local"),),
            ).fetchall()
        for row in rows:
            try:
                profile[str(row["key"])] = json.loads(str(row["value_json"]))
            except Exception:
                profile[str(row["key"])] = row["value_json"]
        return profile

    def _store_profile_entry(self, user_id: str, key: str, value: Any, *, weight: float = 1.0) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO profile_entries(user_id, key, value_json, weight, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(user_id, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    weight = excluded.weight,
                    updated_at = excluded.updated_at
                """,
                (str(user_id or "local"), key, _safe_json(value), float(weight or 1.0), _now()),
            )
            conn.commit()

    def _store_graph_edges(self, user_id: str, edges: list[dict[str, Any]]) -> None:
        if not edges:
            return
        with self._connect() as conn:
            for edge in edges:
                conn.execute(
                    """
                    INSERT INTO graph_edges(user_id, src, relation, dst, weight, updated_at)
                    VALUES(?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, src, relation, dst) DO UPDATE SET
                        weight = excluded.weight,
                        updated_at = excluded.updated_at
                    """,
                    (
                        str(user_id or "local"),
                        str(edge.get("src") or "user"),
                        str(edge.get("relation") or "related_to"),
                        str(edge.get("dst") or ""),
                        float(edge.get("weight", 1.0) or 1.0),
                        _now(),
                    ),
                )
            conn.commit()

    def _extract_profile_updates(
        self,
        *,
        user_input: str,
        assistant_output: str,
        intent: str,
        action: str,
        success: bool,
        metadata: dict[str, Any],
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        profile = self._load_profile(str(metadata.get("user_id") or "local"))
        lang = str(metadata.get("detected_language") or detect_language(user_input) or "auto").strip().lower()
        response_length_bias = str(profile.get("response_length_bias") or "medium")
        low_input = str(user_input or "").lower()
        if any(marker in low_input for marker in {"kısa", "kisa", "özet", "ozet", "madde madde"}):
            response_length_bias = "short"
        elif any(marker in low_input for marker in {"detaylı", "detayli", "ayrıntılı", "ayrintili", "uzun"}):
            response_length_bias = "detailed"
        elif response_length_bias not in {"short", "medium", "detailed"}:
            response_length_bias = "medium"

        topic_counts = dict(profile.get("topic_counts") or {})
        action_counts = dict(profile.get("action_counts") or {})
        success_counts = dict(profile.get("successful_actions") or {})
        failure_counts = dict(profile.get("failed_actions") or {})
        for keyword in _keyword_candidates(user_input, assistant_output):
            topic_counts[keyword] = int(topic_counts.get(keyword, 0)) + 1
        if action:
            action_counts[action] = int(action_counts.get(action, 0)) + 1
            if success:
                success_counts[action] = int(success_counts.get(action, 0)) + 1
            else:
                failure_counts[action] = int(failure_counts.get(action, 0)) + 1

        top_topics = [item[0] for item in sorted(topic_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:6]]
        top_actions = [item[0] for item in sorted(success_counts.items(), key=lambda pair: (-pair[1], pair[0]))[:6]]
        profile_updates = {
            "preferred_language": lang,
            "response_length_bias": response_length_bias,
            "topic_counts": topic_counts,
            "action_counts": action_counts,
            "successful_actions": success_counts,
            "failed_actions": failure_counts,
            "top_topics": top_topics,
            "top_actions": top_actions,
            "last_intent": str(intent or ""),
            "last_action": str(action or ""),
            "last_success": bool(success),
            "updated_at": _now(),
        }
        edges: list[dict[str, Any]] = []
        if lang and lang != "auto":
            edges.append({"src": "user", "relation": "prefers_language", "dst": lang, "weight": 1.0})
        if response_length_bias:
            edges.append({"src": "user", "relation": "prefers_response_length", "dst": response_length_bias, "weight": 0.9})
        for keyword in top_topics[:4]:
            edges.append({"src": "user", "relation": "interested_in", "dst": keyword, "weight": float(topic_counts.get(keyword, 1))})
        if intent:
            edges.append({"src": "user", "relation": "recent_intent", "dst": str(intent), "weight": 0.7})
        if action:
            edges.append({"src": "user", "relation": "recent_action", "dst": str(action), "weight": 0.7})
        return profile_updates, edges

    def write_interaction(
        self,
        *,
        user_id: str,
        user_input: str,
        assistant_output: str,
        intent: str = "",
        action: str = "",
        success: bool = True,
        reward_evidence: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        privacy_flags: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        interaction_id = str(uuid.uuid4())
        meta = dict(metadata or {})
        meta["user_id"] = uid
        embedding = self._embed_text(f"{user_input}\n{assistant_output}")
        profile_updates, graph_edges = self._extract_profile_updates(
            user_input=user_input,
            assistant_output=assistant_output,
            intent=intent,
            action=action,
            success=success,
            metadata=meta,
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO interactions(
                    interaction_id, user_id, user_input, assistant_output, intent, action_name,
                    success, embedding_json, reward_evidence_json, privacy_flags_json, metadata_json, created_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    interaction_id,
                    uid,
                    str(user_input or ""),
                    str(assistant_output or ""),
                    str(intent or ""),
                    str(action or ""),
                    1 if success else 0,
                    _safe_json(embedding),
                    _safe_json(dict(reward_evidence or {})),
                    _safe_json(dict(privacy_flags or {})),
                    _safe_json(meta),
                    _now(),
                ),
            )
            conn.commit()
        for key, value in profile_updates.items():
            self._store_profile_entry(uid, key, value)
        self._store_graph_edges(uid, graph_edges)
        if self._lancedb_table is not None:
            try:
                self._lancedb_table.add(
                    [
                        {
                            "interaction_id": interaction_id,
                            "user_id": uid,
                            "vector": embedding,
                            "created_at": _now(),
                        }
                    ]
                )
            except Exception as exc:
                logger.debug(f"LanceDB add skipped: {exc}")
        return {
            "interaction_id": interaction_id,
            "embedding_backend": self.vector_backend_effective,
            "profile_updates": profile_updates,
            "graph_edges": graph_edges,
        }

    def interaction_count(self, user_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM interactions WHERE user_id = ?",
                (str(user_id or "local"),),
            ).fetchone()
        return int((row["cnt"] if row else 0) or 0)

    def recent_interactions(self, user_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT interaction_id, user_input, assistant_output, intent, action_name, success, metadata_json, created_at
                FROM interactions
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
                    "interaction_id": str(row["interaction_id"]),
                    "user_input": str(row["user_input"] or ""),
                    "assistant_output": str(row["assistant_output"] or ""),
                    "intent": str(row["intent"] or ""),
                    "action": str(row["action_name"] or ""),
                    "success": bool(int(row["success"] or 0)),
                    "metadata": metadata,
                    "created_at": float(row["created_at"] or 0.0),
                }
            )
        return out

    def retrieve_context(
        self,
        user_id: str,
        query: str,
        *,
        k: int = 5,
        token_budget: int = 512,
    ) -> dict[str, Any]:
        uid = str(user_id or "local")
        query_embedding = self._embed_text(query)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT interaction_id, user_input, assistant_output, intent, action_name, success,
                       embedding_json, metadata_json, created_at
                FROM interactions
                WHERE user_id = ?
                ORDER BY created_at DESC
                LIMIT 200
                """,
                (uid,),
            ).fetchall()
            edge_rows = conn.execute(
                """
                SELECT src, relation, dst, weight
                FROM graph_edges
                WHERE user_id = ?
                ORDER BY weight DESC, updated_at DESC
                LIMIT 20
                """,
                (uid,),
            ).fetchall()
        hits: list[dict[str, Any]] = []
        for row in rows:
            try:
                embedding = json.loads(str(row["embedding_json"] or "[]"))
            except Exception:
                embedding = []
            score = _cosine_similarity(query_embedding, embedding if isinstance(embedding, list) else [])
            hits.append(
                {
                    "interaction_id": str(row["interaction_id"]),
                    "score": round(score, 6),
                    "user_input": str(row["user_input"] or ""),
                    "assistant_output": str(row["assistant_output"] or ""),
                    "intent": str(row["intent"] or ""),
                    "action": str(row["action_name"] or ""),
                    "success": bool(int(row["success"] or 0)),
                    "created_at": float(row["created_at"] or 0.0),
                }
            )
        hits.sort(key=lambda item: (-item["score"], -item["created_at"]))
        top_hits = hits[: max(1, int(k or 5))]
        profile = self._load_profile(uid)
        graph_edges = [
            {
                "src": str(row["src"] or ""),
                "relation": str(row["relation"] or ""),
                "dst": str(row["dst"] or ""),
                "weight": float(row["weight"] or 0.0),
            }
            for row in edge_rows
        ]

        profile_lines: list[str] = []
        preferred_language = str(profile.get("preferred_language") or "").strip()
        if preferred_language:
            profile_lines.append(f"- Preferred language: {preferred_language}")
        response_length_bias = str(profile.get("response_length_bias") or "").strip()
        if response_length_bias:
            profile_lines.append(f"- Response length bias: {response_length_bias}")
        top_topics = list(profile.get("top_topics") or [])
        if top_topics:
            profile_lines.append(f"- Top topics: {', '.join(top_topics[:6])}")
        top_actions = list(profile.get("top_actions") or [])
        if top_actions:
            profile_lines.append(f"- Successful actions: {', '.join(top_actions[:6])}")

        memory_lines: list[str] = []
        for index, hit in enumerate(top_hits, start=1):
            memory_lines.append(
                f"{index}. User: {hit['user_input']}\nAssistant: {hit['assistant_output']}\n"
                f"Action: {hit['action'] or hit['intent'] or 'unknown'} | Score: {hit['score']:.2f}"
            )
        edge_lines = [
            f"- {edge['relation']}: {edge['dst']}"
            for edge in graph_edges[:8]
            if edge.get("relation") and edge.get("dst")
        ]
        blocks: list[str] = []
        if profile_lines:
            blocks.append("[Personal Profile]\n" + "\n".join(profile_lines))
        if edge_lines:
            blocks.append("[Preference Graph]\n" + "\n".join(edge_lines))
        if memory_lines:
            blocks.append("[Relevant History]\n" + "\n\n".join(memory_lines))
        text = self._compact_text("\n\n".join(blocks), token_budget=token_budget)
        return {
            "text": text,
            "profile": profile,
            "vector_hits": top_hits,
            "graph_edges": graph_edges,
            "backend": {
                "vector_requested": self.vector_backend_requested,
                "vector_effective": self.vector_backend_effective,
                "graph": self.graph_backend,
            },
            "interaction_count": self.interaction_count(uid),
        }

    def get_stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            interactions = conn.execute("SELECT COUNT(*) AS cnt FROM interactions").fetchone()
            profiles = conn.execute("SELECT COUNT(*) AS cnt FROM profile_entries").fetchone()
            edges = conn.execute("SELECT COUNT(*) AS cnt FROM graph_edges").fetchone()
        return {
            "db_path": str(self.db_path),
            "interactions": int((interactions["cnt"] if interactions else 0) or 0),
            "profile_entries": int((profiles["cnt"] if profiles else 0) or 0),
            "graph_edges": int((edges["cnt"] if edges else 0) or 0),
            "vector_backend_requested": self.vector_backend_requested,
            "vector_backend_effective": self.vector_backend_effective,
            "graph_backend": self.graph_backend,
        }

    def delete_user(self, user_id: str) -> dict[str, Any]:
        uid = str(user_id or "local")
        with self._connect() as conn:
            interaction_row = conn.execute("SELECT COUNT(*) AS cnt FROM interactions WHERE user_id = ?", (uid,)).fetchone()
            profile_row = conn.execute("SELECT COUNT(*) AS cnt FROM profile_entries WHERE user_id = ?", (uid,)).fetchone()
            edge_row = conn.execute("SELECT COUNT(*) AS cnt FROM graph_edges WHERE user_id = ?", (uid,)).fetchone()
            conn.execute("DELETE FROM interactions WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM profile_entries WHERE user_id = ?", (uid,))
            conn.execute("DELETE FROM graph_edges WHERE user_id = ?", (uid,))
            conn.commit()
        if self._lancedb_table is not None:
            try:
                safe_uid = uid.replace("'", "''")
                self._lancedb_table.delete(f"user_id = '{safe_uid}'")
            except Exception as exc:
                logger.debug(f"LanceDB delete skipped: {exc}")
        return {
            "user_id": uid,
            "deleted_interactions": int((interaction_row["cnt"] if interaction_row else 0) or 0),
            "deleted_profile_entries": int((profile_row["cnt"] if profile_row else 0) or 0),
            "deleted_graph_edges": int((edge_row["cnt"] if edge_row else 0) or 0),
        }
