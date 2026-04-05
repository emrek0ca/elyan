"""
core/task_continuity.py
──────────────────────────────────────────────────────────────────────────────
Task Continuity Manager — "Kaldığı yerden devam" layer.

Surfaces interrupted or stalled tasks to the user at session start and
provides structured resume suggestions. This is the cross-session memory
that makes Elyan feel like it never forgets.

Inspiration from BrightOS: central_nerve + neural_store pattern.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from core.observability.logger import get_structured_logger

slog = get_structured_logger("task_continuity")

_STALL_THRESHOLD_HOURS = 1.0      # threads inactive this long are "stalled"
_RESUME_WINDOW_HOURS = 72.0       # look back 72h for continuity candidates
_MAX_RESUME_SUGGESTIONS = 5


@dataclass
class ContinuityCandidate:
    thread_id: str
    title: str
    status: str
    current_step: str
    goal: str
    last_active_at: float
    interrupted_hours_ago: float
    risk_level: str = "low"
    mode: str = "cowork"
    resume_hint: str = ""          # what to say to resume this thread

    def to_dict(self) -> dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "title": self.title,
            "status": self.status,
            "current_step": self.current_step,
            "goal": self.goal,
            "last_active_at": self.last_active_at,
            "interrupted_hours_ago": round(self.interrupted_hours_ago, 1),
            "risk_level": self.risk_level,
            "mode": self.mode,
            "resume_hint": self.resume_hint,
        }

    def to_prompt_fragment(self) -> str:
        h = round(self.interrupted_hours_ago, 1)
        return (
            f"Yarım kalan görev ({h} saat önce): \"{self.title}\" — "
            f"Son adım: {self.current_step or 'belirsiz'}"
        )


class TaskContinuityManager:
    """
    Queries the cowork_threads table for stalled or interrupted tasks
    and provides structured resume suggestions.
    """

    def get_continuity_surface(
        self,
        workspace_id: str,
        user_id: str = "local",
        *,
        max_results: int = _MAX_RESUME_SUGGESTIONS,
    ) -> dict[str, Any]:
        """
        Returns the session start continuity surface:
        - open threads that were interrupted
        - stalled (queued but not started) tasks
        - failed tasks that can be retried
        """
        try:
            candidates = self._find_candidates(workspace_id)
        except Exception as exc:
            slog.log_event("continuity_query_error", {"error": str(exc)})
            candidates = []

        candidates = candidates[:max_results]
        prompt_lines = [c.to_prompt_fragment() for c in candidates[:3]]

        return {
            "has_open_tasks": len(candidates) > 0,
            "count": len(candidates),
            "candidates": [c.to_dict() for c in candidates],
            "prompt_fragment": ("\n".join(prompt_lines)) if prompt_lines else "",
            "session_start_message": self._build_session_message(candidates),
        }

    def get_session_start_message(self, workspace_id: str) -> str:
        """Short message to inject into the first agent response of a session."""
        surface = self.get_continuity_surface(workspace_id)
        return surface.get("session_start_message", "")

    # ─── Internal ────────────────────────────────────────────────────────

    def _find_candidates(self, workspace_id: str) -> list[ContinuityCandidate]:
        from core.persistence.runtime_db import get_runtime_database as get_runtime_db
        from sqlalchemy import text as _text
        db = get_runtime_db()
        now = time.time()
        cutoff = now - (_RESUME_WINDOW_HOURS * 3600)
        stall_cutoff = now - (_STALL_THRESHOLD_HOURS * 3600)
        candidates: list[ContinuityCandidate] = []

        try:
            with db.local_engine.connect() as conn:
                rows = conn.execute(
                    _text(
                        "SELECT thread_id, title, status, current_mode, updated_at, metadata_json "
                        "FROM cowork_threads "
                        "WHERE workspace_id = :wid "
                        "  AND updated_at > :cutoff "
                        "  AND status NOT IN ('completed', 'cancelled', 'archived') "
                        "ORDER BY updated_at DESC LIMIT 50"
                    ),
                    {"wid": workspace_id, "cutoff": cutoff},
                ).fetchall()
        except Exception:
            return []

        for row in rows:
            r = dict(row._mapping)
            updated_at = float(r.get("updated_at") or 0.0)
            if updated_at > stall_cutoff:
                continue  # actively running — not a continuity candidate

            hours_ago = (now - updated_at) / 3600.0
            status = str(r.get("status") or "unknown")
            title = str(r.get("title") or "").strip()
            mode = str(r.get("current_mode") or "cowork")

            # Decode metadata
            try:
                import json
                meta = json.loads(str(r.get("metadata_json") or "{}"))
            except Exception:
                meta = {}

            goal = str(meta.get("goal") or title)
            current_step = str(meta.get("current_step") or "")
            risk_level = str(meta.get("risk_level") or "low")

            resume_hint = self._build_resume_hint(status, title, current_step)

            candidates.append(ContinuityCandidate(
                thread_id=str(r.get("thread_id") or ""),
                title=title,
                status=status,
                current_step=current_step,
                goal=goal,
                last_active_at=updated_at,
                interrupted_hours_ago=hours_ago,
                risk_level=risk_level,
                mode=mode,
                resume_hint=resume_hint,
            ))

        # Sort: failed first (retry opportunity), then running/stalled by recency
        def _sort_key(c: ContinuityCandidate) -> tuple:
            priority = 0 if c.status == "failed" else (1 if c.status == "running" else 2)
            return (priority, c.interrupted_hours_ago)

        candidates.sort(key=_sort_key)
        return candidates

    def _build_resume_hint(self, status: str, title: str, current_step: str) -> str:
        if status == "failed":
            return f'"{title}" görevini tekrar deneyeyim mi?'
        if status == "running":
            step_part = f' — {current_step}' if current_step else ''
            return f'"{title}" görevi{step_part} aşamasında durdu. Devam edeyim mi?'
        if status in {"queued", "planning"}:
            return f'"{title}" görevi henüz başlamamış. Şimdi başlayalım mı?'
        return f'"{title}" görevine devam edeyim mi?'

    def _build_session_message(self, candidates: list[ContinuityCandidate]) -> str:
        if not candidates:
            return ""
        if len(candidates) == 1:
            c = candidates[0]
            return (
                f"Geçen oturumdan yarım kalan bir görev var: "
                f"\"{c.title}\" ({round(c.interrupted_hours_ago, 1)} saat önce). "
                f"{c.resume_hint}"
            )
        return (
            f"Geçen oturumdan {len(candidates)} yarım kalan görev var. "
            f"En öncelikli: \"{candidates[0].title}\" "
            f"({round(candidates[0].interrupted_hours_ago, 1)} saat önce). "
            f"Devam edelim mi?"
        )


# ─── Singleton ────────────────────────────────────────────────────────────────

_manager: Optional[TaskContinuityManager] = None


def get_task_continuity_manager() -> TaskContinuityManager:
    global _manager
    if _manager is None:
        _manager = TaskContinuityManager()
    return _manager


__all__ = [
    "ContinuityCandidate",
    "TaskContinuityManager",
    "get_task_continuity_manager",
]
