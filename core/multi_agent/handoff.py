from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from config.elyan_config import elyan_config
from core.security.contracts import DataClassification, classify_value, contains_sensitive_data
from core.storage_paths import resolve_elyan_data_dir


@dataclass(slots=True)
class AgentHandoffPacket:
    handoff_id: str = field(default_factory=lambda: f"handoff_{uuid.uuid4().hex[:10]}")
    from_agent: str = ""
    to_agent: str = ""
    objective: str = ""
    summary: str = ""
    constraints: list[str] = field(default_factory=list)
    artifacts: list[str] = field(default_factory=list)
    memory_refs: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    classification: str = DataClassification.INTERNAL.value
    provenance: dict[str, Any] = field(default_factory=dict)
    cloud_allowed: bool = False
    requires_redaction: bool = False
    integrity_hash: str = ""
    created_at: float = field(default_factory=time.time)

    def compute_integrity_hash(self) -> str:
        payload = {
            "handoff_id": self.handoff_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "objective": self.objective,
            "summary": self.summary,
            "constraints": list(self.constraints),
            "artifacts": list(self.artifacts),
            "memory_refs": list(self.memory_refs),
            "metadata": dict(self.metadata),
            "classification": self.classification,
            "provenance": dict(self.provenance),
            "cloud_allowed": bool(self.cloud_allowed),
            "requires_redaction": bool(self.requires_redaction),
            "created_at": float(self.created_at),
        }
        return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["integrity_hash"] = self.integrity_hash or self.compute_integrity_hash()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "AgentHandoffPacket":
        data = dict(payload or {})
        packet = cls(
            handoff_id=str(data.get("handoff_id") or data.get("id") or f"handoff_{uuid.uuid4().hex[:10]}"),
            from_agent=str(data.get("from_agent") or ""),
            to_agent=str(data.get("to_agent") or ""),
            objective=str(data.get("objective") or ""),
            summary=str(data.get("summary") or ""),
            constraints=[str(item) for item in list(data.get("constraints") or []) if str(item).strip()],
            artifacts=[str(item) for item in list(data.get("artifacts") or []) if str(item).strip()],
            memory_refs=[str(item) for item in list(data.get("memory_refs") or []) if str(item).strip()],
            metadata=dict(data.get("metadata") or {}),
            classification=str(data.get("classification") or classify_value(data.get("metadata") or {}, key="metadata").value),
            provenance=dict(data.get("provenance") or {}),
            cloud_allowed=bool(data.get("cloud_allowed", False)),
            requires_redaction=bool(data.get("requires_redaction", contains_sensitive_data(data.get("metadata") or {}))),
            integrity_hash=str(data.get("integrity_hash") or ""),
            created_at=float(data.get("created_at") or time.time()),
        )
        packet.integrity_hash = packet.integrity_hash or packet.compute_integrity_hash()
        return packet


def build_handoff_context(packet: AgentHandoffPacket | dict[str, Any] | None) -> dict[str, Any]:
    resolved = packet if isinstance(packet, AgentHandoffPacket) else AgentHandoffPacket.from_dict(packet if isinstance(packet, dict) else {})
    return {
        "handoff": resolved.to_dict(),
        "objective": resolved.objective,
        "artifacts": list(resolved.artifacts),
        "constraints": list(resolved.constraints),
        "memory_refs": list(resolved.memory_refs),
        "classification": resolved.classification,
        "cloud_allowed": resolved.cloud_allowed,
        "requires_redaction": resolved.requires_redaction,
        "provenance": dict(resolved.provenance),
    }


def _handoff_store_path() -> str:
    configured = str(
        elyan_config.get("operator.multi_agent.handoff_store.path", "")
        or ""
    ).strip()
    if configured:
        return str(Path(configured).expanduser())
    return str(resolve_elyan_data_dir() / "multi_agent" / "handoffs.sqlite3")


class HandoffStore:
    def __init__(self, db_path: str | None = None) -> None:
        root = Path(db_path or _handoff_store_path()).expanduser().parent
        root.mkdir(parents=True, exist_ok=True)
        self.db_path = str(Path(db_path or _handoff_store_path()).expanduser())
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS handoffs (
                    handoff_id TEXT PRIMARY KEY,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    objective TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at REAL NOT NULL,
                    delivered_at REAL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_handoffs_target_status ON handoffs(to_agent, status, created_at DESC)"
            )
            conn.commit()

    def record(self, packet: AgentHandoffPacket) -> str:
        packet.integrity_hash = packet.integrity_hash or packet.compute_integrity_hash()
        payload = json.dumps(packet.to_dict(), ensure_ascii=False, sort_keys=True)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO handoffs(handoff_id, from_agent, to_agent, objective, summary, payload_json, status, created_at, delivered_at)
                VALUES(?, ?, ?, ?, ?, ?, 'pending', ?, NULL)
                ON CONFLICT(handoff_id) DO UPDATE SET
                    from_agent = excluded.from_agent,
                    to_agent = excluded.to_agent,
                    objective = excluded.objective,
                    summary = excluded.summary,
                    payload_json = excluded.payload_json
                """,
                (
                    packet.handoff_id,
                    packet.from_agent,
                    packet.to_agent,
                    packet.objective,
                    packet.summary,
                    payload,
                    float(packet.created_at or time.time()),
                ),
            )
            conn.commit()
        return packet.handoff_id

    def mark_delivered(self, handoff_id: str) -> bool:
        with self._connect() as conn:
            cur = conn.execute(
                "UPDATE handoffs SET status = 'delivered', delivered_at = ? WHERE handoff_id = ?",
                (time.time(), str(handoff_id or "")),
            )
            conn.commit()
            return bool(cur.rowcount)

    def list_pending(self, to_agent: str, limit: int = 50) -> list[AgentHandoffPacket]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM handoffs
                WHERE to_agent = ? AND status = 'pending'
                ORDER BY created_at ASC
                LIMIT ?
                """,
                (str(to_agent or ""), max(1, int(limit or 50))),
            ).fetchall()
        packets: list[AgentHandoffPacket] = []
        for row in rows:
            try:
                packets.append(AgentHandoffPacket.from_dict(json.loads(str(row["payload_json"] or "{}"))))
            except Exception:
                continue
        return packets

    def stats(self) -> dict[str, Any]:
        with self._connect() as conn:
            total = int(conn.execute("SELECT COUNT(*) FROM handoffs").fetchone()[0] or 0)
            pending = int(conn.execute("SELECT COUNT(*) FROM handoffs WHERE status = 'pending'").fetchone()[0] or 0)
            delivered = int(conn.execute("SELECT COUNT(*) FROM handoffs WHERE status = 'delivered'").fetchone()[0] or 0)
        return {
            "backend": str(elyan_config.get("operator.multi_agent.handoff_store.backend", "sqlite") or "sqlite"),
            "db_path": self.db_path,
            "total": total,
            "pending": pending,
            "delivered": delivered,
        }


_handoff_store: HandoffStore | None = None


def get_handoff_store() -> HandoffStore:
    global _handoff_store
    if _handoff_store is None:
        _handoff_store = HandoffStore()
    return _handoff_store


__all__ = ["AgentHandoffPacket", "HandoffStore", "build_handoff_context", "get_handoff_store"]
