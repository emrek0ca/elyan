"""
Research Session Management - Persist and retrieve research results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from utils.logger import get_logger

logger = get_logger("research.session")


@dataclass
class ResearchSession:
    """Persisted research session."""
    session_id: str
    queries: List[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_query(self, query: str, result: object):
        """Add a query result to the session."""
        self.queries.append({
            "query": query,
            "result": result.to_dict() if hasattr(result, "to_dict") else str(result),
            "timestamp": datetime.now().isoformat(),
        })
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ResearchSession:
        """Deserialize from dict."""
        return cls(
            session_id=data.get("session_id", ""),
            queries=data.get("queries", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


def _get_sessions_dir() -> Path:
    """Get ~/.elyan/research/sessions directory."""
    sessions_dir = Path.home() / ".elyan" / "research" / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _get_session_path(session_id: str) -> Path:
    """Get path for a session JSON file."""
    return _get_sessions_dir() / f"{session_id}.json"


def get_research_session(session_id: str) -> Optional[ResearchSession]:
    """Load a research session from disk."""
    session_path = _get_session_path(session_id)
    if not session_path.exists():
        logger.warning(f"Session not found: {session_id}")
        return None

    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
        session = ResearchSession.from_dict(data)
        logger.info(f"Loaded session {session_id} ({len(session.queries)} queries)")
        return session
    except Exception as e:
        logger.error(f"Failed to load session {session_id}: {e}")
        return None


def save_research_session(session: ResearchSession) -> bool:
    """Save a research session to disk."""
    session_path = _get_session_path(session.session_id)
    try:
        session_path.write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Saved session {session.session_id} to {session_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save session {session.session_id}: {e}")
        return False


def list_research_sessions() -> List[dict]:
    """List all research sessions."""
    sessions_dir = _get_sessions_dir()
    sessions = []

    try:
        for session_file in sorted(sessions_dir.glob("*.json")):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", ""),
                    "created_at": data.get("created_at", ""),
                    "query_count": len(data.get("queries", [])),
                    "last_query": (
                        data.get("queries", [])[-1].get("query", "")
                        if data.get("queries")
                        else ""
                    ),
                })
            except Exception as e:
                logger.warning(f"Failed to parse session file {session_file}: {e}")

        return sessions
    except Exception as e:
        logger.error(f"Failed to list sessions: {e}")
        return []


__all__ = [
    "ResearchSession",
    "get_research_session",
    "save_research_session",
    "list_research_sessions",
]
