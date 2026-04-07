from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from config.elyan_config import elyan_config
from core.storage_paths import resolve_elyan_data_dir
from core.text_artifacts import existing_text_path, preferred_text_path
from utils.logger import get_logger

logger = get_logger("semantic_memory")


def _semantic_config() -> dict[str, Any]:
    return dict(elyan_config.get("operator.multi_agent.semantic_memory", {}) or {})


def _vector_backend_requested() -> str:
    raw = str(
        os.getenv("ELYAN_SEMANTIC_MEMORY_BACKEND", "")
        or os.getenv("ELYAN_VECTOR_BACKEND", "")
        or _semantic_config().get("backend")
        or elyan_config.get("personalization.vector_backend", "text")
        or "text"
    ).strip().lower()
    return raw or "text"


def _qdrant_root_path() -> Path:
    configured = str(_semantic_config().get("path") or "").strip()
    if configured:
        return Path(configured).expanduser()
    return resolve_elyan_data_dir() / "memory" / "qdrant"


def _qdrant_collection_name() -> str:
    return str(_semantic_config().get("collection") or "semantic_memory").strip() or "semantic_memory"


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


class SemanticMemory:
    def __init__(self):
        memory_dir = resolve_elyan_data_dir() / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        self.memory_path = preferred_text_path(memory_dir / "history.txt")
        self.patterns_path = preferred_text_path(memory_dir / "patterns.txt")
        self.sqlite_path = memory_dir / "semantic.sqlite3"
        self.backend_requested = _vector_backend_requested()
        self.backend_effective = "sqlite_text"
        self._qdrant_client: Any = None
        self._qdrant_models: Any = None
        self._collection_name = _qdrant_collection_name()
        self._qdrant_path = _qdrant_root_path()
        self._init_sqlite()
        self._init_vector_backend()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.sqlite_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    entry_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_semantic_user_time ON entries(user_id, timestamp DESC)")
            conn.commit()

    def _init_vector_backend(self) -> None:
        if self.backend_requested != "qdrant":
            self.backend_effective = "sqlite_text"
            return
        try:
            from qdrant_client import QdrantClient, models

            self._qdrant_path.mkdir(parents=True, exist_ok=True)
            client = QdrantClient(path=str(self._qdrant_path))
            if not client.collection_exists(self._collection_name):
                client.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=models.VectorParams(size=32, distance=models.Distance.COSINE),
                )
            self._qdrant_client = client
            self._qdrant_models = models
            self.backend_effective = "qdrant"
        except Exception as exc:
            logger.debug(f"Qdrant unavailable, sqlite_text fallback active: {exc}")
            self._qdrant_client = None
            self._qdrant_models = None
            self.backend_effective = "sqlite_text"

    def _append_audit_text(self, user_id: str, content: str, metadata: dict[str, Any]) -> None:
        timestamp = datetime.now().isoformat()
        try:
            self.patterns_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.patterns_path, "a", encoding="utf-8") as f:
                f.write(
                    f"\n### Entry: {timestamp}\n"
                    f"- User: {user_id}\n"
                    f"- Content: {content}\n"
                    f"- Metadata: {json.dumps(metadata, ensure_ascii=False)}\n"
                )
        except Exception as exc:
            logger.error(f"Failed to append semantic audit text: {exc}")

    async def add_entry(self, user_id: str, content: str, metadata: dict[str, Any] | None = None):
        timestamp = datetime.now().isoformat()
        entry_id = f"sem_{uuid.uuid4().hex[:12]}"
        payload = dict(metadata or {})
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO entries(entry_id, user_id, timestamp, content, metadata_json) VALUES (?, ?, ?, ?, ?)",
                (entry_id, str(user_id), timestamp, str(content), json.dumps(payload, ensure_ascii=False, sort_keys=True)),
            )
            conn.commit()
        self._append_audit_text(str(user_id), str(content), payload)

        if self._qdrant_client is not None and self._qdrant_models is not None:
            try:
                self._qdrant_client.upsert(
                    collection_name=self._collection_name,
                    points=[
                        self._qdrant_models.PointStruct(
                            id=entry_id,
                            vector=_embed_text(content),
                            payload={
                                "entry_id": entry_id,
                                "user_id": str(user_id),
                                "timestamp": timestamp,
                                "content": str(content),
                                "metadata": payload,
                            },
                        )
                    ],
                )
            except Exception as exc:
                logger.warning(f"Semantic qdrant upsert failed: {exc}")

    def _sqlite_search(self, user_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        tokens = [token for token in str(query or "").lower().split() if token.strip()]
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT entry_id, timestamp, content, metadata_json FROM entries WHERE user_id = ? ORDER BY timestamp DESC LIMIT 200",
                (str(user_id),),
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in rows:
            content = str(row["content"] or "")
            low_content = content.lower()
            if tokens and not any(token in low_content for token in tokens):
                continue
            score = sum(1 for token in tokens if token in low_content) if tokens else 1
            metadata = {}
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except Exception:
                metadata = {}
            results.append(
                {
                    "entry_id": str(row["entry_id"] or ""),
                    "timestamp": str(row["timestamp"] or ""),
                    "content": content,
                    "metadata": metadata,
                    "score": float(score),
                }
            )
            if len(results) >= limit:
                break
        return results[:limit]

    def _qdrant_search(self, user_id: str, query: str, limit: int) -> list[dict[str, Any]]:
        if self._qdrant_client is None or self._qdrant_models is None:
            return []
        try:
            results = self._qdrant_client.search(
                collection_name=self._collection_name,
                query_vector=_embed_text(query),
                limit=max(1, int(limit or 5)),
                query_filter=self._qdrant_models.Filter(
                    must=[
                        self._qdrant_models.FieldCondition(
                            key="user_id",
                            match=self._qdrant_models.MatchValue(value=str(user_id)),
                        )
                    ]
                ),
            )
        except Exception as exc:
            logger.warning(f"Semantic qdrant search failed: {exc}")
            return []

        rows: list[dict[str, Any]] = []
        for row in results:
            payload = dict(getattr(row, "payload", None) or {})
            rows.append(
                {
                    "entry_id": str(payload.get("entry_id") or getattr(row, "id", "")),
                    "timestamp": str(payload.get("timestamp") or ""),
                    "content": str(payload.get("content") or ""),
                    "metadata": dict(payload.get("metadata") or {}),
                    "score": float(getattr(row, "score", 0.0) or 0.0),
                }
            )
        return rows

    async def search(self, user_id: str, query: str, limit: int = 5) -> list[dict[str, Any]]:
        if self.backend_effective == "qdrant":
            results = self._qdrant_search(user_id, query, limit)
            if results:
                return results
        return self._sqlite_search(user_id, query, limit)

    async def record_success(self, task: str, plan_json: str):
        await self.add_entry("system", f"Success Task: {task}\nPlan: {plan_json}")

    async def get_relevant_examples(self, user_input: str) -> str:
        entries = await self.search("system", user_input, limit=2)
        if not entries:
            return ""
        return "\nGeçmiş Örnekler:\n" + "\n".join([str(e.get("content") or "") for e in entries])

    async def clear_user(self, user_id: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM entries WHERE user_id = ?", (str(user_id),))
            conn.commit()
        if self._qdrant_client is not None and self._qdrant_models is not None:
            try:
                self._qdrant_client.delete(
                    collection_name=self._collection_name,
                    points_selector=self._qdrant_models.FilterSelector(
                        filter=self._qdrant_models.Filter(
                            must=[
                                self._qdrant_models.FieldCondition(
                                    key="user_id",
                                    match=self._qdrant_models.MatchValue(value=str(user_id)),
                                )
                            ]
                        )
                    ),
                )
            except Exception as exc:
                logger.warning(f"Semantic qdrant delete failed: {exc}")

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0] or 0)
            users = int(conn.execute("SELECT COUNT(DISTINCT user_id) FROM entries").fetchone()[0] or 0)
        return {
            "backend_requested": self.backend_requested,
            "backend_effective": self.backend_effective,
            "entries": total,
            "users": users,
            "sqlite_path": str(self.sqlite_path),
            "audit_path": str(self.patterns_path),
            "collection": self._collection_name,
            "qdrant_path": str(self._qdrant_path),
        }


_semantic_memory: SemanticMemory | None = None


def get_semantic_memory():
    global _semantic_memory
    if _semantic_memory is None:
        _semantic_memory = SemanticMemory()
    return _semantic_memory


semantic_memory = get_semantic_memory()
