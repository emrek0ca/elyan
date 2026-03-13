from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List

from core.knowledge_base import get_knowledge_base
from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("world_model")


def _default_world_model_db_path() -> Path:
    return resolve_elyan_data_dir() / "memory" / "world_model.db"


class WorldModel:
    """
    Lightweight world model for Elyan.

    This is not a full AGI simulator. It gives the runtime a deterministic
    bridge between memory, task context, and prior experiences so planning can
    reason over a stable snapshot instead of raw chat text alone.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or _default_world_model_db_path())
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _initialize(self) -> None:
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS facts (
                namespace TEXT NOT NULL,
                entity TEXT NOT NULL,
                attribute TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL NOT NULL DEFAULT 0.5,
                source TEXT,
                updated_at REAL NOT NULL,
                PRIMARY KEY (namespace, entity, attribute)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experiences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                goal TEXT NOT NULL,
                action TEXT,
                job_type TEXT,
                plan_json TEXT,
                tool_calls_json TEXT,
                errors_json TEXT,
                final_response TEXT,
                verified INTEGER NOT NULL DEFAULT 0,
                success_score REAL NOT NULL DEFAULT 0.0,
                metadata_json TEXT,
                created_at REAL NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_experiences_goal_time ON experiences(goal, created_at DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_experiences_action_time ON experiences(action, created_at DESC)"
        )
        conn.commit()
        conn.close()

    @staticmethod
    def _json_dump(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            return json.dumps(str(value), ensure_ascii=False)

    @staticmethod
    def _json_load(value: Any, default: Any) -> Any:
        raw = str(value or "").strip()
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return [tok for tok in re.findall(r"[a-zA-Z0-9_]+", str(text or "").lower()) if len(tok) >= 2]

    def upsert_fact(
        self,
        namespace: str,
        entity: str,
        attribute: str,
        value: str,
        *,
        confidence: float = 0.5,
        source: str = "",
    ) -> None:
        ns = str(namespace or "").strip() or "general"
        ent = str(entity or "").strip()
        attr = str(attribute or "").strip()
        val = str(value or "").strip()
        if not ent or not attr or not val:
            return
        ts = float(time.time())
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO facts(namespace, entity, attribute, value, confidence, source, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(namespace, entity, attribute)
            DO UPDATE SET
                value=excluded.value,
                confidence=excluded.confidence,
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (ns, ent, attr, val, max(0.0, min(1.0, float(confidence or 0.5))), str(source or ""), ts),
        )
        conn.commit()
        conn.close()

    def search_facts(self, query: str, *, limit: int = 5) -> List[Dict[str, Any]]:
        tokens = self._tokenize(query)
        if not tokens:
            return []
        conn = self._connect()
        cur = conn.cursor()
        rows: List[sqlite3.Row] = []
        for tok in tokens[:5]:
            rows.extend(
                cur.execute(
                    """
                    SELECT namespace, entity, attribute, value, confidence, source, updated_at
                    FROM facts
                    WHERE lower(entity) LIKE ? OR lower(attribute) LIKE ? OR lower(value) LIKE ?
                    ORDER BY confidence DESC, updated_at DESC
                    LIMIT ?
                    """,
                    (f"%{tok}%", f"%{tok}%", f"%{tok}%", max(1, int(limit))),
                ).fetchall()
            )
        conn.close()
        seen: set[tuple[str, str, str]] = set()
        out: List[Dict[str, Any]] = []
        for row in rows:
            key = (str(row["namespace"]), str(row["entity"]), str(row["attribute"]))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "namespace": str(row["namespace"]),
                    "entity": str(row["entity"]),
                    "attribute": str(row["attribute"]),
                    "value": str(row["value"]),
                    "confidence": float(row["confidence"] or 0.0),
                    "source": str(row["source"] or ""),
                    "updated_at": float(row["updated_at"] or 0.0),
                }
            )
            if len(out) >= max(1, int(limit)):
                break
        return out

    def record_experience(
        self,
        *,
        user_id: str,
        goal: str,
        action: str = "",
        job_type: str = "",
        plan: Any = None,
        tool_calls: Any = None,
        errors: Any = None,
        final_response: str = "",
        verified: bool = False,
        success_score: float = 0.0,
        metadata: Dict[str, Any] | None = None,
    ) -> None:
        clean_goal = str(goal or "").strip()
        if not clean_goal:
            return
        conn = self._connect()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO experiences(
                user_id, goal, action, job_type, plan_json, tool_calls_json,
                errors_json, final_response, verified, success_score, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(user_id or ""),
                clean_goal,
                str(action or ""),
                str(job_type or ""),
                self._json_dump(plan if plan is not None else []),
                self._json_dump(tool_calls if tool_calls is not None else []),
                self._json_dump(errors if errors is not None else []),
                str(final_response or "")[:4000],
                1 if verified else 0,
                max(0.0, min(1.0, float(success_score or 0.0))),
                self._json_dump(metadata if isinstance(metadata, dict) else {}),
                float(time.time()),
            ),
        )
        conn.commit()
        conn.close()

    def find_similar_experiences(
        self,
        query: str,
        *,
        action: str = "",
        job_type: str = "",
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        tokens = set(self._tokenize(query))
        conn = self._connect()
        cur = conn.cursor()
        rows = cur.execute(
            """
            SELECT id, user_id, goal, action, job_type, plan_json, tool_calls_json,
                   errors_json, final_response, verified, success_score, metadata_json, created_at
            FROM experiences
            ORDER BY created_at DESC
            LIMIT 120
            """
        ).fetchall()
        conn.close()

        scored: List[tuple[float, Dict[str, Any]]] = []
        for row in rows:
            goal = str(row["goal"] or "")
            goal_tokens = set(self._tokenize(goal))
            overlap = len(tokens & goal_tokens)
            score = float(overlap)
            if action and str(row["action"] or "") == str(action or ""):
                score += 2.0
            if job_type and str(row["job_type"] or "") == str(job_type or ""):
                score += 1.5
            score += float(row["success_score"] or 0.0)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    {
                        "id": int(row["id"]),
                        "user_id": str(row["user_id"] or ""),
                        "goal": goal,
                        "action": str(row["action"] or ""),
                        "job_type": str(row["job_type"] or ""),
                        "verified": bool(row["verified"]),
                        "success_score": float(row["success_score"] or 0.0),
                        "plan": self._json_load(row["plan_json"], []),
                        "tool_calls": self._json_load(row["tool_calls_json"], []),
                        "errors": self._json_load(row["errors_json"], []),
                        "final_response": str(row["final_response"] or ""),
                        "metadata": self._json_load(row["metadata_json"], {}),
                        "created_at": float(row["created_at"] or 0.0),
                    },
                )
            )
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: max(1, int(limit))]]

    @staticmethod
    def _infer_domains(query: str, *, action: str = "", job_type: str = "", goal_graph: Dict[str, Any] | None = None) -> List[str]:
        domains: List[str] = []
        if isinstance(goal_graph, dict):
            for item in goal_graph.get("workflow_chain", []) or []:
                text = str(item or "").strip().lower()
                if text and text not in domains:
                    domains.append(text)
        mapped = {
            "system_automation": "system",
            "file_operations": "filesystem",
            "api_integration": "api",
            "code_project": "coding",
            "data_analysis": "research",
        }
        mapped_domain = mapped.get(str(job_type or "").strip().lower())
        if mapped_domain and mapped_domain not in domains:
            domains.append(mapped_domain)
        low = str(query or "").lower()
        heuristics = {
            "system": ("terminal", "shell", "komut", "safari", "chrome", "uygulama", "ekran"),
            "filesystem": ("dosya", "klasor", "klasör", "masaustu", "masaüstü", "desktop"),
            "research": ("arastir", "araştır", "kaynak", "rapor", "incele"),
            "coding": ("kod", "python", "script", "repo", "refactor", "debug"),
            "api": ("api", "endpoint", "http", "json", "request"),
        }
        for domain, markers in heuristics.items():
            if any(marker in low for marker in markers) and domain not in domains:
                domains.append(domain)
        act = str(action or "").strip().lower()
        if act in {"run_safe_command", "open_app", "type_text", "key_combo"} and "system" not in domains:
            domains.append("system")
        return domains or ["general"]

    @staticmethod
    def _memory_hints(memory_results: Dict[str, Any], key: str, *, limit: int = 2) -> List[str]:
        rows = memory_results.get(key, []) if isinstance(memory_results, dict) else []
        hints: List[str] = []
        for row in rows[: max(1, int(limit))]:
            if isinstance(row, dict):
                content = str(row.get("content") or row.get("text") or row.get("message") or "").strip()
                if content:
                    hints.append(content[:240])
            elif isinstance(row, str) and row.strip():
                hints.append(row.strip()[:240])
        return hints

    @staticmethod
    def _kb_hints(query: str, *, action: str = "", limit: int = 2) -> List[str]:
        kb = get_knowledge_base()
        hints: List[str] = []
        tokens = set(WorldModel._tokenize(query))
        for rec in kb.list_experiences():
            if not isinstance(rec, dict):
                continue
            task_type = str(rec.get("task_type") or "")
            problem = str(rec.get("problem") or "")
            if action and task_type == action:
                hints.append(f"Known fix for {task_type}: {problem[:140]}")
            elif tokens and tokens & set(WorldModel._tokenize(problem)):
                hints.append(f"Past solution hint: {problem[:140]}")
            if len(hints) >= max(1, int(limit)):
                break
        return hints

    @staticmethod
    def _strategy_hints(domains: List[str], *, action: str = "", job_type: str = "") -> List[str]:
        hints: List[str] = []
        domain_set = {str(item or "").strip().lower() for item in (domains or []) if str(item or "").strip()}
        if "system" in domain_set:
            hints.append("Verify frontmost app and state before UI or terminal actions.")
        if "filesystem" in domain_set:
            hints.append("Resolve absolute path and validate target existence before write/delete.")
        if "research" in domain_set:
            hints.append("Collect sources first, then synthesize, then verify claims.")
        if "coding" in domain_set:
            hints.append("Prefer deterministic build-test-verify loops over single-pass code generation.")
        if "api" in domain_set:
            hints.append("Prefer API or programmatic path before GUI fallback.")
        if str(job_type or "").strip().lower() == "system_automation":
            hints.append("Use fail-fast policy for dangerous commands and blocked permissions.")
        if str(action or "").strip().lower() == "multi_task":
            hints.append("Enforce DAG dependencies before executing the next step.")
        return list(dict.fromkeys(hints))

    def build_snapshot(
        self,
        *,
        user_id: str,
        query: str,
        goal_graph: Dict[str, Any] | None = None,
        memory_results: Dict[str, Any] | None = None,
        action: str = "",
        job_type: str = "",
    ) -> Dict[str, Any]:
        memory_results = memory_results if isinstance(memory_results, dict) else {}
        domains = self._infer_domains(query, action=action, job_type=job_type, goal_graph=goal_graph)
        facts = self.search_facts(query, limit=5)
        similar = self.find_similar_experiences(query, action=action, job_type=job_type, limit=3)
        episodic_hints = self._memory_hints(memory_results, "episodic", limit=2)
        semantic_hints = self._memory_hints(memory_results, "semantic", limit=2)
        kb_hints = self._kb_hints(query, action=action, limit=2)
        strategy_hints = self._strategy_hints(domains, action=action, job_type=job_type)

        constraints = goal_graph.get("constraints", {}) if isinstance(goal_graph, dict) else {}
        working_memory = {
            "active_goal": str(query or "")[:240],
            "action": str(action or ""),
            "job_type": str(job_type or ""),
            "domains": list(domains),
            "constraints": dict(constraints) if isinstance(constraints, dict) else {},
            "user_id": str(user_id or ""),
        }

        summary_parts: List[str] = []
        if domains:
            summary_parts.append("domains=" + ", ".join(domains[:4]))
        if strategy_hints:
            summary_parts.append("strategy=" + " | ".join(strategy_hints[:2]))
        if similar:
            summary_parts.append("experience_hits=" + str(len(similar)))
        summary = "; ".join(summary_parts).strip()

        return {
            "working_memory": working_memory,
            "domains": domains,
            "facts": facts,
            "episodic_hints": episodic_hints,
            "semantic_hints": semantic_hints,
            "knowledge_hints": kb_hints,
            "similar_experiences": similar,
            "strategy_hints": strategy_hints,
            "summary": summary,
        }


_world_model: WorldModel | None = None


def get_world_model() -> WorldModel:
    global _world_model
    if _world_model is None:
        _world_model = WorldModel()
    return _world_model
