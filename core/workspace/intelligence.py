"""
core/workspace/intelligence.py
──────────────────────────────────────────────────────────────────────────────
Workspace Intelligence Engine — Tenant-level learning layer.

Answers the question: "What does THIS workspace know how to do well?"

Reads from persisted operational data (without touching personal user data)
and builds a workspace profile: dominant tasks, reliable tools, preferred
integrations, peak activity patterns, and recent capability improvements.

This is the "Tenant / workspace intelligence" tier described in the vision.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.observability.logger import get_structured_logger

slog = get_structured_logger("workspace_intelligence")


@dataclass
class WorkspaceProfile:
    workspace_id: str
    dominant_task_types: list[str] = field(default_factory=list)  # top 5 task types by volume
    reliable_tools: list[str] = field(default_factory=list)       # tools with >80% success rate
    weak_tools: list[str] = field(default_factory=list)           # tools with <50% success rate
    preferred_domains: list[str] = field(default_factory=list)    # coding / research / office / system
    total_tasks: int = 0
    success_rate: float = 0.0
    avg_task_latency_ms: float = 0.0
    most_active_hour: int = -1                                     # 0-23
    suggested_shortcuts: list[dict[str, Any]] = field(default_factory=list)
    learning_momentum: float = 0.0                                 # 0.0–1.0, how fast quality is improving
    computed_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "dominant_task_types": self.dominant_task_types,
            "reliable_tools": self.reliable_tools,
            "weak_tools": self.weak_tools,
            "preferred_domains": self.preferred_domains,
            "total_tasks": self.total_tasks,
            "success_rate": round(self.success_rate, 3),
            "avg_task_latency_ms": round(self.avg_task_latency_ms, 1),
            "most_active_hour": self.most_active_hour,
            "suggested_shortcuts": self.suggested_shortcuts[:5],
            "learning_momentum": round(self.learning_momentum, 3),
            "computed_at": self.computed_at,
        }

    def to_prompt_fragment(self) -> str:
        parts: list[str] = []
        if self.dominant_task_types:
            parts.append(f"Bu workspace'de en sık yapılan görevler: {', '.join(self.dominant_task_types[:3])}")
        if self.reliable_tools:
            parts.append(f"En güvenilir araçlar: {', '.join(self.reliable_tools[:3])}")
        if self.preferred_domains:
            parts.append(f"Ağırlıklı çalışma alanı: {self.preferred_domains[0]}")
        if self.success_rate > 0:
            parts.append(f"Görev başarı oranı: %{int(self.success_rate * 100)}")
        return " | ".join(parts) if parts else ""


class WorkspaceIntelligenceEngine:
    """
    Builds and caches workspace intelligence profiles.

    Profile is rebuilt lazily (max once per hour per workspace) from the
    operational_feedback and global_tool_reliability tables.
    """

    _CACHE_TTL_SECONDS = 3600  # 1 hour

    def __init__(self) -> None:
        self._cache: Dict[str, WorkspaceProfile] = {}
        self._cache_times: Dict[str, float] = {}

    # ─── Public API ──────────────────────────────────────────────────────

    def get_profile(self, workspace_id: str, *, force_refresh: bool = False) -> WorkspaceProfile:
        """Return the workspace profile, refreshing if stale."""
        wid = str(workspace_id or "local-workspace")
        now = time.time()
        age = now - self._cache_times.get(wid, 0.0)
        if not force_refresh and wid in self._cache and age < self._CACHE_TTL_SECONDS:
            return self._cache[wid]
        profile = self._build_profile(wid)
        self._cache[wid] = profile
        self._cache_times[wid] = now
        return profile

    def record_task_outcome(
        self,
        workspace_id: str,
        task_type: str,
        tool_names: list[str],
        success: bool,
        latency_ms: float,
        domain: str = "",
    ) -> None:
        """
        Record a task outcome to feed workspace intelligence.
        Called by the agent after each task completes.
        """
        # Invalidate cache so next get_profile is fresh
        wid = str(workspace_id or "local-workspace")
        self._cache_times.pop(wid, None)
        try:
            self._write_feedback(wid, task_type, tool_names, success, latency_ms, domain)
        except Exception as exc:
            slog.log_event("workspace_intel_write_error", {"workspace_id": wid, "error": str(exc)})

    def get_tool_routing_hints(self, workspace_id: str, task_type: str) -> dict[str, Any]:
        """
        Returns tool routing hints for a given task type in this workspace.
        Used by the agent to prefer/avoid tools based on workspace history.
        """
        profile = self.get_profile(workspace_id)
        return {
            "prefer": profile.reliable_tools[:3],
            "avoid": profile.weak_tools[:3],
            "domain": profile.preferred_domains[0] if profile.preferred_domains else "",
        }

    # ─── Internal ────────────────────────────────────────────────────────

    def _build_profile(self, workspace_id: str) -> WorkspaceProfile:
        try:
            return self._build_from_db(workspace_id)
        except Exception as exc:
            slog.log_event("workspace_intel_build_error", {
                "workspace_id": workspace_id, "error": str(exc)
            })
            return WorkspaceProfile(workspace_id=workspace_id)

    def _build_from_db(self, workspace_id: str) -> WorkspaceProfile:
        from core.persistence.runtime_db import get_runtime_database as get_runtime_db
        from sqlalchemy import text as _text
        db = get_runtime_db()

        # 1. Operational feedback → task type frequencies, success rates
        feedback_rows: list[dict] = []
        try:
            with db.local_engine.connect() as conn:
                rows = conn.execute(
                    _text(
                        "SELECT category, outcome, latency_ms, created_at "
                        "FROM operational_feedback "
                        "WHERE workspace_id = :wid "
                        "ORDER BY created_at DESC LIMIT 500"
                    ),
                    {"wid": workspace_id},
                ).fetchall()
                feedback_rows = [dict(r._mapping) for r in rows]
        except Exception:
            pass

        # 2. Tool reliability → reliable/weak tools
        tool_rows: list[dict] = []
        try:
            with db.local_engine.connect() as conn:
                rows = conn.execute(
                    _text(
                        "SELECT tool_name, success_count, failure_count, sample_count, avg_latency_ms "
                        "FROM global_tool_reliability "
                        "WHERE scope = :wid OR scope = 'global' "
                        "ORDER BY sample_count DESC LIMIT 100"
                    ),
                    {"wid": workspace_id},
                ).fetchall()
                tool_rows = [dict(r._mapping) for r in rows]
        except Exception:
            pass

        # 3. Cowork threads → task patterns
        thread_rows: list[dict] = []
        try:
            with db.local_engine.connect() as conn:
                rows = conn.execute(
                    _text(
                        "SELECT title, current_mode, status, created_at "
                        "FROM cowork_threads "
                        "WHERE workspace_id = :wid "
                        "ORDER BY created_at DESC LIMIT 200"
                    ),
                    {"wid": workspace_id},
                ).fetchall()
                thread_rows = [dict(r._mapping) for r in rows]
        except Exception:
            pass

        return self._compute_profile(workspace_id, feedback_rows, tool_rows, thread_rows)

    def _compute_profile(
        self,
        workspace_id: str,
        feedback_rows: list[dict],
        tool_rows: list[dict],
        thread_rows: list[dict],
    ) -> WorkspaceProfile:
        profile = WorkspaceProfile(workspace_id=workspace_id)

        # Task type frequencies
        type_counts: dict[str, int] = {}
        for row in feedback_rows:
            cat = str(row.get("category") or "general")
            type_counts[cat] = type_counts.get(cat, 0) + 1
        profile.dominant_task_types = sorted(type_counts, key=lambda k: -type_counts[k])[:5]

        # Success rate
        if feedback_rows:
            successes = sum(1 for r in feedback_rows if str(r.get("outcome") or "").lower() in {"success", "completed", "ok"})
            profile.total_tasks = len(feedback_rows)
            profile.success_rate = successes / profile.total_tasks
            latencies = [float(r.get("latency_ms") or 0.0) for r in feedback_rows if r.get("latency_ms")]
            profile.avg_task_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0

        # Tool reliability
        reliable, weak = [], []
        for row in tool_rows:
            samples = int(row.get("sample_count") or 0)
            if samples < 3:
                continue
            succ = int(row.get("success_count") or 0)
            fail = int(row.get("failure_count") or 0)
            total = succ + fail
            if total == 0:
                continue
            rate = succ / total
            tool = str(row.get("tool_name") or "")
            if rate >= 0.80:
                reliable.append((tool, rate))
            elif rate <= 0.50:
                weak.append((tool, rate))
        profile.reliable_tools = [t for t, _ in sorted(reliable, key=lambda x: -x[1])][:8]
        profile.weak_tools = [t for t, _ in sorted(weak, key=lambda x: x[1])][:5]

        # Domain detection from thread titles
        domain_keywords: dict[str, list[str]] = {
            "coding": ["kod", "script", "debug", "test", "api", "python", "function", "class", "git"],
            "research": ["araştır", "analiz", "rapor", "incele", "bilgi", "kaynak", "compare"],
            "office": ["sunum", "excel", "word", "tablo", "belge", "doküman", "pdf"],
            "system": ["dosya", "klasör", "terminal", "sistem", "mac", "disk", "uygulama"],
            "browser": ["url", "website", "açık", "tab", "web", "sayfa"],
        }
        domain_scores: dict[str, int] = {}
        for row in thread_rows:
            title = str(row.get("title") or "").lower()
            for domain, keywords in domain_keywords.items():
                if any(kw in title for kw in keywords):
                    domain_scores[domain] = domain_scores.get(domain, 0) + 1
        profile.preferred_domains = sorted(domain_scores, key=lambda k: -domain_scores[k])[:3]

        # Most active hour
        if thread_rows:
            hour_counts: dict[int, int] = {}
            for row in thread_rows:
                ts = float(row.get("created_at") or 0.0)
                if ts > 0:
                    import datetime
                    h = datetime.datetime.fromtimestamp(ts).hour
                    hour_counts[h] = hour_counts.get(h, 0) + 1
            if hour_counts:
                profile.most_active_hour = max(hour_counts, key=lambda k: hour_counts[k])

        # Learning momentum: compare recent 50 vs older 50 success rates
        if len(feedback_rows) >= 100:
            recent_50 = feedback_rows[:50]
            older_50 = feedback_rows[50:100]
            recent_succ = sum(1 for r in recent_50 if str(r.get("outcome") or "").lower() in {"success", "completed", "ok"})
            older_succ = sum(1 for r in older_50 if str(r.get("outcome") or "").lower() in {"success", "completed", "ok"})
            delta = (recent_succ / 50) - (older_succ / 50)
            profile.learning_momentum = max(0.0, min(1.0, 0.5 + delta))

        # Suggested shortcuts from recent repeated thread titles
        if thread_rows:
            title_counts: dict[str, int] = {}
            for row in thread_rows:
                t = str(row.get("title") or "").strip()
                if len(t) > 5:
                    title_counts[t] = title_counts.get(t, 0) + 1
            shortcuts = [
                {"label": title, "count": cnt}
                for title, cnt in sorted(title_counts.items(), key=lambda x: -x[1])
                if cnt >= 2
            ][:5]
            profile.suggested_shortcuts = shortcuts

        profile.computed_at = time.time()
        return profile

    def _write_feedback(
        self,
        workspace_id: str,
        task_type: str,
        tool_names: list[str],
        success: bool,
        latency_ms: float,
        domain: str,
    ) -> None:
        """Write outcome signal to operational_feedback and global_tool_reliability tables."""
        from core.persistence.runtime_db import get_runtime_database as get_runtime_db
        from sqlalchemy import text as _text
        import uuid, json as _json
        db = get_runtime_db()
        outcome = "success" if success else "failure"
        now = time.time()
        reward = 1.0 if success else 0.0
        with db.local_engine.begin() as conn:
            # 1. Write task-level feedback
            conn.execute(
                _text(
                    "INSERT OR IGNORE INTO operational_feedback "
                    "(feedback_id, workspace_id, user_id, entity_id, category, outcome, reward, "
                    "latency_ms, recovery_count, payload_json, created_at) "
                    "VALUES (:fid, :wid, :uid, :eid, :cat, :outcome, :reward, "
                    ":lat, :rec, :meta, :ts)"
                ),
                {
                    "fid": f"wif_{uuid.uuid4().hex[:12]}",
                    "wid": workspace_id,
                    "uid": "workspace-agent",
                    "eid": f"ws_{workspace_id}",
                    "cat": str(domain or task_type or "general"),
                    "outcome": outcome,
                    "reward": reward,
                    "lat": float(latency_ms or 0.0),
                    "rec": 0,
                    "meta": _json.dumps({"task_type": task_type, "tools": tool_names}),
                    "ts": now,
                },
            )
            # 2. Update per-tool reliability for each tool used
            for tool in tool_names:
                if not tool:
                    continue
                stat_id = f"{workspace_id}::{tool}"
                row = conn.execute(
                    _text(
                        "SELECT success_count, failure_count, sample_count, avg_latency_ms "
                        "FROM global_tool_reliability WHERE stat_id = :sid"
                    ),
                    {"sid": stat_id},
                ).fetchone()
                if row:
                    s_cnt = int(row[0] or 0) + (1 if success else 0)
                    f_cnt = int(row[1] or 0) + (0 if success else 1)
                    n = int(row[2] or 0) + 1
                    avg_lat = ((float(row[3] or 0.0) * (n - 1)) + float(latency_ms or 0.0)) / max(n, 1)
                    conn.execute(
                        _text(
                            "UPDATE global_tool_reliability "
                            "SET success_count=:sc, failure_count=:fc, sample_count=:n, "
                            "avg_reward=:rw, avg_latency_ms=:lat, updated_at=:ts "
                            "WHERE stat_id=:sid"
                        ),
                        {"sc": s_cnt, "fc": f_cnt, "n": n, "rw": reward,
                         "lat": avg_lat, "ts": now, "sid": stat_id},
                    )
                else:
                    conn.execute(
                        _text(
                            "INSERT INTO global_tool_reliability "
                            "(stat_id, scope, tool_name, success_count, failure_count, "
                            "sample_count, avg_reward, avg_latency_ms, metadata_json, updated_at) "
                            "VALUES (:sid, :scope, :tool, :sc, :fc, :n, :rw, :lat, :meta, :ts)"
                        ),
                        {
                            "sid": stat_id,
                            "scope": workspace_id,
                            "tool": tool,
                            "sc": 1 if success else 0,
                            "fc": 0 if success else 1,
                            "n": 1,
                            "rw": reward,
                            "lat": float(latency_ms or 0.0),
                            "meta": _json.dumps({"task_type": task_type}),
                            "ts": now,
                        },
                    )


# ─── Singleton ────────────────────────────────────────────────────────────────

_intelligence: Optional[WorkspaceIntelligenceEngine] = None


def get_workspace_intelligence() -> WorkspaceIntelligenceEngine:
    global _intelligence
    if _intelligence is None:
        _intelligence = WorkspaceIntelligenceEngine()
    return _intelligence


__all__ = [
    "WorkspaceProfile",
    "WorkspaceIntelligenceEngine",
    "get_workspace_intelligence",
]
