"""
Vision Session Management — Persist and retrieve analysis results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from utils.logger import get_logger

logger = get_logger("vision.session")


@dataclass
class VisionSession:
    """Persisted vision session."""
    session_id: str
    entries: List[dict] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def add_entry(self, image_path: str, analysis_type: str, text: str):
        """Add an analysis entry to the session."""
        self.entries.append({
            "timestamp": datetime.now().isoformat(),
            "image_path": image_path,
            "analysis_type": analysis_type,
            "text": text,
        })
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> VisionSession:
        """Deserialize from dict."""
        return cls(
            session_id=data.get("session_id", ""),
            entries=data.get("entries", []),
            created_at=data.get("created_at", datetime.now().isoformat()),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


def _get_sessions_dir() -> Path:
    """Get ~/.elyan/vision_sessions directory."""
    sessions_dir = Path.home() / ".elyan" / "vision_sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    return sessions_dir


def _get_session_path(session_id: str) -> Path:
    """Get path for a session JSON file."""
    return _get_sessions_dir() / f"{session_id}.json"


def get_vision_session(session_id: str) -> Optional[VisionSession]:
    """Load a vision session from disk."""
    session_path = _get_session_path(session_id)
    if not session_path.exists():
        logger.warning(f"Session not found: {session_id}")
        return None

    try:
        data = json.loads(session_path.read_text(encoding="utf-8"))
        session = VisionSession.from_dict(data)
        logger.info(f"Loaded vision session {session_id} ({len(session.entries)} entries)")
        return session
    except Exception as e:
        logger.error(f"Failed to load session {session_id}: {e}")
        return None


def save_vision_session(session: VisionSession) -> bool:
    """Save a vision session to disk."""
    session_path = _get_session_path(session.session_id)
    try:
        session_path.write_text(
            json.dumps(session.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        logger.info(f"Saved vision session {session.session_id} to {session_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to save session {session.session_id}: {e}")
        return False


def list_vision_sessions() -> List[dict]:
    """List all vision sessions."""
    sessions_dir = _get_sessions_dir()
    sessions = []

    try:
        for session_file in sorted(sessions_dir.glob("*.json")):
            try:
                data = json.loads(session_file.read_text(encoding="utf-8"))
                sessions.append({
                    "session_id": data.get("session_id", ""),
                    "created_at": data.get("created_at", ""),
                    "entry_count": len(data.get("entries", [])),
                    "last_analysis": (
                        data.get("entries", [])[-1].get("analysis_type", "")
                        if data.get("entries")
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
    "VisionSession",
    "get_vision_session",
    "save_vision_session",
    "list_vision_sessions",
]
